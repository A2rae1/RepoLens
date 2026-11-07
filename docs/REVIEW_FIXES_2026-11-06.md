# Reliability fixes after code review

These source changes follow the 2026-11-06 review. They do not represent a new live-model benchmark, a production deployment, or learner ownership validation.

## Booking transactions

Mutation paths lock the session before current reads of requests, orders, tickets, payment receipts and checker authorization. A pre-existing MySQL REPEATABLE READ snapshot must not determine a state transition. Ticket invalidation checks its affected row count. Real MySQL regression covers allocation/cancellation, confirmation/cancellation, check-in/cancellation, promotion of a newer waiter and payment receipt replay.

## Agent approval, recovery and explicit retries

- Flyway V9 adds `generation` and `approval_hash` to Java jobs. Deploy the updated Java service before the updated Python service.
- Lease reclamation preserves the generation/checkpoint. A user retry of FAILED increments generation and selects a new graph thread. Previous checkpoints, cost reservations and executions are retained.
- `AWAITING_APPROVAL` completion includes `approvalHash`. Java resume requires the matching `planHash` and is idempotent for replay of that same decision. The internal resume endpoint requires the existing service key.
- Python records the decision and its pending delivery in one SQLite transaction. The reconciler retries delivery without persisting a user's bearer token. The decision cannot be reversed. A lost finish response leaves the durable graph outcome available for lease recovery.
- `GET /jobs/{id}/approval` returns the current plan, expiry, decision and `approval_nonce`. For a legacy waiting job it can bind the plan from its saved checkpoint without approving it.
- `POST /jobs/{id}/approval/renew` accepts `plan_hash` only for an expired, undecided plan. It generates a new nonce and does not approve anything. A subsequent approval must include that nonce. Expired plans may still be rejected.
- Recorded execution outcomes may be recovered after approval expiry; expiry still forbids a new dispatch. An identical already-decided plan does not create another interrupt. A new retry generation requires a new plan/approval.

The UI uses the authenticated approval API as its current state, rather than guessing from old events. SSE decoding is extracted into `event-stream.js` with bounded buffering and cancellation tests. All local workers must share DATA_DIR: a per-job OS file lock is acquired before claiming work and held through graph cleanup. Cancellation waits for issued checkpoint writes to drain before releasing ownership. Tests cover two live applications, separate OS processes and separate containers sharing the same bind mount, including process death. This is single-host coordination, not cross-host/distributed-filesystem fencing or proof against every network failure.

## Evidence and evaluation

Python symbol ranges come from AST. Java regex results are explicitly declaration candidates, with comment/string filtering; they are never returned in `exact_definitions`. Existing symbol indexes are rebuilt at version2.

Evaluation execution errors are failures in the complete denominator. Unreviewed cases remain pending, with lower/upper bounds instead of an unjustified complete success rate. The subset score is separately named. `summary-v2.json` and `semantic-review-v2.json` include scorer/raw-input hashes and preserve historical summaries and raw cases.

## Verification scope

Initial repair verification includes default Java/Gateway/Python checks, targeted real MySQL transactions, and native Java/MySQL/Python HTTP tests of approval, nonce renewal, replay and explicit retry using offline model fixtures. The subsequent 2026-11-07 closeout rebuilt the Java/Gateway/Python/runner images and exercised the separate-checkout container deployment, real model research/follow-up/export/approved AST validation/cancellation, PostgreSQL restart recovery, S3 multipart ownership/checksums, Docker execution boundaries, real MySQL/Redis/MQ regression and Redis outage behavior. See `FINAL_VERIFICATION_2026-11-07.md` for current counts and limits. A successful AST recipe means syntax validation only, not complete upstream test success. Test-harness approval is not learner ownership evidence.

Optional frontend check: `node --test event-platform/ui-tests/event-stream.test.mjs` from EventFulfill root.

Container images must be rebuilt from this source before use. An old local image does not acquire these fixes automatically. Source publication and image deployment are separate actions. Local images were rebuilt for acceptance; no registry image publication or production deployment is claimed.
