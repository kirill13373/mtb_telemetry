$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PiHost = "mtb-pi"
$RemoteRoot = "/home/pi/mtb_telemetry"
$RemoteDeployDir = "$RemoteRoot/deploy/sufni"

$ProjectRoot = (
    Resolve-Path (Join-Path $PSScriptRoot "..")
).Path

$SourceDir = Join-Path $ProjectRoot "deploy\sufni"

if (-not (Test-Path -LiteralPath $SourceDir)) {
    throw "Source directory not found: $SourceDir"
}

Write-Host "Deploying Sufni test helpers..."
Write-Host "Source: $SourceDir"
Write-Host "Target: ${PiHost}:${RemoteDeployDir}"

$RemoteCommand = @'
set -e
mkdir -p "$REMOTE_DEPLOY_DIR"
'@

$RemoteCommand = $RemoteCommand.Replace("`r`n", "`n")

$RemoteCommand | & ssh $PiHost "REMOTE_DEPLOY_DIR='$RemoteDeployDir' bash -s"

if ($LASTEXITCODE -ne 0) {
    throw "Failed to create remote directory."
}

& scp (Join-Path $SourceDir "sufni_test.sh") "${PiHost}:${RemoteDeployDir}/sufni_test.sh"

if ($LASTEXITCODE -ne 0) {
    throw "Failed to upload sufni_test.sh."
}

$FixupCommand = @'
set -e
sed -i 's/\r$//' "$REMOTE_SCRIPT"
chmod +x "$REMOTE_SCRIPT"
echo 'Remote Sufni test helper updated.'
'@

$FixupCommand = $FixupCommand.Replace("`r`n", "`n")

$FixupCommand | & ssh $PiHost "REMOTE_SCRIPT='$RemoteDeployDir/sufni_test.sh' bash -s"

if ($LASTEXITCODE -ne 0) {
    throw "Failed to finalize remote helper installation."
}

Write-Host "Sufni test helper deployment completed."