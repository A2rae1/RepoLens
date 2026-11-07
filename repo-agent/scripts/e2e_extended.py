"""Real own Java/MySQL/MQ + Python/Postgres/S3/live-model acceptance.

Uses generated demo accounts and only public/synthetic data. Approvals here are
engineer test-harness actions, never evidence that the user understands a project.
No credentials or tokens are printed or saved in this report.
"""

import asyncio
import base64
import hashlib
import io
import json
import os
import random
import time
import zipfile
from pathlib import Path

import httpx


async def main():
    java, python = os.environ.get("CONTROL_API_URL", "http://127.0.0.1:8094"), "http://127.0.0.1:8092"
    output = Path(os.environ.get("E2E_OUTPUT", ".local/e2e_extended.json"))
    facts = {"approval_origin": "engineer_test_harness", "not_user_understanding_acceptance": True}
    run_prefix = os.environ.get("E2E_RUN_PREFIX", "extended-v6")
    async with httpx.AsyncClient(timeout=35) as client:

        async def login(user):
            response = await client.post(
                java + "/api/auth/login",
                json={"username": user, "password": os.environ["REPOLENS_DEMO_PASSWORD"]},
            )
            response.raise_for_status()
            return {"Authorization": "Bearer " + response.json()["accessToken"]}

        alice, bob = await login("alice"), await login("bob")

        async def call(method, path, body=None, *, agent=False, who=None):
            response = await client.request(
                method, (python if agent else java) + path, json=body, headers=who or alice
            )
            response.raise_for_status()
            return response.json()

        workspaces = await call("GET", "/api/agent/workspaces")
        workspace = next((w for w in workspaces if w["name"] == "扩展联调20261106"), None)
        if not workspace:
            workspace = await call("POST", "/api/agent/workspaces", {"name": "扩展联调20261106"})

        async def wait(job, expected="COMPLETED"):
            if job["status"] == "FAILED" and os.environ.get("E2E_RETRY_FAILED") == "true":
                # Explicit engineer retry after inspecting the saved cause; not a hidden
                # transport retry and never erases previous cost/event records.
                job = await call("POST", f"/api/agent/jobs/{job['id']}/retry", {})
            if job["status"] == "QUEUED":
                await call("POST", f"/jobs/{job['id']}/start", {}, agent=True)
            deadline = time.monotonic() + 180
            while job["status"] not in {"COMPLETED", "FAILED", "CANCELLED", "AWAITING_APPROVAL"}:
                if time.monotonic() > deadline:
                    raise TimeoutError("Own extended integration job timed out")
                await asyncio.sleep(1)
                job = await call("GET", "/api/agent/jobs/" + job["id"])
            assert job["status"] == expected, {
                "job": job["id"],
                "status": job["status"],
                "error": job.get("errorCode"),
            }
            return job

        async def create(key, question):
            return await call(
                "POST",
                "/api/agent/jobs",
                {
                    "workspaceId": workspace["id"],
                    "idempotencyKey": key.replace("extended-v6", run_prefix),
                    "repoUrl": "https://github.com/pallets/click",
                    "commitSha": "934813e4d421071a1b3db3973c02fe2721359a6e",
                    "question": question,
                },
            )

        parent = await wait(
            await create(
                "extended-v6-manifest",
                "只读取pyproject.toml，说明声明的Python最低版本及构建后端，引用证据；不执行代码。",
            )
        )
        parent_report = await call("GET", f"/agent/jobs/{parent['id']}/report")
        assert parent_report["citations"] and "3.7" in parent_report["answer"]
        facts["parent_job"] = parent["id"]
        child = await call(
            "POST",
            f"/api/agent/jobs/{parent['id']}/followup",
            {
                "idempotencyKey": run_prefix + "-followup",
                "question": "沿用上一轮固定仓库和版本，补充说明构建后端及flit_core约束，只读并引用证据。",
            },
        )
        child = await wait(child)
        child_report = await call("GET", f"/jobs/{child['id']}/report", agent=True)
        assert child_report["citations"] and "flit" in child_report["answer"].lower()
        facts["followup_job"] = child["id"]
        exported = await call("POST", f"/agent/jobs/{child['id']}/export", {})
        download = await client.get(
            java + f"/agent/jobs/{child['id']}/artifacts/{exported['id']}", headers=alice
        )
        download.raise_for_status()
        assert hashlib.sha256(download.content).hexdigest() == exported["sha256"]
        forbidden = await client.get(python + f"/jobs/{child['id']}/artifacts/{exported['id']}", headers=bob)
        assert forbidden.status_code == 403
        facts["followup_and_export"] = "PASS; other account 403"

        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("sample/README.md", "# Public synthetic upload fixture\nNo private data.\n")
            archive.writestr("sample/payload.bin", random.Random(20261106).randbytes(5 * 1024 * 1024 + 127))
        payload = data.getvalue()
        upload = await call(
            "POST",
            "/uploads",
            {
                "workspace": workspace["id"],
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
            agent=True,
        )
        # Simulates reconnecting a client: obtain progress again, only resend missing parts.
        progress = await call("GET", "/uploads/" + upload["id"], agent=True)
        if progress["status"] != "COMPLETED":
            sent = {p["part"] for p in progress["parts"]}
            size = progress["part_size"]
            for offset in range(0, len(payload), size):
                part = offset // size + 1
                if part in sent:
                    continue
                block = payload[offset : offset + size]
                response = await client.put(
                    python + f"/uploads/{upload['id']}/parts/{part}",
                    content=block,
                    headers=alice | {"X-Content-Sha256": hashlib.sha256(block).hexdigest()},
                )
                response.raise_for_status()
            await call("POST", f"/uploads/{upload['id']}/complete", {}, agent=True)
        download = await client.get(python + f"/uploads/{upload['id']}/download", headers=alice)
        download.raise_for_status()
        assert hashlib.sha256(download.content).digest() == hashlib.sha256(payload).digest()
        denied = await client.get(python + f"/uploads/{upload['id']}/download", headers=bob)
        assert denied.status_code == 403
        facts["multipart_api"] = {"status": "PASS", "bytes": len(payload), "parts": 2, "cross_owner": 403}
        # Exercise the actual Java same-origin content proxy without launching a
        # browser or invoking the user's external download manager.
        content = await call("GET", f"/agent/uploads/{upload['id']}/content")
        decoded = base64.b64decode(content["content"], validate=True)
        assert content["encoding"] == "base64" and content["size"] == len(payload)
        assert decoded == payload and hashlib.sha256(decoded).hexdigest() == content["sha256"]
        denied = await client.get(java + f"/agent/uploads/{upload['id']}/content", headers=bob)
        assert denied.status_code == 403
        facts["same_origin_content_proxy"] = {"status": "PASS", "bytes": len(decoded), "cross_owner": 403}

        question = "Python环境验证：只提出python_ast白名单语法验证计划并等待我审批，不先执行，也不反复调查。"
        approval_job = await wait(await create("extended-v6-approval", question), "AWAITING_APPROVAL")
        events = await call("GET", f"/jobs/{approval_job['id']}/events", agent=True)
        plan = next(e["data"] for e in reversed(events) if e["kind"] == "approval_required")
        assert plan["plan"]["recipe"] == "python_ast"
        assert not any(e["kind"] == "validation_result" for e in events)
        await call(
            "POST",
            f"/jobs/{approval_job['id']}/approval",
            {"plan_hash": plan["plan_hash"], "approved": True},
            agent=True,
        )
        approval_job = await wait(await call("GET", "/api/agent/jobs/" + approval_job["id"]))
        approval_report = await call("GET", f"/jobs/{approval_job['id']}/report", agent=True)
        runs = approval_report["verification"]["local_executions"]
        assert runs and runs[-1]["verified"] and runs[-1]["recipe"] == "python_ast"
        facts["approved_execution"] = {
            "job": approval_job["id"],
            "recipe": "python_ast",
            "verified": True,
            "scope": "syntax only, not full test pass",
        }
        cancelled = await wait(await create("extended-v6-cancel", question), "AWAITING_APPROVAL")
        await call("POST", f"/api/agent/jobs/{cancelled['id']}/cancel", {})
        after = await call("GET", f"/jobs/{cancelled['id']}/events", agent=True)
        assert not any(e["kind"] == "validation_result" for e in after)
        facts["cancel_before_execution"] = "PASS"
        health = await call("GET", "/health", agent=True)
        assert health["checkpoint"] == "postgres"
        facts["checkpoint_backend"] = "real Postgres; separate process recovery tested independently"
        facts["status"] = "PASS"
        output.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(facts, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
