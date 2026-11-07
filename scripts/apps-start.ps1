param([ValidatePattern('^[a-z0-9][a-z0-9_-]{0,40}$')][string]$ProjectName='repolens',[string]$OverrideFile,[switch]$Stop,[switch]$ConfigOnly)
$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
$env:PATH="$env:LOCALAPPDATA/Programs/DockerDesktop/resources/bin;$env:PATH"
if(-not($Stop-or$ConfigOnly)){& "$PSScriptRoot/init-local.ps1"}
$env:REPOLENS_RUNNER_VOLUME="${ProjectName}_runner_work"
$argsCompose=@('compose','--project-name',$ProjectName,'--env-file',(Join-Path $workspace 'infra/.env'),'-f',(Join-Path $workspace 'infra/compose.yml'),'-f',(Join-Path $workspace 'infra/compose.apps.yml'))
if($OverrideFile){$argsCompose+=@('-f',(Resolve-Path -LiteralPath $OverrideFile).Path)}
if($ConfigOnly){& docker @argsCompose config --quiet;exit $LASTEXITCODE}
if($Stop){& docker @argsCompose stop;exit $LASTEXITCODE}
& docker @argsCompose up -d mysql redis namesrv broker postgres objectstore control repo-agent
if($LASTEXITCODE-ne0){throw 'Independent RepoLens startup failed.'}
$deadline=(Get-Date).AddSeconds(140);$ready=$false
do{try{$control=Invoke-RestMethod 'http://127.0.0.1:8094/actuator/health' -TimeoutSec 3;$agent=Invoke-RestMethod 'http://127.0.0.1:8092/health' -TimeoutSec 3;$ready=$control.status-eq'UP'-and$agent.status-eq'up'}catch{};if(-not$ready){Start-Sleep -Milliseconds 500}}while(-not$ready-and(Get-Date)-lt$deadline)
if(-not$ready){throw 'Independent RepoLens services did not become healthy.'}
Write-Output 'RepoLens ready on8094; worker8092. EventFulfill not required. Startup sent no paid model request.'
