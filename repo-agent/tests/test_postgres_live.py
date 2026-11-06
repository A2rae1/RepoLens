import asyncio
import os
import sys
import uuid

import pytest
from test_graph import ApprovalModel, initial

from repo_agent.checkpoints import postgres_saver
from repo_agent.executor import Executor
from repo_agent.graph import build_graph
from repo_agent.settings import Settings
from repo_agent.tools import Tools

pytestmark = pytest.mark.skipif(
    os.environ.get("POSTGRES_IT") != "true", reason="Requires own real Postgres checkpoint database"
)


async def test_real_postgres_interrupt_survives_connection_and_process_restart(evidence, tmp_path):
    store, repository, snapshot = evidence
    thread = "postgres-it-" + uuid.uuid4().hex
    tools = Tools(store, repository, Executor(Settings(data_dir=tmp_path, executor_enabled=False), store))
    async with postgres_saver(os.environ["CHECKPOINT_URL"]) as saver:
        graph = build_graph(ApprovalModel(), tools, store, saver)
        result = await graph.ainvoke(initial(snapshot), {"configurable": {"thread_id": thread}})
        assert result["__interrupt__"]
        store.decide("job", result["pending_approval"], False)
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "tests/checkpoint_child.py",
        str(tmp_path),
        thread,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(child.communicate(), 30)
    # Never dump a connection string from driver errors into the test output.
    assert child.returncode == 0, (
        f"Checkpoint child failed (exit={child.returncode}, diagnostic bytes={len(stderr)})"
    )
    assert b'"cross_process_resume": "PASS"' in stdout
