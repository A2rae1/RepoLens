import httpx

from .settings import Settings
from .telemetry import headers


class Control:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def internal(self, path: str, data: dict | None = None):
        if len(self.settings.agent_internal_secret) < 32:
            raise RuntimeError("INTERNAL_SERVICE_KEY_NOT_CONFIGURED")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(
                "GET" if data is None else "POST",
                self.settings.control_url + "/internal/agent-jobs" + path,
                headers=headers({"X-Service-Key": self.settings.agent_internal_secret}),
                json=data,
            )
            response.raise_for_status()
            return response.json()

    async def user(self, token: str, path: str, data: dict | None = None):
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(
                "GET" if data is None else "POST",
                self.settings.control_url + path,
                headers=headers({"Authorization": "Bearer " + token}),
                json=data,
            )
            response.raise_for_status()
            return response.json()
