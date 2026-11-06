import asyncio
import json

from repo_agent.executor import Executor
from repo_agent.settings import Settings
from repo_agent.store import Store


async def main():
    cfg = Settings(executor_enabled=True)
    store = Store(cfg.data_dir)
    manifest = json.loads((cfg.data_dir / "sample_manifest.json").read_text(encoding="utf-8"))
    executor = Executor(cfg, store)
    job = "click-pytest-reproduction-v2"
    plan = executor.plan(job, manifest["snapshot"], "python_pytest")
    key = store.propose(job, plan)
    if store.approval(job, key)["decision"] is None:
        store.decide(job, key, True)
        store.event(
            job,
            "approval_origin",
            {
                "mode": "engineer_test_harness",
                "scope": "pinned public Click pytest, no network, no host secrets",
                "not_real_user_understanding_acceptance": True,
            },
        )
    result = await executor.run("eval-owner", "eval-workspace", job, key)
    (cfg.data_dir / "executor_click_smoke_v2.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "verified": result["verified"],
                "exit_code": result["exit_code"],
                "output_tail": result["output"][-1600:],
            },
            ensure_ascii=False,
        )
    )
    if not result["verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
