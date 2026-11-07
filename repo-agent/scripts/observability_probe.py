"""Real cross-service trace, failed repo retrieval and authenticated metric/dashboard probe.

The nonexistent public repo fails before any model call. No prompts/auth headers are exported.
"""

import argparse
import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import httpx


def services_and_spans(body):
    resources = body.get("batches", body.get("resourceSpans", []))
    services = set()
    spans = []
    for batch in resources:
        attrs = {
            r["key"]: r["value"].get("stringValue", "")
            for r in batch.get("resource", {}).get("attributes", [])
        }
        if attrs.get("service.name"):
            services.add(attrs["service.name"])
        for scope in batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", [])):
            spans.extend(scope.get("spans", []))
    return services, spans


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    java = "http://127.0.0.1:8094"
    async with httpx.AsyncClient(timeout=15) as client:
        for _ in range(90):
            try:
                response = await client.get(java + "/actuator/health")
                if response.status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
        response = await client.post(
            java + "/api/auth/login",
            json={"username": "alice", "password": os.environ["REPOLENS_DEMO_PASSWORD"]},
        )
        response.raise_for_status()
        headers = {"Authorization": "Bearer " + response.json()["accessToken"]}
        workspace = await client.post(
            java + "/api/agent/workspaces", headers=headers, json={"name": "可观测故障验收"}
        )
        workspace.raise_for_status()
        trace = uuid.uuid4().hex
        context = f"00-{trace}-{uuid.uuid4().hex[:16]}-01"
        job = await client.post(
            java + "/api/agent/jobs",
            headers=headers | {"traceparent": context},
            json={
                "workspaceId": workspace.json()["id"],
                "idempotencyKey": str(uuid.uuid4()),
                "repoUrl": (
                    "https://github.com/pallets/click"
                    if args.live
                    else "https://github.com/pallets/not-a-real-repo-" + uuid.uuid4().hex[:10]
                ),
                "commitSha": ("934813e4d421071a1b3db3973c02fe2721359a6e" if args.live else "a" * 40),
                "question": "这个仓库声明的Python最低版本是什么？请从pyproject.toml取证，不执行代码。",
            },
        )
        job.raise_for_status()
        job = job.json()
        deadline = time.monotonic() + 70
        while job["status"] not in {"COMPLETED", "FAILED", "CANCELLED"} and time.monotonic() < deadline:
            await asyncio.sleep(1)
            response = await client.get(java + "/api/agent/jobs/" + job["id"], headers=headers)
            response.raise_for_status()
            job = response.json()
        if args.live:
            assert job["status"] == "COMPLETED", job["status"]
        else:
            assert job["status"] == "FAILED" and job["errorCode"] == "HTTPStatusError", {
                "status": job["status"],
                "error": job.get("errorCode"),
            }
        services = set()
        spans = []
        for _ in range(25):
            response = await client.get(
                "http://127.0.0.1:13200/api/traces/" + trace, headers={"Accept": "application/json"}
            )
            if response.status_code == 200:
                services, spans = services_and_spans(response.json())
                names = {s["name"] for s in spans}
                if (
                    {"repolens-control", "repo-agent"} <= services
                    and "repo.fetch" in names
                    and "agent.job" in names
                    and "mq.consume" in names
                    and (
                        not args.live
                        or ("llm.complete" in names and any(n.startswith("tool.") for n in names))
                    )
                ):
                    break
            await asyncio.sleep(1)
        assert {"repolens-control", "repo-agent"} <= services, sorted(services)
        failed = [
            s
            for s in spans
            if s["name"] == "repo.fetch" and s.get("status", {}).get("code") in {"STATUS_CODE_ERROR", 2}
        ]
        if not args.live:
            assert failed, [s["name"] for s in spans]
        if args.live:
            assert any(s["name"] == "llm.complete" for s in spans) and any(
                s["name"].startswith("tool.") for s in spans
            )
        assert any(s["name"] == "mq.consume" for s in spans), [s["name"] for s in spans]
        creds = ("metrics", os.environ["METRICS_PASSWORD"])
        for endpoint in [java + "/actuator/prometheus", "http://127.0.0.1:8092/metrics"]:
            denied = await client.get(endpoint)
            assert denied.status_code == 401
            allowed = await client.get(endpoint, auth=creds)
            allowed.raise_for_status()
        forbidden = await client.get(java + "/api/sessions", auth=creds)
        assert forbidden.status_code == 401
        for _ in range(20):
            targets = await client.get("http://127.0.0.1:19090/api/v1/targets")
            targets.raise_for_status()
            active = targets.json()["data"]["activeTargets"]
            if len(active) == 2 and all(t["health"] == "up" for t in active):
                break
            await asyncio.sleep(1)
        assert len(active) == 2 and all(t["health"] == "up" for t in active), [
            {k: t.get(k) for k in ["health", "lastError"]} for t in active
        ]
        dashboard = await client.get(
            "http://127.0.0.1:13000/api/dashboards/uid/internship-projects",
            auth=("admin", os.environ["GRAFANA_ADMIN_PASSWORD"]),
        )
        dashboard.raise_for_status()
        result = {
            "status": "PASS",
            "trace_id": trace,
            "services": sorted(services),
            "span_count": len(spans),
            "fault_span": "repo.fetch",
            "fault_type": "HTTPStatusError",
            "prometheus_targets": 2,
            "metrics_auth": "401 without credential; scraper cannot enter business API",
            "grafana_dashboard": dashboard.json()["dashboard"]["uid"],
            "model_calls_for_fault": 0,
            "scope": "one controlled nonexistent public repo; local trace system, not production observability experience",
        }
        if args.live:
            result.update(
                {
                    "scope": "one real public repo and live model trace",
                    "fault_span": None,
                    "fault_type": None,
                    "model_calls_for_fault": None,
                    "llm_spans": sum(s["name"] == "llm.complete" for s in spans),
                }
            )
        result["span_names"] = sorted({s["name"] for s in spans})
        Path(
            ".local/observability_live_probe.json" if args.live else ".local/observability_probe.json"
        ).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result))


if __name__ == "__main__":
    asyncio.run(main())
