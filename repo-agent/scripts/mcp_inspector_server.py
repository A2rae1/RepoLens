"""Test adapter: keep short-lived app JWT out of the Inspector command line/output."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
p = Path(sys.argv[1]).resolve()
if (
    p.parent != ROOT / "repo-agent/.local"
    or not p.name.startswith("mcp-inspector-auth-")
    or p.suffix != ".json"
):
    raise ValueError("Only own ephemeral probe auth file accepted")
data = json.loads(p.read_text(encoding="utf-8"))
os.environ["MCP_AUTH_TOKEN"] = data["token"]
os.environ["DATA_DIR"] = str(ROOT / "repo-agent/.local")
os.environ["CONTROL_URL"] = "http://127.0.0.1:8094"
sys.path.insert(0, str(ROOT / "repo-agent/src"))
os.chdir(ROOT / "repo-agent")
from repo_agent.mcp_server import create_server  # noqa: E402

create_server().run(transport="stdio")
