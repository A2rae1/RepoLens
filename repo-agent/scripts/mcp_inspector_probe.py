"""Second independent MCP client, real Java authentication and fixed public source."""

import asyncio
import json
import shutil
import sys
import uuid
from pathlib import Path

import httpx

from repo_agent.repository import Repository
from repo_agent.store import Store

ROOT = Path(__file__).resolve().parents[2]


async def main():
    settings = dict(
        line.split("=", 1)
        for line in (ROOT / "repolens-infra/.env" if (ROOT / "repolens-infra/.env").exists() else ROOT / "infra/.env").read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    )
    async with httpx.AsyncClient(timeout=8) as client:
        for _ in range(60):
            try:
                r = await client.get("http://127.0.0.1:8094/actuator/health")
                if r.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.5)
        login = await client.post(
            "http://127.0.0.1:8094/api/auth/login",
            json={"username": "alice", "password": settings["REPOLENS_DEMO_PASSWORD"]},
        )
        login.raise_for_status()
        token = login.json()["accessToken"]
    store = Store(ROOT / "repo-agent/.local")
    snapshot = await Repository(store).fetch(
        "alice", "inspector-probe", "https://github.com/pallets/click",
        "934813e4d421071a1b3db3973c02fe2721359a6e",
    )
    private = ROOT / "repo-agent/.local" / ("mcp-inspector-auth-" + uuid.uuid4().hex + ".json")
    private.write_text(json.dumps({"token": token}), encoding="utf-8")
    cli = ROOT / ".local/mcp-inspector/node_modules/@modelcontextprotocol/inspector/cli/build/cli.js"

    async def call(method, args=()):
        command = [
            shutil.which("node"),
            str(cli),
            "--cli",
            sys.executable,
            str(ROOT / "repo-agent/scripts/mcp_inspector_server.py"),
            str(private),
            "--method",
            method,
            *args,
        ]
        p = await asyncio.create_subprocess_exec(
            *command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=ROOT / "repo-agent"
        )
        try:
            out, err = await asyncio.wait_for(p.communicate(), 35)
        except BaseException:
            p.kill()
            await p.wait()
            raise
        text = out.decode("utf-8", errors="replace")
        if token in text or token.encode() in err:
            raise RuntimeError("Unexpected auth echo; output suppressed")
        return p.returncode, text

    try:
        code, listing = await call("tools/list")
        assert code == 0 and all(
            name in listing for name in ["search_evidence", "read_file_region", "query_report"]
        )
        arguments = (
            "--tool-name",
            "search_evidence",
            "--tool-arg",
            "workspace=inspector-probe",
            "--tool-arg",
            "snapshot=" + snapshot["id"],
            "--tool-arg",
            "query=Python",
        )
        code, answer = await call("tools/call", arguments)
        assert code == 0 and "pyproject.toml" in answer
        denied = list(arguments)
        denied[3] = "workspace=someone-else"
        denied_code, body = await call("tools/call", tuple(denied))
        assert denied_code != 0 or "isError" in body and "true" in body.lower()
        result = {
            "status": "PASS",
            "client": "Official Inspector1.0.4 CLI, security-fixes-only v1 line; installed Node24.15 does not meet current v2.14 floor",
            "tools_discovered": 3,
            "real_java_auth": True,
            "public_source": snapshot["repo"],
            "commit": snapshot["commit_sha"],
            "owner_search": True,
            "other_workspace_denied": True,
            "temporary_auth_file_removed_on_exit": True,
            "scope": "Independent Node MCP CLI versus Python SDK client regression. No web UI, no model call, no secret in command line or output.",
        }
        (ROOT / "repo-agent/.local/mcp_inspector_probe.json").write_text(
            json.dumps(result, indent=2), encoding="utf-8"
        )
        print(json.dumps(result))
    finally:
        private.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
