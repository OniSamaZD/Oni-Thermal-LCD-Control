$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$stamp=Get-Date -Format 'yyyyMMdd_HHmmss'
$capture=Join-Path $root "captures\originals\live_dual_generated_$stamp.pcapng"
$result=Join-Path $root "analysis\live-dual-generated-result-$stamp.json"
$tshark='C:\Program Files\Wireshark\tshark.exe'
if(-not(Test-Path -LiteralPath $tshark)){throw 'tshark not found'}
$cap=Start-Process -FilePath $tshark -ArgumentList @('-i','USBPcap3','-i','USBPcap4','-a','duration:50','-w',$capture) -RedirectStandardOutput "$capture.stdout.log" -RedirectStandardError "$capture.stderr.log" -PassThru -WindowStyle Hidden
try{
    Start-Sleep -Seconds 2
    if($cap.HasExited){throw "tshark/USBPcap exited before dual generated replay: $($cap.ExitCode)"}
    $env:PYTHONPATH=Join-Path $root 'src'
    'SEND BOTH GENERATED FRAMES FOR 30 SECONDS' | & py -3.12 -m thermalright_lcd dual-generated-live `
      --session-file (Join-Path $root 'analysis\session-report.json') `
      --pid5302-transaction (Join-Path $root 'analysis\pid5302-dual-generated-test.json') `
      --pid5408-transaction (Join-Path $root 'analysis\pid5408-dual-generated-test.json') `
      --duration 30 --send --i-understand-live-usb 2>&1 | Tee-Object -FilePath $result
    $replayExit=$LASTEXITCODE
    if(-not $cap.WaitForExit(55000)){throw 'tshark did not complete its clean duration stop'}
    $cap.Refresh()
    if($null-ne$cap.ExitCode-and$cap.ExitCode-ne 0){throw "tshark capture failed: $($cap.ExitCode)"}
    if(-not(Test-Path -LiteralPath $capture)-or(Get-Item -LiteralPath $capture).Length-le 24){throw 'tshark produced no capture data'}
}finally{
    if(-not $cap.HasExited){Stop-Process -Id $cap.Id -ErrorAction SilentlyContinue;$cap.WaitForExit(5000)|Out-Null}
}
Write-Output "CAPTURE=$capture"
Write-Output "RESULT=$result"
exit $replayExit
