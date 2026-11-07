import asyncio
import json
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from repo_agent.app import create_app
from repo_agent.executor import Executor
from repo_agent.lifecycle import ApprovalRecovery, graph_config
from repo_agent.settings import Settings
from repo_agent.store import Store
from repo_agent.tools import Tools


class ControlFixture:
    def __init__(self, plan_hash):
        self.job = {"id": "job", "status": "AWAITING_APPROVAL", "approvalHash": plan_hash}
        self.offline = False
        self.lose_response = False
        self.resumes = 0

    async def user(self, token, path, data=None):
        if token != "alice":
            response = httpx.Response(403, request=httpx.Request("GET", "http://fixture"))
            raise httpx.HTTPStatusError("outside owner", request=response.request, response=response)
        return {"id": "alice"} if path == "/api/me" else dict(self.job)

    async def internal(self, path, data=None):
        if path.endswith("/resume"):
            if self.offline:
                raise httpx.ConnectError("injected offline control")
            if self.job["status"] == "AWAITING_APPROVAL":
                self.job["status"] = "QUEUED"
                self.resumes += 1
            if self.lose_response:
                self.lose_response = False
                raise httpx.ReadTimeout("injected lost committed response")
        elif path.endswith("/claim"):
            response = httpx.Response(409, request=httpx.Request("POST", "http://fixture"))
            raise httpx.HTTPStatusError(
                "fixture not running worker", request=response.request, response=response
            )
        elif path.endswith("/trace"):
            return {}
        return dict(self.job)


def attach_control(app, fixture):
    app.state.control.user = fixture.user
    app.state.control.internal = fixture.internal


async def post(app, path, body, token="alice"):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        return await client.post(path, json=body, headers={"Authorization": "Bearer " + token})


async def test_approval_survives_offline_control_and_process_restart(tmp_path):
    cfg = Settings(_env_file=None, data_dir=tmp_path)
    app = create_app(cfg)
    key = app.state.store.propose("job", {"recipe": "fixture"})
    control = ControlFixture(key)
    control.offline = True
    attach_control(app, control)
    first = await post(app, "/jobs/job/approval", {"plan_hash": key, "approved": True})
    assert first.status_code == 200 and first.json()["resume_pending"]
    assert app.state.store.approvals.pending()
    second = await post(app, "/jobs/job/approval", {"plan_hash": key, "approved": True})
    assert second.status_code == 200
    # Reopen storage/application and deliver without retaining a user JWT.
    restored = create_app(cfg)
    attach_control(restored, control)
    control.offline = False
    await restored.state.approval_recovery.reconcile()
    await restored.state.approval_recovery.reconcile()
    assert control.resumes == 1 and control.job["status"] == "QUEUED"
    assert restored.state.store.approvals.pending() == []
    changed = await post(restored, "/jobs/job/approval", {"plan_hash": key, "approved": False})
    assert changed.status_code == 409


async def test_lost_resume_response_and_concurrent_duplicate_decisions(tmp_path):
    store = Store(tmp_path)
    key = store.propose("job", {"recipe": "fixture"})
    fixture = ControlFixture(key)
    recovery = ApprovalRecovery(store, fixture)
    store.decide("job", key, True, deliver=True)
    fixture.lose_response = True
    assert not await recovery.deliver("job", key)
    assert fixture.resumes == 1 and store.approvals.pending()
    await asyncio.gather(recovery.reconcile(), recovery.reconcile())
    assert fixture.resumes == 1 and not store.approvals.pending()


async def test_renewal_requires_new_confirmation_nonce_and_expired_rejection_works(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path))
    store = app.state.store
    key = store.propose("job", {"recipe": "fixture"})
    control = ControlFixture(key)
    control.offline = True
    attach_control(app, control)
    with store.connect() as db:
        db.execute("UPDATE approvals SET expires=?", (time.time() - 1,))
    body = {"plan_hash": key, "approved": True}
    assert (await post(app, "/jobs/job/approval", body)).status_code == 409
    renewed = await post(app, "/jobs/job/approval/renew", {"plan_hash": key})
    assert renewed.status_code == 200
    nonce = renewed.json()["approval_nonce"]
    assert nonce and store.approval("job", key)["decision"] is None
    assert (await post(app, "/jobs/job/approval", body)).status_code == 409
    assert (await post(app, "/jobs/job/approval", body | {"approval_nonce": nonce})).status_code == 200
    # A recorded approval may not be extended by renewing it.
    assert (await post(app, "/jobs/job/approval/renew", {"plan_hash": key})).status_code == 409
    reject_key = store.propose("reject-job", {"recipe": "other"})
    with store.connect() as db:
        db.execute("UPDATE approvals SET expires=? WHERE job='reject-job'", (time.time() - 1,))
    store.decide("reject-job", reject_key, False)
    assert store.approval("reject-job", reject_key)["decision"] == "REJECTED"


