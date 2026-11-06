"""MCP SDK v1.x stdio adapter. Every call authenticates via the Java control plane."""

import os

from mcp.server.fastmcp import FastMCP

from .control import Control
from .repository import Repository
from .settings import Settings
from .store import Store


def create_server() -> FastMCP:
    cfg = Settings()
    cfg.prepare()
    store = Store(cfg.data_dir)
    repo = Repository(store)
    control = Control(cfg)
    server = FastMCP(
        "RepoLens", instructions="只读固定版本证据和报告。不会授予执行权限。", log_level="WARNING"
    )

    async def owner() -> str:
        token = os.environ.get("MCP_AUTH_TOKEN", "")
        if not token:
            raise PermissionError("MCP_AUTH_TOKEN is required")
        user = await control.user(token, "/api/me")
        return user["id"]

    @server.tool()
    async def search_evidence(workspace: str, snapshot: str, query: str, k: int = 5) -> list[dict]:
        """Search authorized repository evidence; return paths, source lines and stable chunk IDs."""
        return repo.search(await owner(), workspace, snapshot, query, k)

    @server.tool()
    async def read_file_region(
        workspace: str, snapshot: str, path: str, start: int = 1, end: int = 80
    ) -> list[dict]:
        """Read a bounded region from an authorized snapshot; never a host filesystem path."""
        return repo.read(await owner(), workspace, snapshot, path, start, end)

    @server.tool()
    async def query_report(job: str) -> dict:
        """Return a report only for the authenticated owner."""
        result = store.report(job, await owner())
        if result is None:
            raise PermissionError("Report absent or forbidden")
        return result

    return server


if __name__ == "__main__":
    create_server().run(transport="stdio")
