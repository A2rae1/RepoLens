$ErrorActionPreference='Stop'
$workspace=Split-Path -Parent $PSScriptRoot
Push-Location $workspace
try {
 & uv run --project repo-agent --frozen ruff check repo-agent/src repo-agent/tests repo-agent/scripts repo-agent/evaluation
 if($LASTEXITCODE-ne0){throw 'Python lint failed.'}
 & uv run --project repo-agent --frozen pytest repo-agent/tests -q
 if($LASTEXITCODE-ne0){throw 'Python tests failed.'}
}finally{Pop-Location}

& mvn -B -ntp -f (Join-Path $workspace 'repo-control/pom.xml') verify
if($LASTEXITCODE-ne0){throw 'Independent Java control verification failed.'}
& node --test (Join-Path $workspace 'repo-control/ui-tests/event-stream.test.mjs')
if($LASTEXITCODE-ne0){throw 'Event stream checks failed.'}
