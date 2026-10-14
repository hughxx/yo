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
        if ($LASTEXITCODE -ne 0) { throw "Failed to create build environment" }
    }

    & $Python -m pip install --disable-pip-version-check -r (Join-Path $ProjectDir "requirements-build.txt")
    if ($LASTEXITCODE -ne 0) { throw "Failed to install build dependencies" }
    & $Python -m PyInstaller --noconfirm --clean (Join-Path $ProjectDir "coreinsight-local-toolkit.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

    $Exe = Join-Path $ProjectDir "dist\coreinsight-local-toolkit.exe"
    if (-not (Test-Path -LiteralPath $Exe)) {
        throw "Build completed without expected executable: $Exe"
    }

    $Version = & $Python -c "from coreinsight_local_toolkit import __version__; print(__version__)"
    if ($LASTEXITCODE -ne 0) { throw "Failed to read application version" }
    $ReleaseConfig = Get-Content -LiteralPath (Join-Path $ProjectDir "release-config.example.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    $ReleaseNotes = ConvertTo-Json -InputObject @($ReleaseConfig.releaseNotes) -Compress -Depth 10
    $BuiltAt = [DateTimeOffset]::Now
    $ConfigChanges = [ordered]@{
        latestVersion = $Version.Trim()
        sha256 = (Get-FileHash -LiteralPath $Exe -Algorithm SHA256).Hash.ToLowerInvariant()
        releaseNotes = $ReleaseNotes
        publishedAt = $BuiltAt.ToString("yyyy-MM-dd'T'HH:mm:sszzz", [Globalization.CultureInfo]::InvariantCulture)
    }
    $Timestamp = $BuiltAt.ToString("yyyyMMdd-HHmmss-fff", [Globalization.CultureInfo]::InvariantCulture)
    $ConfigChangesFile = Join-Path $ProjectDir "dist\release-config-$Timestamp.txt"
    $ConfigLines = @($ConfigChanges.GetEnumerator() | ForEach-Object { "{0}={1}" -f $_.Key, $_.Value })
    [IO.File]::WriteAllLines($ConfigChangesFile, $ConfigLines, [Text.UTF8Encoding]::new($false))
} finally {
    Pop-Location
}

Write-Host "Built: $Exe"
Write-Host "Release config changes (EXE SHA256): $ConfigChangesFile"
