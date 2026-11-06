import asyncio
import base64
import json
import secrets
import time
from contextlib import AsyncExitStack, asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from opentelemetry import propagate
from opentelemetry.trace import SpanKind
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from . import telemetry
from .checkpoints import postgres_saver
from .context import parent_summary
from .control import Control
from .executor import Executor
from .graph import build_graph
from .model import DeepSeekModel
from .objects import Objects
from .repository import Repository
from .retrieval import Embeddings, HybridSearch, Reranker
from .settings import Settings
from .store import Store
from .tools import Tools
from .uploads import uploads_router


def create_app(settings: Settings | None = None, model=None) -> FastAPI:
    cfg = settings or Settings()
    cfg.prepare()
    store = Store(cfg.data_dir)
    control = Control(cfg)
    repository = Repository(store)
    executor = Executor(cfg, store)
    active: dict[str, asyncio.Task] = {}
    semaphore = asyncio.Semaphore(2)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            provider = telemetry.configure(cfg.otlp_endpoint)
            if provider:
                stack.callback(provider.shutdown)
            telemetry.model_usage(cfg.deepseek_model, {}, store)
            app.state.objects = None
            if cfg.object_enabled:
                object_store = Objects(cfg, store)
                await asyncio.to_thread(object_store.setup)
                app.state.objects = object_store
                stack.callback(object_store.s3.close)
            hybrid, reranker = None, None
            if cfg.search_backend == "hybrid":
                embeddings = await asyncio.to_thread(Embeddings, cfg)
                hybrid = HybridSearch(cfg, store, embeddings)
                await hybrid.setup()
                stack.push_async_callback(hybrid.close)
                if cfg.rerank_enabled:
                    reranker = await asyncio.to_thread(Reranker, cfg)
            elif cfg.search_backend != "fts":
                raise ValueError("Unknown search backend")
            app.state.hybrid = hybrid
            if cfg.checkpoint_url:
                saver = await stack.enter_async_context(postgres_saver(cfg.checkpoint_url))
            else:
                saver = await stack.enter_async_context(
                    AsyncSqliteSaver.from_conn_string(str(cfg.data_dir / "checkpoints.sqlite3"))
                )
            app.state.graph = build_graph(
                model or DeepSeekModel(cfg, store),
                Tools(store, repository, executor, hybrid, reranker),
                store,
                saver,
                cfg.max_steps,
            )
            recovery = asyncio.create_task(recover())
            try:
                yield
            finally:
                recovery.cancel()
                for task in active.values():
                    task.cancel()
                await asyncio.gather(recovery, *active.values(), return_exceptions=True)

    app = FastAPI(title="RepoLens 仓库调研与复现Agent", version="0.1.0", lifespan=lifespan)
    app.state.store, app.state.repository, app.state.control = store, repository, control

    @app.middleware("http")
    async def trace_http(request: Request, call_next):
        started = time.perf_counter()
        with telemetry.operation(
            "HTTP " + request.method, parent=propagate.extract(request.headers), kind=SpanKind.SERVER
        ) as span:
            response = await call_next(request)
            route = getattr(request.scope.get("route"), "path", "unmatched")
            span.update_name(request.method + " " + route)
            span.set_attribute("http.route", route)
            span.set_attribute("http.response.status_code", response.status_code)
            telemetry.HTTP.labels(request.method, route, str(response.status_code)).inc()
            telemetry.LATENCY.labels(route).observe(time.perf_counter() - started)
            if span.get_span_context().is_valid:
                response.headers["X-Trace-Id"] = format(span.get_span_context().trace_id, "032x")
            return response

    @app.get("/metrics")
    async def metrics(authorization: str = Header(default="")):
        try:
            user, password = (
                base64.b64decode(authorization.removeprefix("Basic "), validate=True).decode().split(":", 1)
            )
        except (ValueError, UnicodeError):
            user, password = "", ""
        if (
            user != "metrics"
            or len(cfg.metrics_password) < 32
            or not secrets.compare_digest(password, cfg.metrics_password)
        ):
            raise HTTPException(
                401, "指标接口需要专用凭证", headers={"WWW-Authenticate": 'Basic realm="metrics"'}
            )
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    async def auth(authorization: str = Header(default="")):
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "请先登录")
        token = authorization.removeprefix("Bearer ")
        try:
            user = await control.user(token, "/api/me")
        except httpx.HTTPError:
            raise HTTPException(401, "凭证失效或鉴权服务不可用") from None
        return user["id"], token

    async def job_owner(job: str, principal: tuple):
        try:
            return await control.user(principal[1], "/api/agent/jobs/" + job)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, "无此任务访问权限") from None

    async def heartbeat(job: str, token: str, worker: asyncio.Task):
        while True:
            await asyncio.sleep(20)
            try:
                await control.internal(f"/{job}/heartbeat", {"token": token})
            except httpx.HTTPError:
                worker.cancel()
                return

    async def perform_attempt(job_id: str):
        async with semaphore:
            try:
                job = await control.internal(f"/{job_id}/claim", {})
            except httpx.HTTPStatusError:
                return  # Durable Java CAS chooses one execution attempt across workers.
            token = job["leaseToken"]
            keeper = asyncio.create_task(heartbeat(job_id, token, asyncio.current_task()))
            config = {"configurable": {"thread_id": job_id}, "recursion_limit": 80}
            try:
                state = await app.state.graph.aget_state(config)
                if state.next:
                    graph_input = Command(resume={"resume": True}) if state.interrupts else None
                elif state.values.get("answer"):
                    # Outcome committed to checkpoint but Java response was lost: publish the stored result only.
                    graph_input = None
                else:
                    snapshot = await repository.fetch(
                        job["ownerId"], job["workspaceId"], job["repoUrl"], job["commitSha"]
                    )
                    if app.state.hybrid:
                        await app.state.hybrid.index_snapshot(
                            job["ownerId"], job["workspaceId"], snapshot["id"]
                        )
                    graph_input = {
                        "job": job_id,
                        "owner": job["ownerId"],
                        "workspace": job["workspaceId"],
                        "snapshot": snapshot["id"],
                        "question": job["question"],
                    }
                    linkage = await control.internal(f"/{job_id}/parent")
                    if linkage.get("parentJobId"):
                        parent = await control.internal("/" + linkage["parentJobId"])
                        previous = store.report(parent["id"], job["ownerId"])
                        if (
                            parent["ownerId"] != job["ownerId"]
                            or parent["workspaceId"] != job["workspaceId"]
                            or parent["commitSha"] != job["commitSha"]
                        ):
                            raise PermissionError("Parent context scope mismatch")
                        if previous:
                            graph_input["prior_context"] = parent_summary(parent["question"], previous)
                            evidence = {}
                            for citation in previous["citations"][:12]:
                                for chunk in repository.read(
                                    job["ownerId"],
                                    job["workspaceId"],
                                    snapshot["id"],
                                    citation["path"],
                                    citation["start_line"],
                                    min(citation["end_line"], citation["start_line"] + 170),
                                ):
                                    evidence[chunk["id"]] = chunk
                            graph_input["evidence"] = evidence
                    store.event(
                        job_id,
                        "snapshot_ready",
                        {"snapshot": snapshot["id"], "commit": snapshot["commit_sha"]},
                    )
                result = await app.state.graph.ainvoke(graph_input, config)
                status = (
                    "AWAITING_APPROVAL"
                    if result.get("__interrupt__")
                    else ("FAILED" if result.get("outcome") == "STEP_LIMIT" else "COMPLETED")
                )
                if status == "COMPLETED" and app.state.objects:
                    try:
                        await asyncio.to_thread(
                            app.state.objects.artifact,
                            job["ownerId"],
                            job["workspaceId"],
                            job_id,
                            "report",
                            store.report(job_id, job["ownerId"]),
                        )
                    except Exception as archive_error:
                        # Report checkpoint is already durable. Object-store outage must not
                        # turn completed research into failed work or repeat paid calls.
                        store.event(job_id, "archive_pending", {"error": type(archive_error).__name__})
                await control.internal(
                    f"/{job_id}/finish",
                    {
                        "token": token,
                        "status": status,
                        "resultRef": f"/jobs/{job_id}/report",
                        "errorCode": "STEP_LIMIT" if status == "FAILED" else None,
                    },
                )
                store.event(job_id, "job_status", {"status": status})
                telemetry.JOBS.labels(status).inc()
                return status
            except asyncio.CancelledError:
                store.event(job_id, "attempt_cancelled", {"attempt": job["attempt"]})
                raise
            except Exception as exc:
                store.event(
                    job_id,
                    "attempt_failed",
                    {"error": type(exc).__name__, "detail": str(exc).splitlines()[0][:150]},
                )
                try:
                    await control.internal(
                        f"/{job_id}/finish",
                        {"token": token, "status": "FAILED", "errorCode": type(exc).__name__},
                    )
                    telemetry.JOBS.labels("FAILED").inc()
                    return "FAILED"
                except httpx.HTTPError:
                    pass
            finally:
                keeper.cancel()
                await asyncio.gather(keeper, return_exceptions=True)

    async def perform(job_id: str):
        try:
            context = await control.internal(f"/{job_id}/trace")
        except httpx.HTTPError:
            context = {}
        parent = propagate.extract({"traceparent": context.get("traceParent", "")})
        with telemetry.operation("agent.job", parent=parent, **{"job.id": job_id}) as span:
            status = await perform_attempt(job_id)
            span.set_attribute("job.status", status or "NOT_CLAIMED_OR_FENCED")
            if status == "FAILED":
                from opentelemetry.trace import Status, StatusCode

                span.set_status(Status(StatusCode.ERROR))

    def wake(job: str):
        if job not in active or active[job].done():
            if sum(not task.done() for task in active.values()) >= 20:
                return (
                    False  # Durable QUEUED state is retried by polling/MQ; do not accumulate unbounded tasks.
                )
            task = asyncio.create_task(perform(job))
            active[job] = task

            def finished(completed):
                if active.get(job) is completed:
                    active.pop(job, None)
                if not completed.cancelled():
                    completed.exception()  # Observe errors without dumping credentials/headers.

            task.add_done_callback(finished)
        return True

    async def recover():
        while True:
            try:
                for job in await control.internal(""):
                    wake(job["id"])
            except (httpx.HTTPError, RuntimeError):
                pass
            await asyncio.sleep(10)

    @app.get("/health")
    async def health():
        return {
            "status": "up",
            "live_model_configured": cfg.live_model_enabled and bool(cfg.deepseek_api_key),
            "checkpoint": "postgres" if cfg.checkpoint_url else "sqlite",
            "active_tasks": sum(not t.done() for t in active.values()),
        }

    @app.post("/internal/jobs/{job}/wake")
    async def wake_internal(job: str, x_service_key: str = Header(default="")):
        if len(cfg.agent_internal_secret) < 32 or not secrets.compare_digest(
            x_service_key, cfg.agent_internal_secret
        ):
            raise HTTPException(401, "内部凭证无效")
        if not wake(job):
            raise HTTPException(503, "任务执行队列已满，已持久化的任务将稍后重试")
        return {"accepted": True}

    @app.post("/internal/jobs/{job}/cancel")
    async def cancel_internal(job: str, x_service_key: str = Header(default="")):
        if len(cfg.agent_internal_secret) < 32 or not secrets.compare_digest(
            x_service_key, cfg.agent_internal_secret
        ):
            raise HTTPException(401, "内部凭证无效")
        owned = await control.internal("/" + job)
        if owned["status"] != "CANCELLED":
            raise HTTPException(409, "业务控制面未取消此任务")
        task = active.get(job)
        if task and not task.done():
            task.cancel()
        return {"cancelled": True}

    @app.post("/jobs/{job}/start")
    async def start(job: str, principal=Depends(auth)):
        owned = await job_owner(job, principal)
        if owned["status"] not in {"QUEUED", "RUNNING"}:
            raise HTTPException(409, "此任务当前状态不能启动")
        if not wake(job):
            raise HTTPException(429, "任务执行队列已满，请稍后重试")
        return {"accepted": True}

    @app.get("/jobs/{job}/report")
    async def report(job: str, principal=Depends(auth)):
        owned = await job_owner(job, principal)
        if owned["status"] != "COMPLETED":
            raise HTTPException(404, "报告尚未就绪")
        result = store.report(job, principal[0])
        if not result:
            raise HTTPException(404, "报告尚未就绪")
        return result

    @app.get("/jobs/{job}/events")
    async def events(job: str, after: int = 0, principal=Depends(auth)):
        await job_owner(job, principal)
        return store.events(job, after)

    @app.post("/jobs/{job}/export")
    async def export_report(job: str, principal=Depends(auth)):
        owned = await job_owner(job, principal)
        if owned["status"] != "COMPLETED" or not app.state.objects:
            raise HTTPException(409, "任务尚未完成或对象存储未启用")
        body = store.report(job, principal[0])
        if not body:
            raise HTTPException(404, "报告不存在")
        return await asyncio.to_thread(
            app.state.objects.artifact, principal[0], owned["workspaceId"], job, "report", body
        )

    @app.get("/jobs/{job}/artifacts/{identifier}")
    async def artifact(job: str, identifier: str, principal=Depends(auth)):
        await job_owner(job, principal)
        if not app.state.objects:
            raise HTTPException(503, "对象存储未启用")
        try:
            payload = await asyncio.to_thread(app.state.objects.read_artifact, principal[0], job, identifier)
        except PermissionError:
            raise HTTPException(403, "无此产物访问权限") from None
        return Response(
            payload,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="research-report.json"'},
        )

    @app.get("/jobs/{job}/stream")
    async def stream(
        job: str, after: int = 0, last_event_id: str | None = Header(default=None), principal=Depends(auth)
    ):
        await job_owner(job, principal)
        try:
            cursor = max(0, after, int(last_event_id or 0))
        except ValueError:
            raise HTTPException(400, "Last-Event-ID必须为整数") from None

        async def generate():
            nonlocal cursor
            for tick in range(120):
                # Recheck ownership/auth periodically; SSE events are durable and replayable by sequence.
                if tick % 10 == 0:
                    await job_owner(job, principal)
                for event in store.events(job, cursor):
                    cursor = event["seq"]
                    yield f"id: {cursor}\nevent: {event['kind']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    class Decision(BaseModel):
        plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
        approved: bool

    @app.post("/jobs/{job}/approval")
    async def approve(job: str, body: Decision, principal=Depends(auth)):
        owned = await job_owner(job, principal)
        if owned["status"] != "AWAITING_APPROVAL":
            raise HTTPException(409, "任务未等待审批")
        try:
            store.decide(job, body.plan_hash, body.approved)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        await control.user(principal[1], f"/api/agent/jobs/{job}/resume", {})
        wake(job)
        return {"accepted": True}

    class Memory(BaseModel):
        key: str = Field(min_length=1, max_length=80)
        value: str | None = Field(default=None, max_length=1000)
        confirmed: bool

    @app.get("/memory")
    async def memory(principal=Depends(auth)):
        return store.preferences(principal[0])

    @app.put("/memory")
    async def save_memory(body: Memory, principal=Depends(auth)):
        if not body.confirmed:
            raise HTTPException(400, "请明确确认保存或删除偏好")
        store.preference(principal[0], body.key, body.value, confirmed=True)
        return {"saved": True}

    app.include_router(uploads_router(app, control, auth))
    return app
