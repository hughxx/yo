$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BuildVenv = Join-Path $ProjectDir ".build-venv"
$Python = Join-Path $BuildVenv "Scripts\python.exe"
$env:PYINSTALLER_CONFIG_DIR = Join-Path $ProjectDir ".pyinstaller-cache"
$env:PIP_CACHE_DIR = Join-Path $ProjectDir ".pip-cache"

Push-Location $ProjectDir
try {
    if (-not (Test-Path -LiteralPath $Python)) {
        python -m venv $BuildVenv
    }

    & $Python -m pip install --disable-pip-version-check -r (Join-Path $ProjectDir "requirements-build.txt")
    & $Python -m PyInstaller --noconfirm --clean (Join-Path $ProjectDir "coreinsight-local-toolkit.spec")

    $Exe = Join-Path $ProjectDir "dist\coreinsight-local-toolkit.exe"
    if (-not (Test-Path -LiteralPath $Exe)) {
        throw "Build completed without expected executable: $Exe"
    }
} finally {
    Pop-Location
}

Write-Host "Built: $Exe"
