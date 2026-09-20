[CmdletBinding()]
param(
    [string]$InstallerPath
)

$ErrorActionPreference = "Stop"
if (-not $InstallerPath) {
    $InstallerPath = Join-Path $PSScriptRoot "..\dist-installer\Oni-Thermal-LCD-Control-Setup.exe"
}
$InstallerPath = [IO.Path]::GetFullPath($InstallerPath)
$SmokeRoot = Join-Path ([IO.Path]::GetTempPath()) ("oni-installer-smoke-" + [Guid]::NewGuid().ToString("N"))
$InstallDir = Join-Path $SmokeRoot "app"
$AppDataDir = Join-Path $SmokeRoot "appdata"
$StartMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Oni Thermal LCD Control.lnk"
$Desktop = Join-Path ([Environment]::GetFolderPath("Desktop")) "Oni Thermal LCD Control.lnk"
$Sentinel = Join-Path $AppDataDir "OniThermalLcd\preserve-after-uninstall.txt"
$UninstallRoot = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall"
$InstalledSplash = Join-Path $SmokeRoot "installed-splash.png"
$InstalledMain = Join-Path $SmokeRoot "installed-main.png"

if (-not (Test-Path -LiteralPath $InstallerPath)) { throw "Installer not found: $InstallerPath" }
New-Item -ItemType Directory -Force -Path (Split-Path $Sentinel -Parent) | Out-Null
Set-Content -LiteralPath $Sentinel -Value "preserve"

try {
    $Install = Start-Process -FilePath $InstallerPath -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER",
        "/TASKS=desktopicon", "/DIR=$InstallDir"
    ) -Wait -PassThru
    if ($Install.ExitCode -ne 0) { throw "Installer exited $($Install.ExitCode)" }

    $Exe = Join-Path $InstallDir "Oni Thermal LCD Control.exe"
    $Uninstaller = Join-Path $InstallDir "unins000.exe"
    foreach ($Path in @($Exe, $Uninstaller, $StartMenu, $Desktop)) {
        if (-not (Test-Path -LiteralPath $Path)) { throw "Expected installed item is missing: $Path" }
    }
    $UninstallEntry = Get-ChildItem -LiteralPath $UninstallRoot | Where-Object {
        $_.GetValue("DisplayName") -eq "Oni Thermal LCD Control"
    } | Select-Object -First 1
    if (-not $UninstallEntry) { throw "Registered uninstall entry is missing" }

    $env:LOCALAPPDATA = $AppDataDir
    $env:ONI_LCD_GUI_SMOKE_TEST = "1"
    $env:ONI_LCD_GUI_SMOKE_HOLD_MS = "1500"
    $env:ONI_LCD_INSTANCE_NAME = "OniInstallerSmoke-" + [Guid]::NewGuid().ToString("N")
    $env:ONI_LCD_SPLASH_SCREENSHOT = $InstalledSplash
    $env:ONI_LCD_GUI_SCREENSHOT = $InstalledMain
    $Launch = Start-Process -FilePath $StartMenu -Wait -PassThru
    if ($Launch.ExitCode -ne 0) { throw "Start Menu launch exited $($Launch.ExitCode)" }
    foreach ($Path in @($InstalledSplash, $InstalledMain)) {
        if (-not (Test-Path -LiteralPath $Path)) { throw "Installed visual smoke image is missing: $Path" }
    }

    $Uninstall = Start-Process -FilePath $Uninstaller -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
    ) -Wait -PassThru
    if ($Uninstall.ExitCode -ne 0) { throw "Uninstaller exited $($Uninstall.ExitCode)" }
    if (Test-Path -LiteralPath $Exe) { throw "Application remained after uninstall" }
    if (Test-Path -LiteralPath $StartMenu) { throw "Start Menu shortcut remained after uninstall" }
    if (Test-Path -LiteralPath $Desktop) { throw "Desktop shortcut remained after uninstall" }
    if (-not (Test-Path -LiteralPath $Sentinel)) { throw "User settings were deleted during uninstall" }
    if (Test-Path -LiteralPath $UninstallEntry.PSPath) { throw "Uninstall registry entry remained after uninstall" }

    Write-Host "INSTALLER SMOKE: PASS"
    Write-Host "Install, installed launch, shortcut, uninstall, and settings-preservation checks passed."
}
finally {
    Remove-Item Env:ONI_LCD_GUI_SMOKE_TEST -ErrorAction SilentlyContinue
    Remove-Item Env:ONI_LCD_GUI_SMOKE_HOLD_MS -ErrorAction SilentlyContinue
    Remove-Item Env:ONI_LCD_INSTANCE_NAME -ErrorAction SilentlyContinue
    Remove-Item Env:ONI_LCD_SPLASH_SCREENSHOT -ErrorAction SilentlyContinue
    Remove-Item Env:ONI_LCD_GUI_SCREENSHOT -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $SmokeRoot) { Remove-Item -LiteralPath $SmokeRoot -Recurse -Force }
}
