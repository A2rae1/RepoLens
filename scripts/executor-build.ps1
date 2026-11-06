$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
$env:PATH="$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin;$env:PATH"
& docker build --progress plain -t repolens-runner:py312-v1 (Join-Path $workspace 'repo-agent/executor')
if($LASTEXITCODE -ne 0){throw 'Runner image build failed.'}
$imageId=& docker image inspect --format '{{.Id}}' repolens-runner:py312-v1
if($imageId -notmatch '^sha256:[a-f0-9]{64}$'){throw 'Runner image ID not verified.'}
$manifest=@{tag='repolens-runner:py312-v1';id=$imageId.Trim();source='repo-agent/executor/Dockerfile';scope='local trusted runner image, source repository is mounted only at runtime'}
$manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $workspace 'repo-agent/.local/runner-image.json') -Encoding utf8
Write-Output 'Pinned local runner image digest. New approval plans bind this digest.'
