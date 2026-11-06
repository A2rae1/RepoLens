"""Real Java control-plane queue load, worker stopped and all created jobs cancelled: no LLM calls."""

import asyncio
import json
import os
import time
import uuid

import httpx
from jobs_init import DOCKER, ROOT, sql


async def main():
    settings = dict(
        line.split("=", 1)
        for line in (ROOT / "infra/.env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    )
    proc = await asyncio.create_subprocess_exec(
        str(DOCKER),
        "ps",
        "-q",
        "--filter",
        "name=^internship-projects-repo-agent-1$",
        stdout=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    assert not out.strip(), "Own worker must be stopped for this queue-only experiment"
    run = "agent-load-" + uuid.uuid4().hex[:12]
    directory = ROOT / ".local/agent-load" / run
    directory.mkdir(parents=True)
    ledger_before = None
    import sqlite3

    with sqlite3.connect(ROOT / "repo-agent/.local/artifacts.sqlite3") as db:
        ledger_before = db.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0]
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            "http://127.0.0.1:8090/api/auth/login",
            json={"username": "organizer", "password": settings["EVENT_DEMO_PASSWORD"]},
        )
        r.raise_for_status()
        token = r.json()["accessToken"]
        headers = {"Authorization": "Bearer " + token}
        r = await client.post(
            "http://127.0.0.1:8090/api/agent/workspaces", headers=headers, json={"name": run}
        )
        r.raise_for_status()
        workspace = r.json()["id"]
        private = directory / "private-input.json"
        private.write_text(
            json.dumps(
                {"token": token, "run": run, "workspace": workspace, "origin": "http://127.0.0.1:8090"}
            ),
            encoding="utf-8",
        )
        output = directory / "summary.json"
        env = os.environ | {
            "LOAD_INPUT": str(private),
            "LOAD_OUTPUT": str(output),
            "K6_NO_USAGE_REPORT": "true",
        }
        k6 = next((ROOT / ".local/tools/k6").rglob("k6.exe"))
        stop = asyncio.Event()
        samples = []

        async def sample():
            while not stop.is_set():
                p = await asyncio.create_subprocess_exec(
                    str(DOCKER),
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{json .}}",
                    "internship-projects-event-app-1",
                    "internship-projects-mysql-1",
                    "internship-projects-broker-1",
                    "internship-projects-redis-1",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                raw, _ = await p.communicate()
                for line in raw.decode().splitlines():
                    samples.append({"time_monotonic": round(time.monotonic(), 3), **json.loads(line)})
                await asyncio.sleep(0.5)

        sampler = asyncio.create_task(sample())
        try:
            with (directory / "k6.log").open("wb") as log:
                process = await asyncio.create_subprocess_exec(
                    str(k6),
                    "run",
                    "--no-usage-report",
                    str(ROOT / "event-platform/load/agent-queue.js"),
                    env=env,
                    stdout=log,
                    stderr=log,
                )
                assert await process.wait() == 0
        finally:
            stop.set()
            await sampler
        persisted = await sql(
            f"SELECT COUNT(*) FROM eventfulfill_docker.agent_job WHERE workspace_id='{workspace}';"
        )
        assert persisted == "40", persisted
        jobs = await sql(f"SELECT id FROM eventfulfill_docker.agent_job WHERE workspace_id='{workspace}';")
        for job in jobs.splitlines():
            r = await client.post("http://127.0.0.1:8090/api/agent/jobs/" + job + "/cancel", headers=headers)
            r.raise_for_status()
            assert r.json()["status"] == "CANCELLED"
        with sqlite3.connect(ROOT / "repo-agent/.local/artifacts.sqlite3") as db:
            ledger_after = db.execute("SELECT COUNT(*) FROM model_calls").fetchone()[0]
        assert ledger_before == ledger_after
        metrics = json.loads(output.read_text(encoding="utf-8"))["metrics"]
        result = {
            "status": "PASS",
            "run": run,
            "vus": 20,
            "iterations": 200,
            "http_attempts": 400,
            "unique_keys_persisted": 40,
            "all_fixture_jobs_cancelled": True,
            "model_calls_added": 0,
            "checks": metrics["checks"]["values"],
            "http_error_rate": metrics["http_req_failed"]["values"]["rate"],
            "idempotency_conflicts": metrics.get("idempotency_conflicts", {})
            .get("values", {})
            .get("count", 0),
            "duration_ms": metrics["http_req_duration"]["values"],
            "sampled_resources": samples,
            "limits": "Queue/idempotency/cancel control plane only; Python worker deliberately stopped, does not measure Agent completion throughput or capacity ceiling. Docker stats are coarse samples, not a proven resource peak; conflicts are expected concurrent idempotency outcomes.",
        }
        (ROOT / "repo-agent/.local/agent_load_probe.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(json.dumps({k: v for k, v in result.items() if k != "sampled_resources"}))


if __name__ == "__main__":
    asyncio.run(main())
