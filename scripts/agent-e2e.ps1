param([ValidatePattern('^[a-z0-9][a-z0-9_-]{0,40}$')][string]$ProjectName='repolens',[switch]$Extended,[switch]$StreamProbe,[switch]$RestartProbe)
$ErrorActionPreference='Stop';$workspace=Split-Path -Parent $PSScriptRoot
foreach($line in [IO.File]::ReadAllLines((Join-Path $workspace 'infra/.env'))){if($line-match'^([A-Z][A-Z0-9_]*)=(.*)$'){[Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process')}}
$env:E2E_COMPOSE_PROJECT=$ProjectName;$env:CONTROL_API_URL='http://127.0.0.1:8094';$env:PYTHONPATH=Join-Path $workspace 'repo-agent/src';$env:PYTHONIOENCODING='utf-8'
$probe=if($RestartProbe){'checkpoint_restart_probe.py'}elseif($StreamProbe){'proxy_stream_probe.py'}elseif($Extended){'e2e_extended.py'}else{'e2e_live.py'}
Push-Location (Join-Path $workspace 'repo-agent');try{& uv run python "scripts/$probe";if($LASTEXITCODE-ne0){throw 'Independent Agent acceptance failed.'}}finally{Pop-Location}
