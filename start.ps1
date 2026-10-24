$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

docker build -f Dockerfile -t credit-cabinet-app:local .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

docker build -f frontend/Dockerfile -t credit-cabinet-frontend:local ./frontend
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Running tests..."
$testExitCode = 1
$cleanupExitCode = 1
try {
    docker compose -f compose.yaml --profile test up --exit-code-from tests tests
    $testExitCode = $LASTEXITCODE
}
finally {
    docker compose -f compose.yaml --profile test rm -sf tests postgres-test
    $cleanupExitCode = $LASTEXITCODE
}
if ($testExitCode -ne 0) { exit $testExitCode }
if ($cleanupExitCode -ne 0) { exit $cleanupExitCode }

docker compose -f compose.yaml up -d frontend
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Frontend URL: http://localhost:8080"
