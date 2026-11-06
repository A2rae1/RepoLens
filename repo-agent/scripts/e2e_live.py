"""Real local Java/MySQL control plane -> Python/LangGraph -> DeepSeek -> cited report.

The wrapper supplies this project's demo password as an environment variable.
Never print credentials, tokens, or HTTP headers.
"""

import asyncio
import json
import os
import time

import httpx


async def main():
    java, agent = "http://127.0.0.1:8090", "http://127.0.0.1:8092"
    async with httpx.AsyncClient(timeout=15) as client:
        login = await client.post(
            java + "/api/auth/login",
            json={"username": "alice", "password": os.environ["EVENT_DEMO_PASSWORD"]},
        )
        login.raise_for_status()
        headers = {"Authorization": "Bearer " + login.json()["accessToken"]}

        async def api(method, path, body=None, *, python=False):
            response = await client.request(
                method, (agent if python else java) + path, headers=headers, json=body
            )
            response.raise_for_status()
            return response.json()

        workspaces = await api("GET", "/api/agent/workspaces")
        workspace = next((w for w in workspaces if w["name"] == "联调验证"), None)
        if workspace is None:
            workspace = await api("POST", "/api/agent/workspaces", {"name": "联调验证"})
        job = await api(
            "POST",
            "/api/agent/jobs",
            {
                "workspaceId": workspace["id"],
                "idempotencyKey": "e2e-click-python-version-v1",
                "repoUrl": "https://github.com/pallets/click",
                "commitSha": "934813e4d421071a1b3db3973c02fe2721359a6e",
                "question": "请检查这个固定版本pyproject.toml声明的Python最低版本及构建后端，并引用源文件证据。只读调研，不执行代码。",
            },
        )
        if job["status"] == "FAILED":
            raise RuntimeError("Previous task failed: inspect its saved events before explicitly retrying")
        if job["status"] == "QUEUED":
            await api("POST", f"/jobs/{job['id']}/start", {}, python=True)
        deadline = time.monotonic() + 180
        while job["status"] not in {"COMPLETED", "FAILED", "CANCELLED", "AWAITING_APPROVAL"}:
            if time.monotonic() > deadline:
                raise TimeoutError("Task did not reach a terminal state within the bounded check")
            await asyncio.sleep(2)
            job = await api("GET", f"/api/agent/jobs/{job['id']}")
        if job["status"] != "COMPLETED":
            raise RuntimeError("Task ended in " + job["status"])
        report = await api("GET", f"/jobs/{job['id']}/report", python=True)
        events = await api("GET", f"/jobs/{job['id']}/events", python=True)
        assert report["citations"] and "3.7" in report["answer"] and "flit" in report["answer"].lower()
        # Verify horizontal isolation with a separately authenticated account.
        other = await client.post(
            java + "/api/auth/login", json={"username": "bob", "password": os.environ["EVENT_DEMO_PASSWORD"]}
        )
        other.raise_for_status()
        forbidden = await client.get(
            agent + f"/jobs/{job['id']}/report",
            headers={"Authorization": "Bearer " + other.json()["accessToken"]},
        )
        assert forbidden.status_code == 403
        summary = {
            "status": "PASS",
            "job": job["id"],
            "attempt": job["attempt"],
            "citations": len(report["citations"]),
            "model_steps": report["steps"],
            "events": len(events),
            "other_user_report_status": forbidden.status_code,
            "dependencies": "real Java/MySQL/Redis/RocketMQ/Python/LangGraph/DeepSeek; SQLite checkpoint",
        }
        from pathlib import Path

        Path(".local/e2e_live.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
