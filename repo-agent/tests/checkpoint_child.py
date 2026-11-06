"""Separate-process integration probe. Uses a fixture model, never a paid model."""

import asyncio
import json
import os
import sys
from pathlib import Path

from langgraph.types import Command
from test_graph import ApprovalModel

from repo_agent.checkpoints import postgres_saver
from repo_agent.executor import Executor
from repo_agent.graph import build_graph
from repo_agent.repository import Repository
from repo_agent.settings import Settings
from repo_agent.store import Store
from repo_agent.tools import Tools


async def main():
    root, thread = Path(sys.argv[1]), sys.argv[2]
    store = Store(root)
    tools = Tools(store, Repository(store), Executor(Settings(data_dir=root, executor_enabled=False), store))
    async with postgres_saver(os.environ["CHECKPOINT_URL"]) as saver:
        graph = build_graph(ApprovalModel(), tools, store, saver)
        config = {"configurable": {"thread_id": thread}}
        saved = await graph.aget_state(config)
        assert saved.interrupts and saved.values["pending_approval"]
        result = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert not result.get("__interrupt__")
        events = [e for e in store.events(saved.values["job"]) if e["kind"] == "validation_result"]
        assert events[-1]["data"]["reason"] == "USER_REJECTED"
        assert not (await graph.aget_state({"configurable": {"thread_id": thread + "-other"}})).values
        print(
            json.dumps({"cross_process_resume": "PASS", "forged_approval": "DENIED", "other_thread": "EMPTY"})
        )


if __name__ == "__main__":
    asyncio.run(main())
