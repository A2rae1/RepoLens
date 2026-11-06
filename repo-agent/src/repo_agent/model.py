import json
import time
from typing import Protocol

import httpx

from .network import tls_context
from .pricing import check_pricing_fresh
from .settings import Settings
from .store import Store
from .telemetry import model_usage, operation


class Model(Protocol):
    async def complete(self, job: str, messages: list[dict], tools: list[dict]) -> dict: ...


class DeepSeekModel:
    def __init__(self, settings: Settings, store: Store):
        self.settings, self.store = settings, store

    async def complete(
        self, job: str, messages: list[dict], tools: list[dict], *, json_output: bool = False
    ) -> dict:
        with operation(
            "llm.complete",
            **{"gen_ai.system": "deepseek", "gen_ai.request.model": self.settings.deepseek_model},
        ):
            return await self._complete(job, messages, tools, json_output=json_output)

    async def _complete(self, job, messages, tools, *, json_output=False):
        cfg = self.settings
        if not cfg.live_model_enabled or not cfg.deepseek_api_key:
            raise RuntimeError("LIVE_MODEL_NOT_CONFIGURED")
        if cfg.deepseek_model != "deepseek-flash":
            raise ValueError("This budget reservation policy currently supports deepseek-flash only")
        check_pricing_fresh()
        if len(json.dumps(messages, ensure_ascii=False).encode()) > 65000:
            raise ValueError("CONTEXT_BUDGET_EXCEEDED")
        # At most 65k UTF8 bytes of input +4096 output; reserve >=1 CNY per request.
        # Reservations are a conservative spending guard, not actual paid cost or a performance metric.
        call_id = self.store.reserve_call(
            job, cfg.deepseek_model, cfg.reserve_cny_per_call, cfg.model_budget_cny
        )
        start = time.perf_counter()
        async with httpx.AsyncClient(timeout=cfg.request_timeout, verify=tls_context()) as client:
            try:
                response = await client.post(
                    "https://api.deepseek.com/chat/completions",
                    headers={"Authorization": f"Bearer {cfg.deepseek_api_key}"},
                    json={
                        "model": cfg.deepseek_model,
                        "messages": messages,
                        **({"tools": tools} if tools else {}),
                        **({"response_format": {"type": "json_object"}} if json_output else {}),
                        "max_tokens": cfg.max_output_tokens,
                        "temperature": 0,
                        "thinking": {"type": "disabled"},
                    },
                )
            except httpx.ConnectError:
                self.store.call_not_sent(call_id, "CONNECT_FAILED_BEFORE_REQUEST")
                raise
            # No automatic retry: an ambiguous timeout may already have incurred provider charges.
            if response.status_code != 200:
                raise RuntimeError(f"MODEL_HTTP_{response.status_code}")
            result = response.json()
        self.store.call_usage(call_id, result.get("usage", {}), (time.perf_counter() - start) * 1000)
        model_usage(cfg.deepseek_model, result.get("usage", {}), self.store)
        message = result["choices"][0]["message"]
        return {
            key: value
            for key, value in message.items()
            if key in {"role", "content", "tool_calls"} and value is not None
        }
