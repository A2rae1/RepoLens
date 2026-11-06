import json

import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from repo_agent.executor import Executor
from repo_agent.graph import build_graph
from repo_agent.settings import Settings
from repo_agent.tools import Tools


class FixtureModel:
    """Deterministic test double; these tests do not measure real LLM quality."""

    async def complete(self, job, messages, tools):
        tool_results = [m for m in messages if m["role"] == "tool"]
        if not tool_results:
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call1",
                        "type": "function",
                        "function": {"name": "search_evidence", "arguments": '{"query":"Python"}'},
                    }
                ],
            }
        data = json.loads(tool_results[-1]["content"])
        evidence = data.get("evidence", [])
        answer = f"Python >=3.12 [{evidence[0]['id']}]" if evidence else "未找到证据"
        return {"role": "assistant", "content": answer}


class ApprovalModel:
    async def complete(self, job, messages, tools):
        if any("验证实际结果" in (m.get("content") or "") for m in messages):
            return {"role": "assistant", "content": "已收到实际验证状态；未运行不能称成功。"}
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "approve1",
                    "type": "function",
                    "function": {
                        "name": "propose_validation",
                        "arguments": '{"recipe":"python_ast","reason":"检查Python语法"}',
                    },
                }
            ],
        }


def initial(snapshot, question="Python依赖是什么"):
    return {
        "job": "job",
        "owner": "alice",
        "workspace": "workspace",
        "snapshot": snapshot["id"],
        "question": question,
    }


async def test_real_langgraph_tool_routing_report_and_checkpoint(evidence, tmp_path):
    store, repository, snapshot = evidence
    cfg = Settings(data_dir=tmp_path)
    tools = Tools(store, repository, Executor(cfg, store))
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "graph.sqlite")) as saver:
        graph = build_graph(FixtureModel(), tools, store, saver)
        result = await graph.ainvoke(initial(snapshot), {"configurable": {"thread_id": "job"}})
        assert "3.12" in result["answer"]
        report = store.report("job", "alice")
        assert report["citations"][0]["commit"] == "a" * 40
        assert store.report("job", "bob") is None
    # A second saver connection loads persisted state, not an in-memory object.
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "graph.sqlite")) as saver:
        graph = build_graph(FixtureModel(), tools, store, saver)
        saved = await graph.aget_state({"configurable": {"thread_id": "job"}})
        assert saved.values["answer"] == result["answer"]


async def test_human_interrupt_survives_restart_and_no_execution_without_approval(evidence, tmp_path):
    store, repository, snapshot = evidence
    cfg = Settings(data_dir=tmp_path, executor_enabled=False)
    tools = Tools(store, repository, Executor(cfg, store))
    config = {"configurable": {"thread_id": "job"}}
    path = str(tmp_path / "approval.sqlite")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = build_graph(ApprovalModel(), tools, store, saver)
        result = await graph.ainvoke(initial(snapshot), config)
        assert result["__interrupt__"]
        key = result["pending_approval"]
        assert not any(e["kind"] == "validation_result" for e in store.events("job"))
    store.decide("job", key, False)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = build_graph(ApprovalModel(), tools, store, saver)
        result = await graph.ainvoke(Command(resume={"approved": True}), config)
        assert not result.get("__interrupt__")
        validation = [e for e in store.events("job") if e["kind"] == "validation_result"]
        assert (
            validation[0]["data"]["reason"] == "USER_REJECTED"
        )  # forged resume payload did not grant permission.


async def test_tool_schema_rejects_arbitrary_command_and_cross_scope(evidence, tmp_path):
    store, repository, snapshot = evidence
    tools = Tools(store, repository, Executor(Settings(data_dir=tmp_path), store))
    ctx = initial(snapshot)
    with pytest.raises(ValueError):
        await tools.call(ctx, "propose_validation", '{"recipe":"shell","command":"rm -rf /"}')
    with pytest.raises(PermissionError):
        await tools.call(ctx, "read_host_password", "{}")
