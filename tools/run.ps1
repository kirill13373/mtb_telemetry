$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PiHost = "mtb-pi"
$RemoteProject = "/home/pi/mtb_telemetry"
$RemotePython = "$RemoteProject/venv/bin/python"

Write-Host "Starting MTB Telemetry on Raspberry Pi..."
Write-Host "Target: $PiHost"

& ssh $PiHost `
    "cd '$RemoteProject' && '$RemotePython' -m mtb_telemetry.main"

if ($LASTEXITCODE -ne 0) {
    throw "Program exited with code $LASTEXITCODE."
}