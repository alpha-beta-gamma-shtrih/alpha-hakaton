$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

docker build -f Dockerfile -t credit-cabinet-app:local .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

docker build -f frontend/Dockerfile -t credit-cabinet-frontend:local ./frontend
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

docker compose -f compose.yaml up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Frontend URL: http://localhost:8080"
