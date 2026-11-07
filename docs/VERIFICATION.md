> Current standalone results: [independent verification](INDEPENDENCE_VERIFICATION_2026-11-07.md).

> Current architecture: [independent applications](PROJECT_INDEPENDENCE_2026-11-07.md). Earlier combined-deployment results below are historical, not proof of the new split.

> Current repair validation: [2026-11-07 closeout](FINAL_VERIFICATION_2026-11-07.md). Earlier results below retain their original version/scope.

# Verification scope

Baseline snapshot: 2026-11-06. Local results describe a development environment, not production capacity or learner proficiency. Raw private runtime databases, credentials, traces and machine-specific logs are intentionally excluded from the public repository.

## Default reproducible checks

`./scripts/verify.ps1` explicitly collects only this workspace's projects: Python Ruff, Python tests, Java service Maven verify and Gateway Maven verify. The final local baseline recorded Python: 21 passed / 10 conditional skips; Java: 23 passed / 21 conditional skips; Gateway: 4 passed. Conditional real-dependency skips remain separate. A newly uploaded GitHub workflow has not succeeded until its remote run actually completes.

## Real integration work exercised locally

- MySQL transaction ordering/MVCC regression, capacity invariants, repeated booking and authorization boundaries.
- Redis Lua admission, WatchDog lease renewal, cache behavior and stopped-Redis failure paths.
- RocketMQ duplicate delivery, real dead letters, audited replay, uncertain send acknowledgement and publishing-lease recovery.
- XXL-JOB expiration, retry and recovery after missed scheduling; cross-aggregate error isolation.
- Real model/API agent tasks, follow-ups, reports, Postgres checkpoint restart, approval/rejection/cancel, and bounded Docker execution.
- Real S3 two-part upload/resume of approximately 5.4 MB, SHA verification and cross-owner denial. The application limit is 12 MB; this is not a multi-GB upload claim.
- Elasticsearch and CPU retrieval comparison, incremental content cache reuse and partial-index-write recovery.
- Local observability, two-instance service discovery and an isolated single-node Gateway Kubernetes lab.

## Evaluation limits

The 80-case Click 8.1.8 fixed-commit set is AI-authored and contract/source grounded, with 64 development and 16 development-holdout cases. The holdout has been inspected during development; it is not blind or independent human evaluation. V6 recorded 55/56 automatic checks and 20/24 AI-reviewed cases; the later six-case bad-case run is separate and must not be spliced into a new aggregate result.

On 40 AI-path-labeled retrieval queries, BM25 Recall@5=.775, hybrid=.6375 and rerank=.75. Hybrid did not beat BM25 in this sample. A fixed Click constrained pytest recipe recorded 628 passed / 21 skipped / 1 expected failure; those are upstream tests, not 628 tests authored for this application.

The local booking probe used 100 synthetic users / 200 submissions at 20 VU, resulting in 20 held / 80 waiting and matching allocation/capacity counters. It is not a throughput ceiling, production scale or end-to-end fulfillment latency measurement. No external user data or live payment channel is involved.


Repository split: Java source is in A2rae1/EventFulfill; Python Agent source is in A2rae1/RepoLens. Historical joint verification is retained as historical evidence; new repository CI is verified separately.
