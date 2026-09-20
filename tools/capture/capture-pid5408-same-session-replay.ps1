param(
    [switch]$Elevated,
    [Parameter(Mandatory=$true)][string]$DeviceInstanceId
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if (-not $Elevated) {
    $safeDeviceInstanceId = $DeviceInstanceId.Replace("'", "''")
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Elevated -DeviceInstanceId '$safeDeviceInstanceId'"
    Start-Process powershell.exe -Verb RunAs -ArgumentList $arg -WorkingDirectory $root -WindowStyle Normal -Wait
    exit $LASTEXITCODE
}
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$capture = Join-Path $root "captures\originals\live_5408_same_session_$stamp.pcap"
$usbpcap = 'C:\Program Files\USBPcap\USBPcapCMD.exe'
if (-not (Test-Path -LiteralPath $usbpcap)) { throw 'USBPcapCMD not found' }
$cap = Start-Process -FilePath $usbpcap -ArgumentList @('-d','\\.\USBPcap3','-o',$capture,'--inject-descriptors','-A') -PassThru -WindowStyle Hidden
try {
    Start-Sleep -Seconds 2
    $env:PYTHONPATH = Join-Path $root 'src'
    & python -m thermalright_lcd replay `
      (Join-Path $root 'analysis\pid5408-new-session-first-frame.json') `
      --session-file (Join-Path $root 'analysis\session-report.json') `
      --transaction 1 `
      --device $DeviceInstanceId `
      --sequence '0416:5408/pid5408-new-session-first-frame-transaction-1' `
      --send --i-understand-live-usb
    $replayExit = $LASTEXITCODE
} finally {
    if (-not $cap.HasExited) { Stop-Process -Id $cap.Id -ErrorAction SilentlyContinue }
    $cap.WaitForExit(5000) | Out-Null
}
Write-Host "Capture preserved: $capture"
exit $replayExit
