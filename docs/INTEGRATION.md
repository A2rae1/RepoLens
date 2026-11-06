# Two-repository integration

The two repositories have separate source trees, tests and CI. The existing Java identity/task control plane lives in EventFulfill; RepoLens calls it over HTTP. This split changes repository packaging and startup paths, not the business protocol.

```text
parent/
  EventFulfill/event-platform/  Java booking and task-control service
  RepoLens/repo-agent/          Python Agent worker
```

## Native workflow

1. Clone both repositories side by side.
2. In EventFulfill run `./scripts/init-local.ps1`, `./scripts/verify.ps1` and `./scripts/runtime.ps1 -Group core`. Then run `./scripts/event-start.ps1` in a long-running terminal.
3. In RepoLens run `./scripts/init-local.ps1`, then `./scripts/agent-start.ps1 -EventFulfillRoot ../EventFulfill`. The startup process reads only the generated shared Agent secret from the specified Java checkout, without printing it.
4. Open http://127.0.0.1:8090/ for the UI. Java health is 8090/actuator/health; Agent health is 8092/health. Use generated local demo credentials.

## Container workflow

1. Build EventFulfill after Java verification: `./scripts/apps-build.ps1`.
2. In RepoLens: `./scripts/init-local.ps1`, `./scripts/executor-build.ps1`, `./scripts/apps-build.ps1`.
3. Stop native application processes first, then run `./scripts/integration.ps1 -EventFulfillRoot ../EventFulfill` in RepoLens. It combines both Compose definitions under the existing dedicated internship-projects project name and initializes only that application's schema.
4. Stop with the same command plus `-Stop`; data volumes are retained. Do not run multiple checkouts of this same application at once, or stack optional search/governance/K8s groups on a resource-constrained machine.

The integration script creates an ignored `.local/integration.env` from the two generated local configurations; no credentials are included in Git. Model API keys stay in RepoLens/repo-agent/.env, with live calls disabled by default. Default CI checks each repository separately and does not start a paid model or full container deployment.

The split has independent source/test/configuration validation. Earlier real middleware/model/approval tests apply to the same underlying business implementation; they are not relabeled as a new paid end-to-end run of the two-checkout deployment.
