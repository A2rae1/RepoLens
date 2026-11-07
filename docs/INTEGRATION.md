# Independent deployment

EventFulfill and RepoLens are separate applications. Each checkout supplies its own source, build, secrets, identity, frontend, database configuration and lifecycle scripts. No sibling checkout is required.

| Application | Web/API | Worker | MySQL | Redis | MQ nameserver | Postgres | S3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| EventFulfill |8090|—|13406|16379|19876|—|—|
| RepoLens |8094|8092|13407|16380|19877|15433|19010/19011|

RepoLens Elasticsearch is optional on19210. Bindings are localhost only. Do not start every optional group on a small machine merely because ports differ.

In each repository run `scripts/init-local.ps1`, then `scripts/verify.ps1` and `scripts/apps-build.ps1`. RepoLens additionally requires `scripts/executor-build.ps1`. Start/stop each independently using `scripts/apps-start.ps1` / `scripts/apps-stop.ps1`.

Both accept an explicit `-ProjectName` (defaults `eventfulfill` or `repolens`). Keep the same name for stop. Volumes are retained. Startup waits for application health. RepoLens `integration.ps1` is now an alias for its own complete stack; it has no EventFulfillRoot parameter. `agent-e2e.ps1` likewise uses RepoLens credentials and8094.

RepoLens native mode: start its own middleware, run `scripts/control-start.ps1`, then `scripts/agent-start.ps1 -Postgres` in separate terminals. MySQL/Redis/MQ are this repository's own services. The control service's default local adapter is durable HTTP delivery, explicitly different from the RocketMQ container profile.

The Agent image may reuse an immutable local runtime only when uv.lock and pyproject.toml hashes exactly match; old source is removed before replacement. `-RefreshDependencies` forces the pinned clean dependency build; `-ClassicBuilder` selects the classic builder. Neither disables checksum verification.

All workers in a RepoLens deployment must share DATA_DIR, including metadata, budget and per-job OS locks. This is single-host coordination, not a cross-host/distributed-filesystem lock. A clean second checkout must use its own generated credentials and data; old combined-version databases remain preserved rather than silently copied or reset.
