$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Host "=== Deploy ==="

& "$PSScriptRoot\deploy.ps1"

if ($LASTEXITCODE -ne 0) {
    throw "Deployment failed."
}

Write-Host ""
Write-Host "=== Run ==="

& "$PSScriptRoot\run.ps1"

if ($LASTEXITCODE -ne 0) {
    throw "Program failed."
}