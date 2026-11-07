param([switch]$ClassicBuilder,[switch]$RefreshDependencies)
$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
$env:PATH="$env:LOCALAPPDATA/Programs/DockerDesktop/resources/bin;$env:PATH"
$lock=Get-Content -LiteralPath (Join-Path $workspace 'infra/image-lock.json') -Raw|ConvertFrom-Json -AsHashtable
$source=Join-Path $workspace 'repo-agent'
$dependencyImage=$null
if(-not$RefreshDependencies){
 $existing=& docker image inspect repolens:local --format '{{.Id}}' 2>$null
 if($LASTEXITCODE-eq0-and$existing-match'^sha256:[a-f0-9]{64}$'){
  # A local immutable runtime may reuse installed packages only for identical lock/metadata.
  $probe=& docker run --rm --network none --entrypoint python $existing -c 'import hashlib,json;from pathlib import Path;print(json.dumps({p:hashlib.sha256(Path("/app/"+p).read_bytes()).hexdigest() for p in ["uv.lock","pyproject.toml"]}))'
  if($LASTEXITCODE-eq0){
   $hashes=$probe|ConvertFrom-Json -AsHashtable
   if(@('uv.lock','pyproject.toml').Where({(Get-FileHash -LiteralPath (Join-Path $source $_) -Algorithm SHA256).Hash.ToLowerInvariant()-ne$hashes[$_]}).Count-eq0){$dependencyImage=$existing.Trim()}
  }
 }
}
$before=$env:DOCKER_BUILDKIT
try{
 if($ClassicBuilder){$env:DOCKER_BUILDKIT='0'}
 if($dependencyImage){
  & docker build -f (Join-Path $source 'Dockerfile.update') --build-arg "DEPENDENCY_IMAGE=$dependencyImage" -t repolens:local $source
 }else{
  & docker build --build-arg "PYTHON_RUNTIME=$($lock['python:3.12-slim-bookworm'])" --build-arg "DOCKER_CLI=$($lock['docker:29-cli'])" -t repolens:local $source
 }
 if($LASTEXITCODE-ne0){throw 'Agent image build failed.'}
}finally{$env:DOCKER_BUILDKIT=$before}
