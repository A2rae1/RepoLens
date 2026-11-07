# RepoLens

**开源项目调研与复现 Agent · Evidence-grounded repository research**

Submit a public GitHub repository, a full commit SHA and a question. RepoLens retrieves source evidence, produces cited reports, supports follow-up questions and requests approval before constrained Python verification.

## Independent application

This repository contains everything specific to RepoLens. It does not require EventFulfill, its API, users, database, frontend, secrets or source checkout.

- `repo-control/`: Java17/Spring Boot identity, task ownership, idempotency, lease/generation CAS, transactional Outbox/RocketMQ delivery and the standalone web UI.
- `repo-agent/`: Python3.12/FastAPI/LangGraph worker, retrieval/Skills/MCP, approval, constrained runner, reports and evaluation.
- `infra/`: this application's own MySQL, Redis, RocketMQ, PostgreSQL, optional Elasticsearch and S3-compatible storage; distinct ports/volumes from other projects.

**Stack:** Java17, Spring Boot, MyBatis-Plus, MySQL, Redis, RocketMQ; Python3.12, FastAPI, LangGraph, DeepSeek, PostgreSQL, Elasticsearch, MCP, S3-compatible storage, Docker.

## Verify and run

```powershell
./scripts/init-local.ps1
./scripts/verify.ps1
./scripts/executor-build.ps1
./scripts/apps-build.ps1
./scripts/apps-start.ps1
# http://127.0.0.1:8094/
./scripts/apps-stop.ps1
```

Default checks require JDK17+, Maven, Python3.12, uv and Node, but no model key or live middleware. Use this repository's generated demo credentials from ignored `infra/.env`; Alice/Bob are researchers, operator has the maintenance role. JWT issuer is `repolens`, separate from any other application.

Live calls are disabled in `.env.example`. Put a key only in ignored `repo-agent/.env`, review the cumulative budget, and then opt in. Workers in one deployment must share DATA_DIR and its budget ledger. Never publish credentials, model weights or runtime databases.

See [independent deployment](docs/INTEGRATION.md), [separation notes](docs/PROJECT_INDEPENDENCE_2026-11-07.md), [verification scope](docs/VERIFICATION.md) and [third-party notices](docs/THIRD_PARTY_NOTICES.md).

The execution recipes are constrained checks, not arbitrary repository one-click reproduction or a strong sandbox for arbitrary malicious code. Python symbols use AST; Java results are declaration candidates. The 80-case development evaluation is AI-authored and was not a blind generalization benchmark. Historical results retain their original version and scope.

[Independent-deployment verification](docs/INDEPENDENCE_VERIFICATION_2026-11-07.md) records current tests and remaining boundaries.
