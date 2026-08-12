param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments = @()
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PiHost = "mtb-pi"
$RemoteRoot = "/home/pi/mtb_telemetry"
$RemoteScript = "$RemoteRoot/deploy/sufni/sufni_test.sh"

$escapedCommand = $Command.Replace("'", "''")
$argumentString = ""

if ($Arguments) {
    $argumentString = ($Arguments | ForEach-Object {
        "'" + $_.Replace("'", "''") + "'"
    }) -join " "
}

$remoteInvocation = if ([string]::IsNullOrWhiteSpace($argumentString)) {
    "bash '$RemoteScript' '$escapedCommand'"
} else {
    "bash '$RemoteScript' '$escapedCommand' $argumentString"
}

Write-Host "Running remote Sufni test helper..."
Write-Host "Target: $PiHost"
Write-Host "Command: $Command"

& ssh $PiHost $remoteInvocation

if ($LASTEXITCODE -ne 0) {
    throw "Remote helper exited with code $LASTEXITCODE."
}