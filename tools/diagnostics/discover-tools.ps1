param([string]$Output = "analysis/tool_inventory.json")
$paths = @(
  'C:\Program Files\Wireshark\Wireshark.exe',
  'C:\Program Files\Wireshark\tshark.exe',
  'C:\Program Files\Wireshark\capinfos.exe',
  'C:\Program Files\USBPcap\USBPcapCMD.exe',
  'C:\Program Files\Wireshark\extcap\USBPcapCMD.exe'
)
$found = foreach ($path in $paths) {
  if (Test-Path -LiteralPath $path) {
    $item = Get-Item -LiteralPath $path
    [ordered]@{ path=$path; version=$item.VersionInfo.FileVersion; sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant() }
  }
}
$vendor = foreach ($root in @(
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
)) {
  Get-ItemProperty $root -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -match 'Thermalright|TRCC|Control Center' } |
    Select-Object @{n='Name';e={$_.DisplayName}}, @{n='Version';e={$_.DisplayVersion}}, InstallLocation, DisplayIcon
}
[ordered]@{ tools=@($found); vendor_products=@($vendor) } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Output -Encoding utf8
