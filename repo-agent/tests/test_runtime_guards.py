from unittest.mock import AsyncMock, patch

import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from repo_agent.executor import Executor
from repo_agent.graph import build_graph
from repo_agent.model import DeepSeekModel
from repo_agent.settings import Settings
from repo_agent.tools import Tools


@pytest.mark.parametrize(
    "error,expected_reserved",
    [(httpx.ConnectError("TLS setup failed"), 0), (httpx.ReadTimeout("Response unknown"), 1)],
)
async def test_only_proven_unsent_connections_release_budget(evidence, tmp_path, error, expected_reserved):
    store, _, _ = evidence
    cfg = Settings(data_dir=tmp_path, live_model_enabled=True, deepseek_api_key="fixture-not-a-real-key")
    client = AsyncMock()
    client.post.side_effect = error
    with patch("repo_agent.model.httpx.AsyncClient") as factory:
        factory.return_value.__aenter__.return_value = client
        with pytest.raises(type(error)):
            await DeepSeekModel(cfg, store).complete(
                "network-guard", [{"role": "user", "content": "fixture"}], []
            )
    with store.connect() as db:
        assert db.execute("SELECT SUM(reserved_cny) FROM model_calls").fetchone()[0] == expected_reserved


async def test_agent_step_limit_is_not_a_completed_answer(evidence, tmp_path):
    store, repo, snapshot = evidence

    class LoopModel:
        calls = 0

        async def complete(self, job, messages, tools):
            self.calls += 1
            return {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": str(self.calls),
                        "type": "function",
                        "function": {"name": "search_evidence", "arguments": '{"query":"Python"}'},
                    }
                ],
            }

    model = LoopModel()
    cfg = Settings(data_dir=tmp_path)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "limited.sqlite")) as saver:
        graph = build_graph(model, Tools(store, repo, Executor(cfg, store)), store, saver, max_steps=1)
        result = await graph.ainvoke(
            {
                "job": "limit",
                "owner": "alice",
                "workspace": "workspace",
                "snapshot": snapshot["id"],
                "question": "Python version",
            },
            {"configurable": {"thread_id": "limit"}},
        )
    assert model.calls == 1 and result["outcome"] == "STEP_LIMIT"
    assert store.report("limit", "alice")["completion_reason"] == "STEP_LIMIT"


def test_symbol_index_uses_real_definition_and_respects_scope(evidence):
    _, repo, snapshot = evidence
    found = repo.find_symbol("alice", "workspace", snapshot["id"], "add")
    assert found and found[0]["path"] == "sample.py" and "def add" in found[0]["content"]
    assert repo.find_symbol("alice", "workspace", snapshot["id"], "unknown") == []
    with pytest.raises(PermissionError):
        repo.find_symbol("bob", "workspace", snapshot["id"], "add")
