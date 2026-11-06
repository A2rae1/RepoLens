import asyncio
import json

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from repo_agent.executor import Executor
from repo_agent.graph import build_graph
from repo_agent.model import DeepSeekModel
from repo_agent.reporting import make_report
from repo_agent.repository import Repository
from repo_agent.settings import Settings
from repo_agent.store import Store
from repo_agent.tools import Tools


async def main():
    cfg = Settings(max_steps=5)
    store = Store(cfg.data_dir)
    manifest = json.loads((cfg.data_dir / "sample_manifest.json").read_text(encoding="utf-8"))
    job = "live-click-python-requirement"
    tools = Tools(store, Repository(store), Executor(cfg, store))
    async with AsyncSqliteSaver.from_conn_string(
        str(cfg.data_dir / "live-smoke-checkpoints.sqlite3")
    ) as saver:
        graph = build_graph(DeepSeekModel(cfg, store), tools, store, saver, cfg.max_steps)
        config = {"configurable": {"thread_id": job}, "recursion_limit": 40}
        saved = await graph.aget_state(config)
        if saved.values.get("answer"):
            result = saved.values
            store.save_report(job, "eval-owner", make_report(result, store))
        else:
            result = await graph.ainvoke(
                {
                    "job": job,
                    "owner": "eval-owner",
                    "workspace": "eval-workspace",
                    "snapshot": manifest["snapshot"],
                    "question": "这个固定版本的Click声明支持什么Python版本？请读取pyproject.toml并引用原文证据。不要执行代码。",
                },
                config,
            )
    report = store.report(job, "eval-owner")
    if result.get("__interrupt__") or not report or not report["citations"]:
        raise RuntimeError("Live graph did not produce a cited report")
    output = cfg.data_dir / "live_graph_smoke.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "LIVE_CITED_REPORT",
                "steps": report["steps"],
                "citations": len(report["citations"]),
                "answer": report["answer"][:1200],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
