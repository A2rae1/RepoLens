"""Independent task-queue k6 probe; stops only the selected project's worker before enqueueing."""

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def main():
    project = os.environ.get("E2E_COMPOSE_PROJECT", "repolens")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", project):
        raise ValueError("Invalid explicit project name")
    k6 = os.environ.get("K6_EXECUTABLE") or shutil.which("k6")
    if not k6 or not Path(k6).is_file():
        raise RuntimeError("Set K6_EXECUTABLE to your own installed k6 before this optional probe")
    docker = os.environ.get("DOCKER_EXECUTABLE", "docker")
    container = project + "-repo-agent-1"

    def owned_command(*args):
        result = subprocess.run([docker, *args], capture_output=True, timeout=35)
        if result.returncode:
            raise RuntimeError("Own worker lifecycle check failed; credentials/output omitted")
        return result.stdout

    labels = json.loads(owned_command("inspect", container, "--format", "{{json .Config.Labels}}"))
    assert labels["com.docker.compose.project"] == project
    assert labels["com.docker.compose.service"] == "repo-agent"
    origin = os.environ.get("CONTROL_API_URL", "http://127.0.0.1:8094")
    run = "queue-" + uuid.uuid4().hex
    directory = ROOT / ".local/load" / run
    directory.mkdir(parents=True)
    config_root = ROOT / "repolens-infra" if (ROOT / "repolens-infra").exists() else ROOT / "infra"
    settings = dict(
        line.split("=", 1)
        for line in (config_root / ".env").read_text(encoding="utf-8-sig").splitlines()
        if "=" in line and not line.startswith("#")
    )
    with httpx.Client(timeout=15) as client:
        login = client.post(origin + "/api/auth/login", json={"username": "alice", "password": settings["REPOLENS_DEMO_PASSWORD"]})
        login.raise_for_status()
        headers = {"Authorization": "Bearer " + login.json()["accessToken"]}

        def api(method, path, data=None):
            result = client.request(method, origin + path, headers=headers, json=data)
            result.raise_for_status()
            return result.json()

        workspace = api("POST", "/api/agent/workspaces", {"name": run})["id"]
        private = directory / "private-input.json"
        private.write_text(json.dumps({"origin": origin, "workspace": workspace, "token": login.json()["accessToken"], "run": run}), encoding="utf-8")
        owned_command("stop", "--timeout", "20", container)
        completed = None
        try:
            completed = subprocess.run([k6, "run", "--quiet", "--env", "LOAD_INPUT=" + str(private), "--env", "LOAD_OUTPUT=" + str(directory / "k6.json"), str(ROOT / "repo-control/load/agent-queue.js")], capture_output=True, timeout=110)
        finally:
            jobs = [j for j in api("GET", "/api/agent/jobs") if j["workspaceId"] == workspace]
            for job in jobs:
                assert api("POST", "/api/agent/jobs/" + job["id"] + "/cancel", {})["status"] == "CANCELLED"
            private.unlink(missing_ok=True)
            # Never restart a worker before confirming that this probe's queued work is cancelled.
            assert all(j["status"] == "CANCELLED" for j in api("GET", "/api/agent/jobs") if j["workspaceId"] == workspace)
            owned_command("start", container)
        assert completed is not None and completed.returncode == 0, "k6 thresholds failed; raw bounded metrics retained"
        assert len(jobs) == len({j["idemKey"] for j in jobs}) == 40
        result = {"status": "PASS", "distinct_tasks": 40, "all_cancelled_before_worker_restart": True, "model_calls": 0, "scope": "20VU/400POST task enqueue only; independent control API, not Agent completion throughput"}
        (directory / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))


if __name__ == "__main__":
    main()
