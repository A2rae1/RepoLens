"""Small real-model development comparison: scoped packs versus all packs/tools."""

import asyncio
import json
import statistics
import time
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from provenance import freeze

from repo_agent.executor import Executor
from repo_agent.graph import build_graph
from repo_agent.model import DeepSeekModel
from repo_agent.repository import Repository
from repo_agent.settings import Settings
from repo_agent.skills import select_skill
from repo_agent.store import Store
from repo_agent.tools import Tools

CASES = [
    ("env-python", "环境需要哪个最低Python版本？只读取证，不执行。", "environment", ["3.7"]),
    ("env-install", "安装Click需要哪些运行依赖？只读取证，不执行。", "environment", ["colorama"]),
    ("env-build", "构建后端依赖如何配置？只读取证，不执行。", "environment", ["flit"]),
    (
        "env-platform",
        "Java项目能否直接使用这个Python库？解释语言和安装边界，只读取证。",
        "environment",
        ["python"],
    ),
    ("diag-python", "Python报错时，CliRunner如何捕获异常？只读取证，不执行。", "diagnose", ["exception"]),
    ("diag-failure", "安装失败可以先检查哪些配置？不要猜唯一原因，只读取证。", "diagnose", ["python"]),
    (
        "diag-debug",
        "debug：CliRunner的catch_exceptions参数是什么？只读取证。",
        "diagnose",
        ["catch_exceptions"],
    ),
    ("diag-error", "错误诊断：UsageError是什么？只读取证，不执行。", "diagnose", ["usageerror"]),
    ("research-command", "command装饰器定义在哪个文件？只读取证。", "research", ["decorators.py"]),
    (
        "research-option",
        "option小写装饰器定义在哪个文件？不要回答Option类，只读取证。",
        "research",
        ["decorators.py"],
    ),
    ("research-runner", "CliRunner类定义在哪个文件？只读取证。", "research", ["testing.py"]),
    ("research-group", "Group类定义在哪个文件？只读取证。", "research", ["core.py"]),
]


async def main():
    cfg = Settings(max_steps=6, max_output_tokens=800)
    store = Store(cfg.data_dir)
    repository = Repository(store)
    cases = [json.loads(x) for x in Path("evaluation/cases.jsonl").read_text(encoding="utf-8").splitlines()]
    snapshot = cases[0]["snapshot"]
    out = Path(".local/skills-comparison-v1")
    out.mkdir(exist_ok=True)
    freeze(
        out,
        cfg,
        {
            "case_ids": [c[0] for c in CASES],
            "modes": ["scoped", "all"],
            "label_source": "AI-authored development expectations; not blind holdout",
        },
    )
    async with AsyncSqliteSaver.from_conn_string(str(cfg.data_dir / "skills-comparison-v1.sqlite3")) as saver:
        for idx, (identifier, question, expected, terms) in enumerate(CASES):
            modes = ("scoped", "all") if idx % 2 == 0 else ("all", "scoped")
            for mode in modes:
                target = out / (identifier + "-" + mode + ".json")
                if target.exists():
                    continue
                job = "skills-v1-" + identifier + "-" + mode
                graph = build_graph(
                    DeepSeekModel(cfg, store),
                    Tools(store, repository, Executor(cfg, store)),
                    store,
                    saver,
                    6,
                    skill_mode=mode,
                )
                start = time.perf_counter()
                await graph.ainvoke(
                    {
                        "job": job,
                        "owner": "eval-owner",
                        "workspace": "eval-workspace",
                        "snapshot": snapshot,
                        "question": question,
                    },
                    {"configurable": {"thread_id": job}, "recursion_limit": 30},
                )
                report = store.report(job, "eval-owner")
                with store.connect() as db:
                    usage = dict(
                        db.execute(
                            "SELECT COUNT(*) calls,COALESCE(SUM(input_tokens),0) input_tokens,COALESCE(SUM(output_tokens),0) output_tokens,COALESCE(SUM(cached_tokens),0) cached_tokens,COALESCE(SUM(reserved_cny),0) conservative_cny FROM model_calls WHERE job=?",
                            (job,),
                        ).fetchone()
                    )
                # Explicit proxy score: required keyword AND valid citations AND completed answer; semantic correctness is not automatically inferred.
                proxy = (
                    all(
                        term.lower() in report["answer"].lower()
                        or any(term.lower() in c["path"].lower() for c in report["citations"])
                        for term in terms
                    )
                    and bool(report["citations"])
                    and not report["unknown_citation_ids"]
                    and report["completion_reason"] == "ANSWER"
                )
                row = {
                    "id": identifier,
                    "mode": mode,
                    "expected_route": expected,
                    "actual_rule_route": select_skill(question)[0],
                    "route_correct": select_skill(question)[0] == expected,
                    "proxy_gate": proxy,
                    "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                    "usage": usage,
                    "answer": report["answer"],
                    "citations": report["citations"],
                    "completion_reason": report["completion_reason"],
                }
                target.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
                print(identifier, mode, "saved", flush=True)
    rows = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in out.glob("*.json")
        if p.name not in {"provenance.json", "summary.json"}
    ]
    groups = {}
    for mode in ("scoped", "all"):
        selected = [r for r in rows if r["mode"] == mode]
        groups[mode] = {
            "cases": len(selected),
            "input_tokens": sum(r["usage"]["input_tokens"] for r in selected),
            "output_tokens": sum(r["usage"]["output_tokens"] for r in selected),
            "calls": sum(r["usage"]["calls"] for r in selected),
            "conservative_cny": round(sum(r["usage"]["conservative_cny"] for r in selected), 2),
            "proxy_passed": sum(r["proxy_gate"] for r in selected),
            "latency_median_ms": statistics.median(r["latency_ms"] for r in selected),
        }
    summary = {
        "status": "COMPLETE",
        "routing_correct": sum(select_skill(q)[0] == expected for _, q, expected, _ in CASES),
        "routing_cases": 12,
        "groups": groups,
        "scope": "12 AI-authored development questions, real DeepSeek usage, alternating mode order, one Click version. Keyword/citation proxy is not a semantic success rate. Provider cache and generation variance confound latency; no universal improvement claim.",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())
