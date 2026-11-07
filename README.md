# RepoLens

**开源项目调研与复现 Agent · Evidence-grounded repository research**

A Python Agent service that investigates a fixed GitHub commit, retrieves source evidence, requests approval for constrained checks, and produces traceable reports.

**Stack:** Python3.12, FastAPI, LangGraph, DeepSeek, Elasticsearch, MCP, PostgreSQL, S3-compatible storage, Docker.

## Capabilities

- Version-pinned snapshots, source citations, BM25/vector/hybrid retrieval comparisons and content/model cache reuse.
- Persistent checkpoints, leases, cancellation, generation-separated retries and Java completion fencing; approval binds the plan, recipe, image identity and expiry.
- Non-root, read-only, network-disabled execution recipes with resource/output limits; this is not a strong sandbox for arbitrary malicious code.
- Scoped Skills, MCP tools, isolated context, resumable S3 uploads, reports and an 80-case development evaluation set with documented limitations.

## Layout and default checks

`repo-agent/` contains Python source, tests, evaluation, trusted runner and Agent probes. `infra/` contains optional Postgres/search/S3 services; `scripts/` provides Agent-only checks and two-checkout integration.

```powershell
./scripts/verify.ps1
./scripts/init-local.ps1
```

Default verification requires Python3.12 and uv; it does not require Java, a live model key or running middleware. Live model calls are disabled by default. Add your own key to ignored `repo-agent/.env` and review the budget before enabling them. Never commit credentials, runtime databases, model weights or logs.

## Run the Agent and full workflow

The Python API can start independently and exposes its health endpoint on 8092. Full authenticated research jobs, approvals, ownership and the demo UI use the Java task-control API hosted by the separate [EventFulfill](https://github.com/A2rae1/EventFulfill) repository. This HTTP dependency is retained explicitly; the Java project is not duplicated here.

```powershell
# Clone EventFulfill as a sibling and initialize/start its Java backend first.
./scripts/agent-start.ps1 -EventFulfillRoot ../EventFulfill
# http://127.0.0.1:8092/health
```

For container integration, build each repository's images and the runner, then use `./scripts/integration.ps1 -EventFulfillRoot ../EventFulfill`. See [integration setup](docs/INTEGRATION.md). Default retrieval is FTS; Elasticsearch/CPU embeddings are optional. Real model acceptance costs money and is separate from default CI.

The evaluation set is AI-authored development material, not blind human evaluation. Simulated/local measurements do not imply production scale or universal repository reproduction. See [verification scope](docs/VERIFICATION.md) and [third-party notices](docs/THIRD_PARTY_NOTICES.md).

## Review fixes

See [reliability fixes](docs/REVIEW_FIXES_2026-11-06.md) for current-read transactions, durable approval delivery, generation-separated retries, evidence precision and versioned evaluation metrics. Rebuild old container images before using this source. See [2026-11-07 verification](docs/FINAL_VERIFICATION_2026-11-07.md) for the rebuilt two-checkout acceptance and remaining boundaries.
