param([switch]$Postgres,[switch]$Search)
$ErrorActionPreference='Stop';$workspace=Split-Path -Parent $PSScriptRoot
foreach($line in [IO.File]::ReadAllLines((Join-Path $workspace 'infra/.env'))){if($line-match'^([A-Z][A-Z0-9_]*)=(.*)$'){[Environment]::SetEnvironmentVariable($Matches[1],$Matches[2],'Process')}}
$env:CONTROL_URL='http://127.0.0.1:8094';$env:OBJECT_URL='http://127.0.0.1:19010';$env:REDIS_URL='redis://127.0.0.1:16380/1';$env:ES_URL='http://127.0.0.1:19210';$env:OBJECT_SECRET_KEY=$env:AGENT_OBJECT_PASSWORD
if($Postgres){$env:CHECKPOINT_URL="postgresql://repoagent:$($env:AGENT_CHECKPOINT_PASSWORD)@127.0.0.1:15433/repoagent"}
$env:DOCKER_EXECUTABLE="$env:LOCALAPPDATA/Programs/DockerDesktop/resources/bin/docker.exe";$env:PYTHONPATH=Join-Path $workspace 'repo-agent/src'
Push-Location (Join-Path $workspace 'repo-agent');try{if($Search){$env:EMBEDDING_ENABLED='true';$env:SEARCH_BACKEND='hybrid';& uv run --extra embedding uvicorn repo_agent.app:create_app --factory --host 127.0.0.1 --port 8092}else{& uv run uvicorn repo_agent.app:create_app --factory --host 127.0.0.1 --port 8092}}finally{Pop-Location}