async def test_owner_and_active_plan_are_checked_before_recording_decision(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path))
    key = app.state.store.propose("job", {"recipe": "current"})
    old = app.state.store.propose("job", {"recipe": "orphan"})
    control = ControlFixture(key)
    attach_control(app, control)
    assert (
        await post(app, "/jobs/job/approval", {"plan_hash": key, "approved": True}, "bob")
    ).status_code in {401, 403}
    assert (await post(app, "/jobs/job/approval", {"plan_hash": old, "approved": True})).status_code == 409
    assert app.state.store.approval("job", old)["decision"] is None
    control.job["status"] = "CANCELLED"
    assert (await post(app, "/jobs/job/approval", {"plan_hash": key, "approved": True})).status_code == 409


def test_existing_approval_schema_migrates_without_changing_decisions(tmp_path):
    path = tmp_path / "artifacts.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE approvals(job TEXT,plan_hash TEXT,plan TEXT,expires REAL,decision TEXT,claimed INTEGER DEFAULT 0,PRIMARY KEY(job,plan_hash))"
        )
        db.execute("INSERT INTO approvals VALUES('legacy','hash','{}',?,'REJECTED',0)", (time.time(),))
    store = Store(tmp_path)
    assert store.approval("legacy", "hash")["decision"] == "REJECTED"
    assert store.approval("legacy", "hash")["nonce"] == ""


def test_generation_separates_explicit_retry_from_lease_recovery(tmp_path):
    job = {"id": "job", "generation": 0, "attempt": 1}
    assert graph_config(job) == graph_config(job | {"attempt": 2})
    assert graph_config(job) != graph_config(job | {"generation": 1})
    executor = Executor(Settings(_env_file=None, data_dir=tmp_path), Store(tmp_path))
    first = executor.plan("job", "snapshot", "python_ast")
    retried = executor.plan("job", "snapshot", "python_ast", 1)
    assert first != retried and retried["generation"] == 1


async def test_legacy_waiting_job_binds_checkpoint_without_granting_authority(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path))
    key = app.state.store.propose("job", {"recipe": "legacy"})
    control = ControlFixture(None)
    original = control.internal

    async def internal(path, data=None):
        if path.endswith("/bind-approval"):
            control.job["approvalHash"] = data["planHash"]
        return await original(path, data)

    control.internal = internal
    attach_control(app, control)
    app.state.graph = SimpleNamespace(
        aget_state=AsyncMock(
            return_value=SimpleNamespace(values={"pending_approval": key}, interrupts=("fixture",))
        )
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
        response = await client.get("/jobs/job/approval", headers={"Authorization": "Bearer alice"})
    assert response.status_code == 200 and response.json()["plan_hash"] == key
    assert control.job["status"] == "AWAITING_APPROVAL" and control.resumes == 0
    assert app.state.store.approval("job", key)["decision"] is None


async def test_expiry_blocks_dispatch_but_preserves_recorded_outcome(evidence, tmp_path):
    store, _, snapshot = evidence
    (tmp_path / "runner-image.json").write_text(
        json.dumps({"tag": "repolens-runner:py312-v1", "id": "sha256:" + "a" * 64})
    )
    executor = Executor(Settings(_env_file=None, data_dir=tmp_path, executor_enabled=True), store)
    key = store.propose("job", executor.plan("job", snapshot["id"], "python_ast"))
    store.decide("job", key, True)
    with store.connect() as db:
        db.execute(
            "INSERT INTO executions VALUES(?,?,'COMPLETED',?)",
            ("job", key, json.dumps({"verified": False, "status": "COMPLETED"})),
        )
        db.execute("UPDATE approvals SET expires=?", (time.time() - 1,))
    result = await executor.run("alice", "workspace", "job", key)
    assert result["reused"] and not result["verified"]
    other = store.propose("other-job", executor.plan("other-job", snapshot["id"], "python_ast"))
    store.decide("other-job", other, True)
    with store.connect() as db:
        db.execute("UPDATE approvals SET expires=?", (time.time() - 1,))
    with pytest.raises(PermissionError, match="expired"):
        await executor.run("alice", "workspace", "other-job", other)


async def test_reproposing_a_decided_plan_does_not_create_an_unresolvable_interrupt(evidence, tmp_path):
    store, repo, snapshot = evidence
    tool = Tools(store, repo, Executor(Settings(_env_file=None, data_dir=tmp_path), store))
    context = {"job": "job", "owner": "alice", "workspace": "workspace", "snapshot": snapshot["id"]}
    raw = '{"recipe":"python_ast","reason":"fixture"}'
    first = await tool.call(context, "propose_validation", raw)
    store.decide("job", first["plan_hash"], False)
    repeated = await tool.call(context, "propose_validation", raw)
    assert repeated["status"] == "ALREADY_DECIDED" and not repeated["approval_required"]
    assert repeated["decision"] == "REJECTED"
