$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
$env:DOCKER_EXECUTABLE=Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
$env:EXECUTOR_IT='true'
$env:PYTHONIOENCODING='utf-8'
Push-Location (Join-Path $workspace 'repo-agent')
try{& uv run pytest -q tests/test_executor_live.py; if($LASTEXITCODE -ne 0){throw 'Real isolated-executor verification failed.'}}finally{Pop-Location}
