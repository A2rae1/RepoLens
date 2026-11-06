"""Reconcile already-reported token usage using the verified CNY peak-price upper bound."""

import json

from repo_agent.pricing import check_pricing_fresh
from repo_agent.settings import Settings
from repo_agent.store import Store

check_pricing_fresh()
store = Store(Settings().data_dir)
with store.connect() as db:
    rows = db.execute("SELECT * FROM model_calls WHERE status='REPORTED' AND reserved_cny>=1").fetchall()
for row in rows:
    store.call_usage(
        row["id"],
        {
            "prompt_tokens": row["input_tokens"],
            "completion_tokens": row["output_tokens"],
            "prompt_cache_hit_tokens": row["cached_tokens"] or 0,
        },
        row["latency_ms"] or 0,
    )
with store.connect() as db:
    result = dict(
        db.execute(
            "SELECT COUNT(*) AS calls,SUM(reserved_cny) AS conservative_total_cny FROM model_calls"
        ).fetchone()
    )
print(json.dumps(result))
