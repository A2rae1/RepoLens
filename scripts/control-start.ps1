$ErrorActionPreference='Stop';$workspace=Split-Path -Parent $PSScriptRoot
foreach($line in [IO.File]::ReadAllLines((Join-Path $workspace 'infra/.env'))){if($line-match'^([A-Z][A-Z0-9_]*)=(.*)$'){[Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process')}}
$env:REPOLENS_DEMO_USERS='true';$env:ROCKETMQ_NAMESRV='127.0.0.1:19877'
& java -jar (Join-Path $workspace 'repo-control/target/repolens-control-0.1.0.jar')
