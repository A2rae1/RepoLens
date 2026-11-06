"""Real local ES/CPU ablation; no paid model call and no quality claim beyond this corpus."""

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path

from repo_agent.repository import Repository
from repo_agent.retrieval import Embeddings, HybridSearch, Reranker
from repo_agent.settings import Settings
from repo_agent.store import Store


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rerank", action="store_true")
    args = parser.parse_args()
    cfg = Settings(embedding_enabled=True)
    store = Store(cfg.data_dir)
    repository = Repository(store)
    search = HybridSearch(cfg, store, Embeddings(cfg))
    reranker = Reranker(cfg) if args.rerank else None
    cases = [
        json.loads(line) for line in Path("evaluation/cases.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    cases = [c for c in cases if c["retrieval_query"] and c["expected_paths"]]
    await search.setup()
    rows = []
    try:
        for case in cases:
            strategies = ["fts", "bm25", "vector", "hybrid"] + (["hybrid_rerank"] if reranker else [])
            for strategy in strategies:
                started = time.perf_counter()
                if strategy == "fts":
                    found = repository.search(
                        "eval-owner", "eval-workspace", case["snapshot"], case["retrieval_query"], 5
                    )
                else:
                    found = await search.search(
                        "eval-owner",
                        "eval-workspace",
                        case["snapshot"],
                        case["retrieval_query"],
                        10 if strategy == "hybrid_rerank" else 5,
                        "hybrid" if strategy == "hybrid_rerank" else strategy,
                    )
                    if strategy == "hybrid_rerank":
                        found = await reranker.rank(case["retrieval_query"], found, 5)
                relevant = set(case["expected_paths"])
                recall = len(relevant & {r["path"] for r in found}) / len(relevant)
                rows.append(
                    {
                        "case": case["id"],
                        "strategy": strategy,
                        "recall_at_5": recall,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                        "paths": [r["path"] for r in found],
                    }
                )
            print(case["id"], flush=True)
    finally:
        await search.close()
    summary = {}
    for strategy in sorted({r["strategy"] for r in rows}):
        selected = [r for r in rows if r["strategy"] == strategy]
        latency = sorted(r["latency_ms"] for r in selected)
        summary[strategy] = {
            "cases": len(selected),
            "mean_recall_at_5": statistics.mean(r["recall_at_5"] for r in selected),
            "latency_p50_ms": statistics.median(latency),
            "latency_p95_ms": latency[min(len(latency) - 1, int(len(latency) * 0.95))],
        }
    report = {
        "scope": "40 source-path-labelled English queries on one fixed Click repository; AI-authored development cases; warm index; sequential local CPU run; not a universal retrieval comparison",
        "embedding": cfg.embedding_model,
        "reranker": "Xenova/ms-marco-MiniLM-L-6-v2" if reranker else None,
        "summary": summary,
        "rows": rows,
    }
    output = cfg.data_dir / ("retrieval-ablation-rerank.json" if reranker else "retrieval-ablation.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
