$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
foreach($dir in @('infra','repo-agent/.local','.local')){New-Item -ItemType Directory -Force (Join-Path $workspace $dir)|Out-Null}
$config=Join-Path $workspace 'infra/.env'
$lines=if(Test-Path -LiteralPath $config){[IO.File]::ReadAllLines($config)}else{@()}
foreach($name in @('MYSQL_ROOT_PASSWORD','REPOLENS_DB_PASSWORD','REPOLENS_JWT_SECRET','REPOLENS_DEMO_PASSWORD','AGENT_INTERNAL_SECRET','AGENT_CHECKPOINT_PASSWORD','AGENT_OBJECT_PASSWORD')){
 if(-not($lines|Where-Object {$_-match("^"+$name+"=")})){Add-Content -LiteralPath $config -Value "$name=$([Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)))" -Encoding utf8}
}
$model=Join-Path $workspace 'repo-agent/.env'
if(-not(Test-Path -LiteralPath $model)){Copy-Item -LiteralPath (Join-Path $workspace 'repo-agent/.env.example') -Destination $model}
Write-Output 'Independent RepoLens configuration ready. Existing values retained; no credentials printed.'
