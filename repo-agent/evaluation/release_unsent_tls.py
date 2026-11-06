"""One-time ledger reconciliation using preserved ConnectError case results; never release ambiguous timeouts."""

import json
from pathlib import Path

from repo_agent.settings import Settings
from repo_agent.store import Store

store = Store(Settings().data_dir)
released = 0
for path in Path(".local/evaluation-v1").glob("case-*.json"):
    case = json.loads(path.read_text(encoding="utf-8"))
    if case.get("error") != "ConnectError" or "CERTIFICATE_VERIFY_FAILED" not in case.get("detail", ""):
        continue
    job = "eval-v1-" + case["id"]
    with store.connect() as db:
        rows = db.execute("SELECT id FROM model_calls WHERE job=? AND status='RESERVED'", (job,)).fetchall()
    if len(rows) == 1:
        store.call_not_sent(rows[0]["id"], "RECONCILED_FROM_SAVED_TLS_CONNECT_ERROR_BEFORE_HTTP_REQUEST")
        released += 1
print(
    json.dumps({"released_unsent_tls_reservations": released, "original_case_results": "preserved unchanged"})
)
