[CmdletBinding()]
param(
    [string]$CompilerPath
)

$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PortableExe = Join-Path $RepoRoot "dist\Oni Thermal LCD Control.exe"
$InstallerPath = Join-Path $RepoRoot "dist-installer\Oni-Thermal-LCD-Control-Setup.exe"
$ScriptPath = Join-Path $PSScriptRoot "oni_thermal_lcd.iss"

if (-not (Test-Path -LiteralPath $PortableExe)) {
    throw "Portable application is missing. Run packaging\build-portable.ps1 first."
}

if (-not $CompilerPath) {
    $Candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )
    $CompilerPath = $Candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
}
if (-not $CompilerPath -or -not (Test-Path -LiteralPath $CompilerPath)) {
    throw "Inno Setup 6 compiler was not found. Install JRSoftware.InnoSetup or pass -CompilerPath."
}

& $CompilerPath $ScriptPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $InstallerPath)) {
    throw "Installer build failed."
}

$Item = Get-Item -LiteralPath $InstallerPath
$Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPath).Hash.ToLowerInvariant()
Write-Host "Built: $($Item.FullName)"
Write-Host "Bytes: $($Item.Length)"
Write-Host "SHA-256: $Hash"
