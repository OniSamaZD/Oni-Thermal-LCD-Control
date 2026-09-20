$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$capture=Join-Path $root "captures\originals\live_5302_hid_captured_$stamp.pcapng"
$result=Join-Path $root "analysis\live-5302-hid-result-$stamp.json"
$stdout="$capture.stdout.log";$stderr="$capture.stderr.log"
$tshark='C:\Program Files\Wireshark\tshark.exe'
if(-not(Test-Path -LiteralPath $tshark)){throw 'tshark not found'}
# Fixed duration makes tshark own the USBPcap extcap lifecycle and guarantees
# a normal flush/close after the 15-second post-frame hold and handle release.
# USBPcap3 is retained as required. A read-only controller map made during
# recorder validation placed the current HID MI_00 path on USBPcap4, so the
# same PCAPNG also records USBPcap4. This is passive capture only.
$cap=Start-Process -FilePath $tshark -ArgumentList @('-i','USBPcap3','-i','USBPcap4','-a','duration:35','-w',$capture) -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -WindowStyle Hidden
try{
    Start-Sleep -Seconds 2
    if($cap.HasExited){throw "tshark/USBPcap exited before replay: $($cap.ExitCode)"}
    $env:PYTHONPATH=Join-Path $root 'src'
    'SEND PID 5302 CAPTURED FRAME' | & python -m thermalright_lcd replay `
      (Join-Path $root 'analysis\pid5302-same-session-first-frame.json') `
      --session-file (Join-Path $root 'analysis\session-report.json') `
      --transaction 1 `
      --device 'USB\VID_0416&PID_5302\USBDISPLAY' `
      --sequence '0416:5302/pid5302-same-session-first-frame-transaction-1' `
      --hold-open-seconds 15 --send --i-understand-live-usb 2>&1 | Tee-Object -FilePath $result
    $replayExit=$LASTEXITCODE
    if(-not $cap.WaitForExit(40000)){throw 'tshark did not complete its clean duration stop'}
    $cap.Refresh();$captureExit=$cap.ExitCode
    if($null-ne$captureExit-and$captureExit-ne 0){throw "tshark capture failed: $captureExit"}
    if(-not(Test-Path -LiteralPath $capture)-or(Get-Item -LiteralPath $capture).Length-le 24){throw 'tshark produced no capture data'}
}finally{
    if(-not $cap.HasExited){Stop-Process -Id $cap.Id -ErrorAction SilentlyContinue;$cap.WaitForExit(5000)|Out-Null}
}
Write-Output "CAPTURE=$capture"
Write-Output "RESULT=$result"
exit $replayExit
