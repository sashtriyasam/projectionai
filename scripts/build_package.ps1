# Builds the ProjectionAI distributable: icon, PyInstaller bundle, zip.
# Requires: uv sync --extra dev  (installs pyinstaller + Pillow)
#
# Usage:  powershell -ExecutionPolicy Bypass -File scripts/build_package.ps1
# Output: dist/ProjectionAI/ProjectionAI.exe  and  dist/ProjectionAI-<ver>-win64.zip

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# 1. Programmatic icon (no binary assets in the repo)
uv run python packaging/make_icon.py

# 2. PyInstaller bundle
uv run pyinstaller --noconfirm --clean packaging/projectionai.spec

# 3. Zip for distribution (portable fallback to the installer)
$Version = uv run python -c "from projectionai import __version__; print(__version__)"
$ZipName = "ProjectionAI-$Version-win64.zip"
$ZipPath = Join-Path $Root "dist\$ZipName"
if (Test-Path $ZipPath) { Remove-Item $ZipPath }
Compress-Archive -Path (Join-Path $Root "dist\ProjectionAI\*") -DestinationPath $ZipPath
Write-Host "Built: dist\ProjectionAI\ProjectionAI.exe"
Write-Host "Built: dist\$ZipName"

# 4. Optional installer (Inno Setup) - version flows from projectionai.__version__
#    ISCC resolution: env override, then PATH, then the default install path.
$Iscc = $env:ISCC
if (-not $Iscc) {
    $IsccCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($IsccCommand) { $Iscc = $IsccCommand.Source }
}
if (-not $Iscc) { $Iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" }
if (Test-Path $Iscc) {
    & $Iscc "/DMyAppVersion=$Version" (Join-Path $Root "installer\ProjectionAI.iss")
    if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }
    Write-Host "Built: dist\ProjectionAI-$Version-setup.exe"
}
else {
    Write-Host "Inno Setup not found - skipping installer (portable zip is the artifact)"
}