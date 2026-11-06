$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
foreach($dir in @('infra','repo-agent/.local','.local')){New-Item -ItemType Directory -Force (Join-Path $workspace $dir)|Out-Null}
$config=Join-Path $workspace 'infra/.env'
if(-not(Test-Path -LiteralPath $config)) {
 @('AGENT_CHECKPOINT_PASSWORD','AGENT_OBJECT_PASSWORD')|ForEach-Object {"$_=$([Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32)))"}|Set-Content -LiteralPath $config
}
$model=Join-Path $workspace 'repo-agent/.env'
if(-not(Test-Path -LiteralPath $model)){Copy-Item -LiteralPath (Join-Path $workspace 'repo-agent/.env.example') -Destination $model}
Write-Output 'Local configuration ready; existing values retained and no secrets printed.'
