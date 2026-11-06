$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
Push-Location $workspace
try {
 & uv run --project repo-agent --frozen ruff check repo-agent/src repo-agent/tests repo-agent/scripts repo-agent/evaluation
 if($LASTEXITCODE-ne0){throw 'Python lint failed.'}
 & uv run --project repo-agent --frozen pytest repo-agent/tests -q
 if($LASTEXITCODE-ne0){throw 'Python tests failed.'}
}finally{Pop-Location}
