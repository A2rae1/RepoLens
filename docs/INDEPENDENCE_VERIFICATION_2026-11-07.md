# Independent application verification — 2026-11-07

This replaces the previous requirement to run EventFulfill for RepoLens. Historical combined-version measurements retain their original scope.

| Scope | Actual local result |
|---|---|
| EventFulfill clean default build | 47 tests:21 passed,26 real-dependency conditional skips; Gateway4 passed |
| RepoLens default checks | Python39 passed/10 conditional skips; Java control7 passed; SSE Node3 passed; Ruff passed |
| Identity boundary | Independent credentials/issuer; a correctly test-signed event-fulfill issuer is rejected by RepoLens; booking Agent endpoint404 and no Agent page |
| EventFulfill alone | Own MySQL/Redis/MQ and Java; accept/wait/cancel/promote/confirm/ticket/explicit checker/check-in/duplicate conflict pass while RepoLens is stopped |
| RepoLens alone | Event API8090 and DB13406 stopped; own Java/MySQL/Redis/MQ, Python/Postgres/S3; fresh real-model research/follow-up/cited report/export, multipart checksum/resume/owner isolation, approved Docker AST and cancellation pass |
| Recovery | Own Agent process restarted; Postgres/events retained, reject=NOT_RUN, repeated same rejection200 idempotent, RUNNING cancellation observed and cancelled report404 |
| UI | Headless browser login/list/report/citations displayed; final static JS matches source; own favicon200 |
| Independent task queue | Real k6:20VU/400POST,40 distinct idempotency keys; all tasks cancelled before the owned worker restarts,0 model calls. Enqueue behavior only, not completion throughput |
| Final artifact boundary | Clean JAR no longer contains booking Agent classes/static stream module; independent control JAR has its own task API. Both installed JARs and Python source hashes match final build artifacts |

Optional task-queue load uses `repo-agent/scripts/agent_load_probe.py` and `repo-control/load/agent-queue.js`. It requires an explicitly installed K6_EXECUTABLE, validates its own Compose worker label, stops only that worker, enqueues synthetic work and cancels it before restoring the worker. Do not use this maintenance probe against real users; it is not part of default CI and is not a model throughput benchmark.

No new80-case quality evaluation, production load, cross-host locking or arbitrary untrusted-code security claim is made. AST success means syntax checking only. Other historical optional governance/observability/scheduler/K8s results were not all repeated for this split. Existing old combined-version database tables and data are retained, not reset or silently imported.

Local images were rebuilt; no container registry or production deployment is claimed. Dependency reuse still requires matching uv.lock/pyproject.toml hashes and never bypasses package checksum verification. Local model acceptance uses the original cumulative budget ledger, not a reset per checkout. Test-harness approvals are not learner ownership evidence.
