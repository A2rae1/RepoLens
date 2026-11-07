"""Real approval checkpoint across container restart and running-job cancellation.

Only the owned repo-agent container is restarted. The test harness rejects the
plan after restart; this is not user understanding/approval evidence.
"""

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import httpx


async def main():
    java = "http://127.0.0.1:8090"
    agent = "http://127.0.0.1:8092"
    docker = str(Path(os.environ["LOCALAPPDATA"]) / "Programs/DockerDesktop/resources/bin/docker.exe")
    project = os.environ.get("E2E_COMPOSE_PROJECT", "internship-projects")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", project):
        raise ValueError("Invalid explicit project name")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            java + "/api/auth/login",
            json={"username": "alice", "password": os.environ["EVENT_DEMO_PASSWORD"]},
        )
        response.raise_for_status()
        headers = {"Authorization": "Bearer " + response.json()["accessToken"]}

        async def api(method, path, body=None, python=False):
            r = await client.request(method, (agent if python else java) + path, headers=headers, json=body)
            r.raise_for_status()
            return r.json()

        workspace = await api("POST", "/api/agent/workspaces", {"name": "真实重启恢复验收"})

        async def create(question):
            return await api(
                "POST",
                "/api/agent/jobs",
                {
                    "workspaceId": workspace["id"],
                    "idempotencyKey": str(uuid.uuid4()),
                    "repoUrl": "https://github.com/pallets/click",
                    "commitSha": "934813e4d421071a1b3db3973c02fe2721359a6e",
                    "question": question,
                },
            )

        async def wait(job, status, timeout=70):
            deadline = time.monotonic() + timeout
            while job["status"] != status:
                assert job["status"] not in {"FAILED", "CANCELLED", "COMPLETED"}, job["status"]
                if time.monotonic() > deadline:
                    raise TimeoutError("Checkpoint probe state timeout")
                await asyncio.sleep(0.2)
                job = await api("GET", "/api/agent/jobs/" + job["id"])
            return job

        job = await wait(
            await create("Python环境检查：只提出python_ast白名单验证计划并等待人工审批，不先执行。"),
            "AWAITING_APPROVAL",
        )
        before = await api("GET", f"/jobs/{job['id']}/events", python=True)
        plan = next(e["data"] for e in reversed(before) if e["kind"] == "approval_required")
        assert not any(e["kind"] == "validation_result" for e in before)

        def restart():
            r = subprocess.run(
                [docker, "restart", "--time", "20", project + "-repo-agent-1"],
                capture_output=True,
                timeout=45,
            )
            if r.returncode:
                raise RuntimeError("Own Agent container restart failed")

        await asyncio.to_thread(restart)
        for _ in range(50):
            try:
                health = await client.get(agent + "/health")
                if health.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
        assert (await api("GET", "/api/agent/jobs/" + job["id"]))["status"] == "AWAITING_APPROVAL"
        after = await api("GET", f"/jobs/{job['id']}/events", python=True)
        assert {e["seq"] for e in before} <= {e["seq"] for e in after}
        await api(
            "POST",
            f"/jobs/{job['id']}/approval",
            {"plan_hash": plan["plan_hash"], "approved": False},
            python=True,
        )
        duplicate = await client.post(
            agent + f"/jobs/{job['id']}/approval",
            headers=headers,
            json={"plan_hash": plan["plan_hash"], "approved": False},
        )
        assert duplicate.status_code == 200 and duplicate.json()["accepted"]
        await wait(await api("GET", "/api/agent/jobs/" + job["id"]), "COMPLETED")
        report = await api("GET", f"/jobs/{job['id']}/report", python=True)
        runs = report["verification"]["local_executions"]
        assert runs[-1]["reason"] == "USER_REJECTED" and not runs[-1].get("verified", False)
        running = await wait(
            await create(
                "请分别检索Command、Context、Option、Argument、Group的源码定义和职责，逐个取证并引用，不运行代码。"
            ),
            "RUNNING",
        )
        started = time.monotonic()
        await api("POST", f"/api/agent/jobs/{running['id']}/cancel", {})
        cancelled = False
        for _ in range(40):
            events = await api("GET", f"/jobs/{running['id']}/events", python=True)
            if any(e["kind"] == "attempt_cancelled" for e in events):
                cancelled = True
                break
            await asyncio.sleep(0.25)
        assert cancelled, "Running worker did not observe cancellation within10seconds"
        unavailable = await client.get(agent + f"/jobs/{running['id']}/report", headers=headers)
        assert unavailable.status_code == 404
        result = {
            "status": "PASS",
            "approval_job": job["id"],
            "checkpoint_backend": "real Postgres across container process restart",
            "events_preserved": True,
            "rejected_after_restart": "NOT_RUN/USER_REJECTED",
            "duplicate_approval": "200/idempotent same decision",
            "running_cancel_job": running["id"],
            "cancel_observed_seconds": round(time.monotonic() - started, 3),
            "cancelled_report": 404,
            "scope": "engineer test-harness rejection; cancellation can leave conservative cost reservation for an ambiguous provider request, not claimed free",
        }
        Path(".local/checkpoint_restart_probe.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
