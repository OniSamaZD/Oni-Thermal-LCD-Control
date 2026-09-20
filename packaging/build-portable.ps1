[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$NoClean
)

$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$DistRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "dist"))
$WorkRoot = [IO.Path]::GetFullPath((Join-Path $RepoRoot "build\pyinstaller"))
$ExePath = Join-Path $DistRoot "Oni Thermal LCD Control.exe"

if (-not $DistRoot.StartsWith($RepoRoot, [StringComparison]::OrdinalIgnoreCase) -or
    -not $WorkRoot.StartsWith($RepoRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to clean paths outside the repository"
}

py -3.12 -c "import PyInstaller, PySide6, PIL, psutil, cv2, av"
if ($LASTEXITCODE -ne 0) { throw "Python 3.12 packaging dependencies are incomplete" }

if (-not $SkipTests) {
    $PreviousPythonPath = $env:PYTHONPATH
    $env:PYTHONPATH = Join-Path $RepoRoot "src"
    py -3.12 -m unittest discover -s tests -v
    if ($null -eq $PreviousPythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
    else { $env:PYTHONPATH = $PreviousPythonPath }
    if ($LASTEXITCODE -ne 0) { throw "Regression tests failed; packaging aborted" }
}

$IconPath = Join-Path $RepoRoot "assets\oni-thermal-lcd.ico"
$IconPreviewPath = Join-Path $RepoRoot "assets\oni-thermal-lcd-icon.png"
if (-not (Test-Path -LiteralPath $IconPath) -or -not (Test-Path -LiteralPath $IconPreviewPath)) {
    Write-Host "Oni icon assets are missing; generating them explicitly."
    py -3.12 (Join-Path $PSScriptRoot "generate_icon.py")
    if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }
} else {
    Write-Host "Using existing Oni icon assets."
}
py -3.12 (Join-Path $PSScriptRoot "collect_licenses.py")
if ($LASTEXITCODE -ne 0) { throw "Third-party license collection failed" }

if (-not $NoClean) {
    if (Test-Path -LiteralPath $WorkRoot) { Remove-Item -LiteralPath $WorkRoot -Recurse -Force }
    if (Test-Path -LiteralPath $DistRoot) { Remove-Item -LiteralPath $DistRoot -Recurse -Force }
}
New-Item -ItemType Directory -Force -Path $DistRoot, $WorkRoot | Out-Null

py -3.12 -m PyInstaller --noconfirm --clean `
    --distpath $DistRoot --workpath $WorkRoot `
    (Join-Path $PSScriptRoot "oni_thermal_lcd.spec")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ExePath)) {
    throw "Portable executable build failed"
}

$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ExePath).Hash.ToLowerInvariant()
$Size = (Get-Item -LiteralPath $ExePath).Length
Copy-Item -LiteralPath (Join-Path $RepoRoot "THIRD_PARTY_NOTICES.md") -Destination $DistRoot -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "LICENSE") -Destination $DistRoot -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "README.md") -Destination $DistRoot -Force
Copy-Item -LiteralPath (Join-Path $RepoRoot "CHANGELOG.md") -Destination $DistRoot -Force
$LicenseDestination = Join-Path $DistRoot "third-party-licenses"
if (Test-Path -LiteralPath $LicenseDestination) { Remove-Item -LiteralPath $LicenseDestination -Recurse -Force }
Copy-Item -LiteralPath (Join-Path $RepoRoot "build\third-party-licenses") -Destination $LicenseDestination -Recurse
py -3.12 (Join-Path $PSScriptRoot "benchmark_executable.py") --candidate "pyinstaller=$ExePath" --runs 1 --output (Join-Path $RepoRoot "analysis\packaging-build-smoke.json")
if ($LASTEXITCODE -ne 0) { throw "Portable executable smoke test failed" }
Write-Host "Built: $ExePath"
Write-Host "Bytes: $Size"
Write-Host "SHA-256: $Hash"
