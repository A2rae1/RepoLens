$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
foreach($configLine in [IO.File]::ReadAllLines((Join-Path $workspace 'infra/.env'))) {
    if($configLine -match '^([A-Z][A-Z0-9_]*)=(.*)$') {[Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process')}
}
$env:CHECKPOINT_URL="postgresql://repoagent:$($env:AGENT_CHECKPOINT_PASSWORD)@127.0.0.1:15433/repoagent"
$env:POSTGRES_IT='true'
$env:PYTHONPATH=Join-Path $workspace 'repo-agent/src'
Push-Location (Join-Path $workspace 'repo-agent')
try {& uv run pytest -q tests/test_postgres_live.py; if($LASTEXITCODE -ne 0){throw 'Own Postgres checkpoint integration failed.'}} finally {Pop-Location}
