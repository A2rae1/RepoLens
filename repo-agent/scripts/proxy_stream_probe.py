"""Replay/ownership acceptance for the real same-origin SSE adapter; no model calls."""

import asyncio
import json
import os
from pathlib import Path

import httpx


async def main():
    java = os.environ.get("CONTROL_API_URL", "http://127.0.0.1:8094")
    summary = json.loads(Path(".local/e2e_extended.json").read_text(encoding="utf-8"))
    job = summary["followup_job"]
    async with httpx.AsyncClient(timeout=15) as client:

        async def login(user):
            response = await client.post(
                java + "/api/auth/login",
                json={"username": user, "password": os.environ["REPOLENS_DEMO_PASSWORD"]},
            )
            response.raise_for_status()
            return {"Authorization": "Bearer " + response.json()["accessToken"]}

        alice, bob = await login("alice"), await login("bob")
        events = await client.get(java + f"/agent/jobs/{job}/events", headers=alice)
        events.raise_for_status()
        ids = [e["seq"] for e in events.json()]
        cursor = ids[-3] if len(ids) > 2 else 0
        received = []
        async with client.stream(
            "GET", java + f"/agent/jobs/{job}/stream", headers=alice | {"Last-Event-ID": str(cursor)}
        ) as response:
            response.raise_for_status()
            assert response.headers["content-type"].startswith("text/event-stream")
            async for line in response.aiter_lines():
                if line.startswith("id:"):
                    received.append(int(line[3:]))
                    if len(received) == 2:
                        break
        assert received == [seq for seq in ids if seq > cursor][:2]
        async with client.stream("GET", java + f"/agent/jobs/{job}/stream", headers=bob) as response:
            assert response.status_code == 403
        memory = await client.get(java + "/agent/memory", headers=alice)
        memory.raise_for_status()
        result = {
            "status": "PASS",
            "event_replay": "exact ordered IDs after Last-Event-ID",
            "received": received,
            "other_owner": 403,
            "memory_proxy": "PASS",
            "model_calls": 0,
        }
        Path(".local/proxy_stream_probe.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
