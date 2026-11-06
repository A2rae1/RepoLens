$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
$env:PATH="$env:LOCALAPPDATA/Programs/DockerDesktop/resources/bin;$env:PATH"
$lock=Get-Content -LiteralPath (Join-Path $workspace 'infra/image-lock.json') -Raw|ConvertFrom-Json -AsHashtable
& docker build --build-arg "PYTHON_RUNTIME=$($lock['python:3.12-slim-bookworm'])" --build-arg "DOCKER_CLI=$($lock['docker:29-cli'])" -t repolens:local (Join-Path $workspace 'repo-agent')
if($LASTEXITCODE-ne0){throw 'Agent image build failed.'}
