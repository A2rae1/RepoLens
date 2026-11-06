"""Bounded telemetry: no prompts, tool arguments, source bodies or auth headers exported."""

from contextlib import contextmanager

from opentelemetry import propagate, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import Counter, Gauge, Histogram

HTTP = Counter("repo_agent_http_requests_total", "Observed HTTP responses", ["method", "route", "status"])
LATENCY = Histogram(
    "repo_agent_http_headers_seconds",
    "Response-header latency; not full SSE duration",
    ["route"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 5, 30, 120),
)
TOOLS = Counter("repo_agent_tool_calls_total", "Tool attempts, including failures", ["name", "result"])
JOBS = Counter("repo_agent_job_attempts_total", "Attempt completion responses observed", ["status"])
TOKENS = Counter("repo_agent_model_tokens_total", "Provider-reported tokens", ["model", "direction"])
COST = Gauge(
    "repo_agent_model_conservative_cny", "Cumulative conservative budget accounting, not actual invoice"
)


def configure(endpoint: str):
    if not endpoint:
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    provider = TracerProvider(
        resource=Resource.create({"service.name": "repo-agent", "service.version": "0.1.0"})
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces", timeout=3),
            max_queue_size=256,
            max_export_batch_size=64,
            schedule_delay_millis=500,
        )
    )
    trace.set_tracer_provider(provider)
    return provider


@contextmanager
def operation(name: str, *, parent=None, kind=SpanKind.INTERNAL, **attributes):
    with trace.get_tracer("repo-agent").start_as_current_span(
        name, context=parent, kind=kind, record_exception=False, set_status_on_exception=False
    ) as span:
        for key, value in attributes.items():
            span.set_attribute(key, str(value)[:300])
        try:
            yield span
        except BaseException as error:
            span.set_status(Status(StatusCode.ERROR))
            span.set_attribute("error.type", type(error).__name__)
            raise


def headers(base=None):
    result = dict(base or {})
    propagate.inject(result)
    return result


def model_usage(model, usage, store):
    for key, direction in [("prompt_tokens", "input"), ("completion_tokens", "output")]:
        count = usage.get(key)
        if isinstance(count, int) and count >= 0:
            TOKENS.labels(model, direction).inc(count)
    try:
        with store.connect() as db:
            COST.set(db.execute("SELECT COALESCE(SUM(reserved_cny),0) FROM model_calls").fetchone()[0])
    except Exception:
        COST.set(float("nan"))  # Metrics failure must not repeat an already billed request.
