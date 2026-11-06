param([Parameter(Mandatory=$true)][string]$EventFulfillRoot,[switch]$Stop,[switch]$ConfigOnly)
$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
$control=(Resolve-Path -LiteralPath $EventFulfillRoot).Path
if(-not(Test-Path -LiteralPath (Join-Path $control 'event-platform/pom.xml'))){throw 'EventFulfill checkout not found.'}
$env:PATH="$env:LOCALAPPDATA/Programs/DockerDesktop/resources/bin;$env:PATH"
if(-not $ConfigOnly){& (Join-Path $control 'scripts/init-local.ps1');& "$PSScriptRoot/init-local.ps1"}
$combined=@{}
foreach($path in @((Join-Path $control 'infra/.env'),(Join-Path $workspace 'infra/.env'))) {
 foreach($line in [IO.File]::ReadAllLines($path)) {if($line-match'^([A-Z][A-Z0-9_]*)=(.*)$'){$combined[$Matches[1]]=$Matches[2]}}
}
$env:REPOLENS_ROOT=$workspace.Replace([IO.Path]::DirectorySeparatorChar,[char]'/')
$private=Join-Path $workspace '.local/integration.env'
New-Item -ItemType Directory -Force (Split-Path -Parent $private)|Out-Null
$combined.GetEnumerator()|ForEach-Object {"$($_.Key)=$($_.Value)"}|Set-Content -LiteralPath $private
$argsCompose=@('compose','--project-name','internship-projects','--env-file',$private,'-f',(Join-Path $control 'infra/compose.yml'),'-f',(Join-Path $control 'infra/compose.apps.yml'),'-f',(Join-Path $workspace 'infra/compose.yml'),'-f',(Join-Path $workspace 'infra/compose.apps.yml'))
if($ConfigOnly){& docker @argsCompose config --quiet;exit $LASTEXITCODE}
if($Stop){& docker @argsCompose stop;exit $LASTEXITCODE}
& docker @argsCompose up -d mysql redis namesrv broker postgres objectstore
if($LASTEXITCODE-ne0){throw 'Integration middleware did not start.'}
$deadline=(Get-Date).AddSeconds(100)
do {$health=(& docker inspect internship-projects-mysql-1 --format '{{.State.Health.Status}}');if($health.Trim()-eq'healthy'){break};Start-Sleep -Milliseconds 500}while((Get-Date)-lt$deadline)
if($health.Trim()-ne'healthy'){throw 'Own MySQL not ready.'}
Get-Content -LiteralPath (Join-Path $control 'infra/mysql/02-app-database.sql') -Raw|& docker exec -i internship-projects-mysql-1 sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot'
if($LASTEXITCODE-ne0){throw 'Own application schema initialization failed.'}
& docker @argsCompose up -d event-app repo-agent
if($LASTEXITCODE-ne0){throw 'Integration application startup failed.'}
Write-Output 'Two-checkout application group started. Check Java8090 and Agent8092 health; no paid model request was sent.'
