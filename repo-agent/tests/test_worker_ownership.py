import asyncio

import httpx

from repo_agent.app import create_app
from repo_agent.settings import Settings


async def test_successor_cannot_claim_or_overwrite_while_old_graph_is_still_live(evidence, tmp_path):
    store, _, snapshot = evidence
    started, release = asyncio.Event(), asyncio.Event()

    class OldModel:
        calls = 0

        async def complete(self, *args):
            self.calls += 1
            started.set()
            await release.wait()
            return {"role": "assistant", "content": "Stored original generation result"}

    class NewModel:
        calls = 0

        async def complete(self, *args):
            self.calls += 1
            raise AssertionError("Recovery must publish the durable result, not start another graph")

    old_model, new_model = OldModel(), NewModel()
    cfg = Settings(_env_file=None, data_dir=tmp_path)
    old, new = create_app(cfg, old_model), create_app(cfg, new_model)
    row = {
        "id": "job",
        "ownerId": "alice",
        "workspaceId": "workspace",
        "status": "QUEUED",
        "repoUrl": snapshot["repo"],
        "commitSha": snapshot["commit_sha"],
        "question": "Python",
        "generation": 0,
        "attempt": 0,
        "leaseToken": "",
        "approvalHash": None,
    }
    expired = False

    async def user(token, path, data=None):
        return {"id": "alice"} if path == "/api/me" else dict(row)

    async def internal(path, data=None):
        if path == "":
            return []
        if path.endswith("/trace"):
            return {}
        if path.endswith("/parent"):
            return {"parentJobId": ""}
        if path.endswith("/claim"):
            row["attempt"] += 1
            row.update(status="RUNNING", leaseToken=str(row["attempt"]))
        if path.endswith("/finish"):
            if expired and data["token"] == "1":
                request = httpx.Request("POST", "http://fixture/finish")
                raise httpx.HTTPStatusError(
                    "expired token", request=request, response=httpx.Response(409, request=request)
                )
            row["status"] = data["status"]
        return dict(row)

    async def fetch(*args):
        return snapshot

    for app in [old, new]:
        app.state.control.user = user
        app.state.control.internal = internal
        app.state.repository.fetch = fetch

    async with old.router.lifespan_context(old), new.router.lifespan_context(new):
        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=old), base_url="http://old") as a,
            httpx.AsyncClient(transport=httpx.ASGITransport(app=new), base_url="http://new") as b,
        ):
            headers = {"Authorization": "Bearer alice"}
            await a.post("/jobs/job/start", headers=headers)
            await asyncio.wait_for(started.wait(), 2)
            expired = True  # Control plane would permit a new lease; old graph is still alive.
            await b.post("/jobs/job/start", headers=headers)
            for _ in range(100):
                await asyncio.sleep(0.01)
                if (await b.get("/health")).json()["active_tasks"] == 0:
                    break
            assert row["attempt"] == 1 and new_model.calls == 0
            release.set()
            for _ in range(100):
                await asyncio.sleep(0.01)
                if (await a.get("/health")).json()["active_tasks"] == 0:
                    break
            assert any(e["kind"] == "finish_pending" for e in store.events("job"))
            await b.post("/jobs/job/start", headers=headers)
            for _ in range(100):
                await asyncio.sleep(0.01)
                if row["status"] == "COMPLETED":
                    break
            assert row["attempt"] == 2 and row["status"] == "COMPLETED"
            assert old_model.calls == 1 and new_model.calls == 0
            assert store.report("job", "alice")["answer"] == "Stored original generation result"
