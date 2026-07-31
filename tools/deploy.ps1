$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$PiHost = "mtb-pi"
$RemoteProject = "/home/pi/mtb_telemetry"

$ProjectRoot = (
    Resolve-Path (Join-Path $PSScriptRoot "..")
).Path

$TempRoot = Join-Path `
    $env:TEMP `
    ("mtb_telemetry_" + [Guid]::NewGuid().ToString("N"))

$StageDirectory = Join-Path $TempRoot "package"
$ArchivePath = Join-Path $TempRoot "mtb_telemetry_deploy.tar"
$RemoteArchive = "/tmp/mtb_telemetry_deploy.tar"

# Nur diese Bestandteile gehören auf das Zielsystem.
$DeploymentItems = @(
    "src",
    "config",
    "calibration",
    "scripts",
    "deploy",
    "pyproject.toml",
    "README.md"
)

try {
    Write-Host "Preparing deployment..."
    Write-Host "Source: $ProjectRoot"
    Write-Host "Target: ${PiHost}:${RemoteProject}"

    New-Item `
        -ItemType Directory `
        -Path $StageDirectory `
        -Force | Out-Null

    foreach ($Item in $DeploymentItems) {
        $SourcePath = Join-Path $ProjectRoot $Item

        if (-not (Test-Path -LiteralPath $SourcePath)) {
            Write-Warning "Skipped missing item: $Item"
            continue
        }

        Write-Host "Adding: $Item"

        Copy-Item `
            -LiteralPath $SourcePath `
            -Destination $StageDirectory `
            -Recurse `
            -Force
    }

    # Dateien entfernen, die nie auf den Pi deployed werden sollen.
    Get-ChildItem `
        -Path $StageDirectory `
        -Directory `
        -Recurse `
        -Force `
        -Filter "__pycache__" |
        Remove-Item -Recurse -Force

    Get-ChildItem `
        -Path $StageDirectory `
        -File `
        -Recurse `
        -Force `
        -Include "*.pyc", "*.pyo" |
        Remove-Item -Force

    # Generierte Paket-Metadaten werden auf dem Pi neu erzeugt.
    Get-ChildItem `
        -Path $StageDirectory `
        -Directory `
        -Recurse `
        -Force |
        Where-Object { $_.Name -like "*.egg-info" } |
        Remove-Item -Recurse -Force

    Write-Host "Creating TAR package..."

    Push-Location $StageDirectory

    try {
        & tar -cf $ArchivePath .

        if ($LASTEXITCODE -ne 0) {
            throw "TAR creation failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }

    $ArchiveSizeMB = [Math]::Round(
        (Get-Item -LiteralPath $ArchivePath).Length / 1MB,
        2
    )

    Write-Host "Package size: $ArchiveSizeMB MB"

    if ($ArchiveSizeMB -gt 100) {
        throw "Deployment package is unexpectedly large: $ArchiveSizeMB MB"
    }

    Write-Host "Uploading deployment package..."

    & scp $ArchivePath "${PiHost}:${RemoteArchive}"

    if ($LASTEXITCODE -ne 0) {
        throw "SCP upload failed with exit code $LASTEXITCODE."
    }

    Write-Host "Installing files on Raspberry Pi..."

    $RemoteCommand = @'
set -e

REMOTE_PROJECT="/home/pi/mtb_telemetry"
ARCHIVE="/tmp/mtb_telemetry_deploy.tar"

mkdir -p "$REMOTE_PROJECT"
mkdir -p "$REMOTE_PROJECT/data"
mkdir -p "$REMOTE_PROJECT/logs"
mkdir -p "$REMOTE_PROJECT/plots"

find "$REMOTE_PROJECT" \
    -mindepth 1 \
    -maxdepth 1 \
    ! -name "venv" \
    ! -name ".venv" \
    ! -name "data" \
    ! -name "logs" \
    ! -name "plots" \
    -exec rm -rf -- {} +

tar -xf "$ARCHIVE" -C "$REMOTE_PROJECT"

if [ -d "$REMOTE_PROJECT/scripts" ]; then
    find "$REMOTE_PROJECT/scripts" -type f -name "*.sh" -print0 |
        while IFS= read -r -d '' script_path; do
            sed -i 's/\r$//' "$script_path"
            chmod +x "$script_path"
        done
fi

if [ -d "$REMOTE_PROJECT/deploy/systemd" ]; then
    find "$REMOTE_PROJECT/deploy/systemd" -type f -name "*.service" -exec sed -i 's/\r$//' {} +
fi

cd "$REMOTE_PROJECT"
venv/bin/python -m pip install -e .

rm -f "$ARCHIVE"

echo "Remote installation completed."
'@

    # Bash-Befehl ohne problematische Windows-Zeilenenden übertragen.
    $RemoteCommand = $RemoteCommand.Replace("`r`n", "`n")
    $RemoteCommand | & ssh $PiHost "bash -s"

    if ($LASTEXITCODE -ne 0) {
        throw "Remote installation failed with exit code $LASTEXITCODE."
    }

    Write-Host ""
    Write-Host "Deployment completed successfully."
}
finally {
    if (Test-Path -LiteralPath $TempRoot) {
        Remove-Item `
            -LiteralPath $TempRoot `
            -Recurse `
            -Force `
            -ErrorAction SilentlyContinue
    }
}