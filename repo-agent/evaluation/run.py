"""Bounded paid evaluation. Persists every case; completed cases are reused on continuation."""

import argparse
import asyncio
import json
import time
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from provenance import freeze

from repo_agent.executor import Executor
from repo_agent.graph import build_graph
from repo_agent.model import DeepSeekModel
from repo_agent.repository import Repository
from repo_agent.settings import Settings
from repo_agent.store import Store
from repo_agent.tools import SCHEMAS, Tools


class FaultTools(Tools):
    def __init__(self, *args, fault=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fault = fault
        self.triggered = False

    async def call(self, context, name, raw):
        if name == self.fault and not self.triggered:
            self.triggered = True
            raise TimeoutError("Evaluation-injected transient tool timeout; no source evidence returned")
        return await super().call(context, name, raw)


def summarize(root: Path):
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(root.glob("case-*.json"))]
    scored = [
        r
        for r in rows
        if r.get("task_success") is not None and not r.get("requires_review") and "error" not in r
    ]
    tool_rows = [r for r in rows if r.get("tool_selection_correct") is not None]
    calls = sum(r.get("tool_calls", 0) for r in rows)
    valid = sum(r.get("valid_tool_arguments", 0) for r in rows)
    retrieval = [r for r in rows if r.get("retrieval_recall_at_5") is not None]
    latencies = sorted(r["latency_ms"] for r in rows if "latency_ms" in r)
    summary = {
        "execution_errors": sum("error" in r for r in rows),
        "cases_completed": len(rows),
        "task_success_scored_cases": len(scored),
        "task_success_rate": sum(r["task_success"] for r in scored) / len(scored) if scored else None,
        "semantic_review_pending": sum(r.get("requires_review", False) for r in rows),
        "tool_selection_scored_cases": len(tool_rows),
        "tool_selection_accuracy": sum(r["tool_selection_correct"] for r in tool_rows) / len(tool_rows)
        if tool_rows
        else None,
        "tool_argument_calls": calls,
        "tool_argument_accuracy": valid / calls if calls else None,
        "retrieval_cases": len(retrieval),
        "raw_fts_recall_at_5": sum(r["retrieval_recall_at_5"] for r in retrieval) / len(retrieval)
        if retrieval
        else None,
        "latency_p50_ms": latencies[len(latencies) // 2] if latencies else None,
        "latency_p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        if latencies
        else None,
        "metric_scope": "Version-pinned Click engineering regression; AI-authored source/contract labels. Unreviewed semantic cases excluded from task success.",
        "raw_retrieval_scope": "SQLite FTS query field, not model query reformulation or vector retrieval.",
    }
    (root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--split", choices=["all", "dev", "holdout"], default="all")
    parser.add_argument("--output", default=".local/evaluation-v1")
    parser.add_argument("--run-id", default="v1")
    parser.add_argument("--ids", default="", help="Comma-separated case IDs for explicit badcase regression")
    args = parser.parse_args()
    cfg = Settings(max_steps=10, max_output_tokens=1600)
    store = Store(cfg.data_dir)
    cases = [
        json.loads(line) for line in Path("evaluation/cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    cases = [c for c in cases if args.split == "all" or c["split"] == args.split][
        : max(0, min(args.limit, 80))
    ]
    if args.ids:
        selected = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in selected]
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    freeze(root, cfg, {"ids": args.ids, "split": args.split, "limit": args.limit})
    semaphore = asyncio.Semaphore(2)
    async with AsyncSqliteSaver.from_conn_string(
        str(cfg.data_dir / f"evaluation-{args.run_id}-checkpoints.sqlite3")
    ) as saver:

        async def one(case):
            path = root / ("case-" + case["id"] + ".json")
            if path.exists():
                return
            async with semaphore:
                job = "eval-" + args.run_id + "-" + case["id"]
                tools = FaultTools(store, Repository(store), Executor(cfg, store), fault=case["fault"])
                graph = build_graph(DeepSeekModel(cfg, store), tools, store, saver, cfg.max_steps)
                config = {"configurable": {"thread_id": job}, "recursion_limit": 35}
                started = time.perf_counter()
                row = {
                    "id": case["id"],
                    "category": case["category"],
                    "split": case["split"],
                    "requires_review": case["category"] in {"security", "ambiguous", "failure"},
                    "task_success": None,
                    "tool_selection_correct": None,
                    "retrieval_recall_at_5": None,
                }
                try:
                    state = await graph.aget_state(config)
                    if state.values.get("answer") or state.interrupts:
                        result = state.values
                        interrupted = bool(state.interrupts)
                    else:
                        result = await graph.ainvoke(
                            {
                                "job": job,
                                "owner": "eval-owner",
                                "workspace": "eval-workspace",
                                "snapshot": case["snapshot"],
                                "question": case["question"],
                            },
                            config,
                        )
                        interrupted = bool(result.get("__interrupt__"))
                    messages = result.get("messages", [])
                    events = []
                    after = 0
                    while True:
                        batch = store.events(job, after)
                        events.extend(batch)
                        if len(batch) < 100:
                            break
                        after = batch[-1]["seq"]
                    calls = [
                        {"function": {"name": e["data"]["name"], "arguments": e["data"]["arguments"]}}
                        for e in events
                        if e["kind"] == "tool_call"
                    ]
                    if not calls:
                        calls = [call for message in messages for call in message.get("tool_calls", [])]
                    names = [call["function"]["name"] for call in calls]
                    valid = 0
                    for call in calls:
                        try:
                            SCHEMAS[call["function"]["name"]][0].model_validate_json(
                                call["function"]["arguments"]
                            )
                            valid += 1
                        except (ValueError, KeyError):
                            pass
                    report = store.report(job, "eval-owner")
                    answer = result.get("answer", "")
                    paths = {c["path"] for c in (report or {}).get("citations", [])}
                    checks = {
                        "terms": all(term.lower() in answer.lower() for term in case["expected_terms"]),
                        "paths": all(path in paths for path in case["expected_paths"]),
                        "tools": all(tool in names for tool in case["expected_tools"]),
                        "step_limit": result.get("outcome") != "STEP_LIMIT",
                        "approval": interrupted if case["expect"] == "approval" else not interrupted,
                        "citation_integrity": not (report or {}).get("unknown_citation_ids", []),
                    }
                    if case["expected_tools"]:
                        row["tool_selection_correct"] = checks["tools"]
                    if not row["requires_review"]:
                        row["task_success"] = all(checks.values())
                    if case["retrieval_query"] and case["expected_paths"]:
                        found = Repository(store).search(
                            "eval-owner", "eval-workspace", case["snapshot"], case["retrieval_query"], 5
                        )
                        row["retrieval_recall_at_5"] = len(
                            set(case["expected_paths"]) & {c["path"] for c in found}
                        ) / len(set(case["expected_paths"]))
                    with store.connect() as db:
                        usage = dict(
                            db.execute(
                                "SELECT COUNT(*) AS calls,COALESCE(SUM(input_tokens),0) AS input_tokens,COALESCE(SUM(output_tokens),0) AS output_tokens,COALESCE(SUM(cached_tokens),0) AS cached_tokens,SUM(reserved_cny) AS reserved_cny FROM model_calls WHERE job=?",
                                (job,),
                            ).fetchone()
                        )
                    row |= {
                        "answer": answer,
                        "citations": (report or {}).get("citations", []),
                        "checks": checks,
                        "tool_names": names,
                        "tool_calls": len(calls),
                        "valid_tool_arguments": valid,
                        "usage": usage,
                        "pending_approval": result.get("pending_approval"),
                        "fault_injected": tools.triggered,
                        "outcome": result.get("outcome", "ANSWER"),
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                except Exception as exc:
                    row |= {
                        "error": type(exc).__name__,
                        "detail": str(exc).splitlines()[0][:200],
                        "task_success": False,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
                print(
                    json.dumps(
                        {
                            "case": case["id"],
                            "success": row["task_success"],
                            "review": row["requires_review"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

        await asyncio.gather(*(one(case) for case in cases))
    print(json.dumps(summarize(root), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
