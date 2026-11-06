"""Conservative CNY settlement bound, not a provider invoice.

Official DeepSeek Flash peak CNY prices verified 2026-11-05:
https://api-docs.deepseek.com/zh-cn/quick_start/pricing/
Per million: cache-hit .04, input-miss 2, output 8 CNY. Add 20% and round upward.
"""

import math
from datetime import UTC, datetime, timedelta

REVIEWED = datetime(2026, 11, 5, tzinfo=UTC)
SOURCE = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"


def check_pricing_fresh():
    if datetime.now(UTC) > REVIEWED + timedelta(days=7):
        raise RuntimeError("PRICING_SNAPSHOT_EXPIRED_REVERIFY_OFFICIAL_CNY_RATES")


def cny_upper(usage: dict) -> float | None:
    prompt, output = usage.get("prompt_tokens"), usage.get("completion_tokens")
    hit = usage.get("prompt_cache_hit_tokens", 0)
    if not all(isinstance(n, int) and n >= 0 for n in [prompt, output, hit]) or hit > prompt:
        return None
    amount = ((prompt - hit) * 2 + hit * 0.04 + output * 8) / 1_000_000
    return max(0.01, math.ceil((amount * 1.2 + 0.000001) * 100) / 100)
