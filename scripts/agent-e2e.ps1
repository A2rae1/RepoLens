param([Parameter(Mandatory=$true)][string]$EventFulfillRoot,[ValidatePattern('^[a-z0-9][a-z0-9_-]{0,40}$')][string]$ProjectName='internship-projects',[switch]$Extended,[switch]$StreamProbe,[switch]$Observability,[switch]$LiveTrace,[switch]$RestartProbe)
$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
$control=(Resolve-Path -LiteralPath $EventFulfillRoot).Path
foreach($path in @((Join-Path $control 'infra/.env'),(Join-Path $workspace 'infra/.env'))) {
 foreach($line in [IO.File]::ReadAllLines($path)) {if($line-match'^([A-Z][A-Z0-9_]*)=(.*)$'){[Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process')}}
}
$env:PYTHONPATH=Join-Path $workspace 'repo-agent/src'
$env:PYTHONIOENCODING='utf-8'
$env:E2E_COMPOSE_PROJECT=$ProjectName
$probe=if($RestartProbe){'checkpoint_restart_probe.py'}elseif($Observability-or$LiveTrace){'observability_probe.py'}elseif($StreamProbe){'proxy_stream_probe.py'}elseif($Extended){'e2e_extended.py'}else{'e2e_live.py'}
Push-Location (Join-Path $workspace 'repo-agent')
try {if($LiveTrace){& uv run python "scripts/$probe" --live}else{& uv run python "scripts/$probe"};if($LASTEXITCODE-ne0){throw 'Cross-service acceptance failed.'}}finally{Pop-Location}
