import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def test_real_stdio_client_server_discovery_call_and_acl(evidence):
    store, _, snapshot = evidence

    class AuthFixture(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/api/me" and self.headers.get("Authorization") == "Bearer fixture-token":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"id": "alice"}).encode())
            else:
                self.send_response(401)
                self.end_headers()

        def log_message(self, *args):
            pass

    auth = ThreadingHTTPServer(("127.0.0.1", 0), AuthFixture)
    thread = threading.Thread(target=auth.serve_forever, daemon=True)
    thread.start()
    env = {
        **os.environ,
        "DATA_DIR": str(store.root),
        "CONTROL_URL": f"http://127.0.0.1:{auth.server_port}",
        "MCP_AUTH_TOKEN": "fixture-token",
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
    }
    try:
        async with stdio_client(
            StdioServerParameters(command=sys.executable, args=["-m", "repo_agent.mcp_server"], env=env)
        ) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = await client.list_tools()
                assert {t.name for t in tools.tools} == {
                    "search_evidence",
                    "read_file_region",
                    "query_report",
                }
                result = await client.call_tool(
                    "search_evidence",
                    {"workspace": "workspace", "snapshot": snapshot["id"], "query": "Python"},
                )
                assert not result.isError
                assert "3.12" in result.content[0].text
                denied = await client.call_tool(
                    "search_evidence",
                    {"workspace": "someone-else", "snapshot": snapshot["id"], "query": "Python"},
                )
                assert denied.isError
    finally:
        auth.shutdown()
        auth.server_close()
