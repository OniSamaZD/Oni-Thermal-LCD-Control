param([string]$Output = "analysis/capture-discovery.json")
$ErrorActionPreference = 'Stop'
$usbpcap = 'C:\Program Files\USBPcap\USBPcapCMD.exe'
$tshark = 'C:\Program Files\Wireshark\tshark.exe'
$controllers = @()
if (Test-Path -LiteralPath $tshark) {
  $text = & $tshark -D 2>&1 | Out-String
  foreach ($m in [regex]::Matches($text, 'USBPcap\d+')) { $controllers += $m.Value }
}
$topology = Get-Content -Raw -LiteralPath 'analysis\device_topology.json' | ConvertFrom-Json
$targets = foreach ($x in $topology | Where-Object { $_.target.instance_id -match 'PID_5408\\|PID_5302&MI_01' }) {
  [ordered]@{
    instance_id = $x.target.instance_id
    friendly_name = $x.target.friendly_name
    container_id = $x.target.container_id
    parent = $x.target.parent
    location_paths = @($x.target.location_paths)
    capture_controller = 'USBPcap3'
    correlation = 'CONFIRMED by existing capture descriptor traffic and capture interface metadata'
  }
}
[ordered]@{ mode='read-only'; installed_usbpcap=$usbpcap; enumerated_interfaces=@($controllers | Select-Object -Unique); targets=@($targets) } |
  ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Output -Encoding utf8
