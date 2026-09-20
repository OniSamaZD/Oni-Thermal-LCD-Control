param(
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$Token
)
$ErrorActionPreference='Stop'
$readyName="Local\ThermalrightUsbPcapReady_$Token"
$stopName="Local\ThermalrightUsbPcapStop_$Token"
$ready=[Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset,$readyName)
$stop=[Threading.EventWaitHandle]::new($false,[Threading.EventResetMode]::ManualReset,$stopName)
$usbpcap='C:\Program Files\USBPcap\USBPcapCMD.exe'
$capture=$null
try {
    $capture=Start-Process -FilePath $usbpcap -ArgumentList @('-d','\\.\USBPcap3','-o',$Output,'--inject-descriptors','-A') -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 2
    if($capture.HasExited){throw "USBPcapCMD exited before capture readiness"}
    $ready.Set()|Out-Null
    $stop.WaitOne(180000)|Out-Null
} finally {
    if($capture -and -not $capture.HasExited){Stop-Process -Id $capture.Id -ErrorAction SilentlyContinue}
    if($capture){$capture.WaitForExit(5000)|Out-Null}
    $ready.Dispose();$stop.Dispose()
}
