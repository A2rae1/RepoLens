# Review repair closeout — 2026-11-07

The R1–R6 repairs and single-host worker ownership guards were exercised after rebuilding the Java application, Gateway, Python application and constrained runner. No registry image publication or production deployment is claimed.

| Check | Result and boundary |
|---|---|
| Default Java checks | 25 passed, 26 dependency-conditional skips; Gateway 4 passed. Skips are not integration passes. |
| Default Python checks | 39 passed, 10 dependency-conditional skips; Ruff passed. |
| Frontend event stream | 3 Node tests passed: chunk handling, cancellation and buffering. |
| Separate real Java tests | 24 passed: MySQL 17, Redis 4, RocketMQ recovery 3. Independent test schemas; legacy learning database untouched. |
| Separate real Python dependency tests | 9 passed: constrained Docker execution 6, S3-compatible storage 2, PostgreSQL checkpoint 1. |
| Separate search test | 1 passed with real Elasticsearch and cached multilingual CPU ONNX embeddings, without a paid embedding API. Three synthetic two-file snapshots; not a general retrieval quality benchmark. |
| Two-checkout cold start | Separate EventFulfill and RepoLens Compose definitions, fresh project volumes, Flyway V9, both health endpoints ready. |
| Booking HTTP lifecycle | Real MySQL/Redis/MQ acceptance, waiting, cancellation, promotion, confirmation, ticket and explicitly granted checker; ownership denial and duplicate check-in conflict verified. Payment remains simulated. |
| Redis outage | Cached display falls back to the database; booking admission returns 503 without inserting a request; owned Redis container restored. |
| Live Agent HTTP | Fresh real-model research and follow-up, cited report export, two-part 5.24 MB S3 upload/resume/checksum/ownership, same-origin content proxy, approved Docker AST recipe and cancellation before execution passed. AST success is syntax-only, not full upstream test success. |
| Restart and approval | Real PostgreSQL across Agent container restart; events retained, rejection gives NOT_RUN, duplicate same decision returns idempotent 200; running cancellation observed within the probe limit and no cancelled report published. |
| Writer ownership | Two live application instances plus OS process and cross-container shared-bind tests: a live old writer blocks the successor, process death releases the lock, cancellation drains issued checkpoint writes before ownership release. |
| Image content | Installed Python source and both Java JARs exactly match the checked-out build artifacts; runner approval uses the rebuilt immutable image ID. |

All local workers must share DATA_DIR, including the SQLite metadata and lock files. These tests establish the single-host/shared-bind boundary only. They do not establish cross-host coordination or distributed-filesystem lock safety. Java completion CAS alone is not claimed to fence every Python side effect.

The Python image was rebuilt from an existing immutable local runtime only after its `uv.lock` and `pyproject.toml` hashes matched this checkout. The original clean pinned dependency build remains available. In this environment BuildKit bootstrap stalled, and a separate fresh package download failed a checksum; neither checksum nor transport verification was disabled. The successful source rebuild does not establish clean-network dependency availability.

The test harness supplied approvals/rejections for synthetic tasks. This does not establish learner understanding, real-user approval or unrestricted untrusted-code safety. The 80-case development evaluation was not rerun: historical corrected scoring remains attached to its original version, AI-authored dataset and AI review. No new success-rate, latency, throughput or production-scale claim is inferred from these smoke tests.

Optional governance, observability, scheduler and K8s historical experiments were not all repeated in this repair closeout. Their original scope and evidence remain available; default CI does not exercise paid models or real middleware.

Acceptance containers are stopped after testing and volumes retained. The original Windows learning MySQL service/data are not moved, reset or stopped.
