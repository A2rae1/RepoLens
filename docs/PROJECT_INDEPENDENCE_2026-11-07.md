# Project separation — 2026-11-07

The earlier packaging put RepoLens identity/task control and its UI in the EventFulfill Java application. That reduced duplicate initial setup but created an unnecessary runtime dependency between unrelated products.

RepoLens now owns an independent `repo-control` Java service (`cn.hm.repolens`), Flyway schema, JWT issuer/signing secret, users, transactional task Outbox/MQ, local worker service key and UI on8094. The Python worker defaults to that control service. Its own MySQL/Redis/MQ/S3/Postgres resources use separate names, ports and volumes. The approval/nonce, explicit retry generation, lease fencing and checkpoint ownership contracts are preserved.

EventFulfill no longer serves Agent APIs, proxy endpoints, task classes or an Agent tab, and does not send events to an Agent. Its Gateway routes only booking traffic; the dynamic admission switch now protects new booking requests. Historical Flyway V2/V4/V7/V9 migrations are retained unchanged to preserve existing database checksums/data. Their obsolete tables do not constitute a runtime dependency and are not automatically dropped.

Existing combined-version evidence and evaluations are historical. Independence verification must demonstrate booking with the Agent/control services absent, then RepoLens with the booking API and database stopped, including login ownership, jobs, approval, follow-up, export and recovery. Test-harness approvals do not establish learner understanding. Optional historical governance/observability/K8s experiments are not automatically reclassified as new independent-deployment results.
