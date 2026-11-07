$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
foreach($configLine in [IO.File]::ReadAllLines((Join-Path $workspace 'infra/.env'))) {
    if($configLine -match '^([A-Z][A-Z0-9_]*)=(.*)$') {[Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process')}
}
$env:OBJECT_SECRET_KEY=$env:AGENT_OBJECT_PASSWORD
$env:OBJECT_URL='http://127.0.0.1:19010'
$env:OBJECT_IT='true'
$env:PYTHONIOENCODING='utf-8'
Push-Location (Join-Path $workspace 'repo-agent')
try { & uv run pytest -q tests/test_objects_live.py; if($LASTEXITCODE -ne 0){throw 'Real object-store verification failed.'} } finally {Pop-Location}
