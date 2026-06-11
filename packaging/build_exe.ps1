# Build the standalone AIAnalyzer Windows .exe.
#
# Usage (from repo root):
#   .\packaging\build_exe.ps1
#
# Output:
#   dist\aianalyzer.exe   (single-file, double-clickable)
#
# What it does:
#   1. Ensures PyInstaller is installed (pip --upgrade for newest hooks).
#   2. Wipes any previous build/ and dist/ to avoid stale data files.
#   3. Runs PyInstaller against packaging/aianalyzer.spec.
#   4. Reports the resulting .exe path and size.

[CmdletBinding()]
param(
    [switch] $Clean,            # Force-wipe build artifacts before building.
    [switch] $SkipInstall       # Skip pip install (useful for repeat builds).
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $repoRoot
try {
    if (-not $SkipInstall) {
        Write-Host "==> Ensuring PyInstaller is installed" -ForegroundColor Cyan
        python -m pip install --quiet --upgrade pyinstaller
    }

    if ($Clean -or (Test-Path build)) { Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue }
    if ($Clean -or (Test-Path dist))  { Remove-Item -Recurse -Force dist  -ErrorAction SilentlyContinue }

    # Force `import aianalyzer` (used by collect_data_files inside the spec)
    # to resolve to THIS worktree's src, not a sibling editable install. This
    # matters when developing in multiple git worktrees: without this pin,
    # PyInstaller silently bundles the other worktree's static/ assets.
    $env:PYTHONPATH = (Join-Path $repoRoot "src")

    Write-Host "==> Building aicodestyle (one-folder bundle)" -ForegroundColor Cyan
    python -m PyInstaller packaging/aianalyzer.spec --clean --noconfirm

    $bundleDir = Join-Path $repoRoot "dist\aicodestyle"
    $exe = Join-Path $bundleDir "aicodestyle.exe"
    if (-not (Test-Path $exe)) {
        Write-Host "Build failed: $exe not found" -ForegroundColor Red
        exit 1
    }

    # Zip the bundle for distribution. One-folder mode gives us a portable
    # directory; the .zip is what teammates actually download and unzip.
    $zip = Join-Path $repoRoot "dist\aicodestyle.zip"
    if (Test-Path $zip) { Remove-Item $zip }
    Compress-Archive -Path $bundleDir -DestinationPath $zip -CompressionLevel Optimal

    $folderMb = [math]::Round(((Get-ChildItem -Recurse $bundleDir | Measure-Object Length -Sum).Sum) / 1MB, 1)
    $zipMb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Build succeeded:" -ForegroundColor Green
    Write-Host "  Bundle folder: $bundleDir  ($folderMb MB)"
    Write-Host "  Shareable zip: $zip  ($zipMb MB)"
    Write-Host ""
    Write-Host "To smoke-test:  & '$exe' --help"
    Write-Host "To run portal:  & '$exe'        (then browser opens automatically)"
    Write-Host ""
    Write-Host "To share with a teammate: send them aicodestyle.zip; they unzip"
    Write-Host "  anywhere (Desktop, OneDrive, etc.) and double-click aicodestyle.exe."
}
finally {
    Pop-Location
}
