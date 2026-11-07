import asyncio

import httpx

from repo_agent.app import create_app
from repo_agent.lifecycle import graph_config
from repo_agent.settings import Settings


async def run_until_idle(app, client, predicate):
    response = await client.post("/jobs/job/start", headers={"Authorization": "Bearer alice"})
    assert response.status_code == 200
    for _ in range(200):
        await asyncio.sleep(0.01)
        if predicate() and (await client.get("/health")).json()["active_tasks"] == 0:
            return
    raise AssertionError("Fixture worker did not reach the expected state")


async def test_step_limit_retry_uses_new_generation_but_finish_outage_reuses_result(evidence, tmp_path):
    store, _, snapshot = evidence

    class Model:
        calls = 0
        loop = True

        async def complete(self, job, messages, tools):
            self.calls += 1
            if self.loop:
                return {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "one",
                            "type": "function",
                            "function": {"name": "search_evidence", "arguments": '{"query":"Python"}'},
                        }
                    ],
                }
            return {"role": "assistant", "content": "Fixture answer; no claim of verified execution."}

    model = Model()
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, max_steps=1), model=model)
    job = {
        "id": "job",
        "ownerId": "alice",
        "workspaceId": "workspace",
        "repoUrl": snapshot["repo"],
        "commitSha": snapshot["commit_sha"],
        "question": "Python version",
        "status": "QUEUED",
        "attempt": 0,
        "generation": 0,
        "leaseToken": "fixture",
        "approvalHash": None,
    }
    lose_finish = False

    async def user(token, path, data=None):
        return {"id": "alice"} if path == "/api/me" else dict(job)

    async def internal(path, data=None):
        nonlocal lose_finish
        if path == "":
            return []  # Explicit starts keep the test deterministic.
        if path.endswith("/trace"):
            return {}
        if path.endswith("/parent"):
            return {"parentJobId": ""}
        if path.endswith("/claim"):
            job["status"] = "RUNNING"
            job["attempt"] += 1
        elif path.endswith("/finish"):
            if lose_finish:
                raise httpx.ConnectError("Injected failure before finish delivery")
            job["status"] = data["status"]
            job["approvalHash"] = data.get("approvalHash")
        return dict(job)

    app.state.control.user = user
    app.state.control.internal = internal

    async def fetch(*args):
        return snapshot

    app.state.repository.fetch = fetch
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        ) as client:
            await run_until_idle(app, client, lambda: job["status"] == "FAILED")
            assert model.calls == 1 and store.report("job", "alice")["completion_reason"] == "STEP_LIMIT"
            first_config = graph_config(job)
            # Models Java's tested FAILED -> QUEUED + generation increment.
            job.update(status="QUEUED", generation=1)
            model.loop = False
            lose_finish = True
            await run_until_idle(app, client, lambda: bool(store.report("job", "alice")))
            assert job["status"] == "RUNNING" and model.calls == 2
            assert (await app.state.graph.aget_state(first_config)).values["outcome"] == "STEP_LIMIT"
            assert any(e["kind"] == "finish_pending" for e in store.events("job"))
            # Models a lease reclaim, preserving generation; no second model call.
            job["status"] = "QUEUED"
            lose_finish = False
            await run_until_idle(app, client, lambda: job["status"] == "COMPLETED")
            assert model.calls == 2 and store.report("job", "alice")["completion_reason"] == "ANSWER"
