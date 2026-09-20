param([string]$OutputDirectory = "analysis")
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$entities = @(Get-CimInstance Win32_PnPEntity | Where-Object { $_.PNPDeviceID -match '^(USB|HID)\\' })
$rows = foreach ($d in $entities) {
  [ordered]@{ class=$d.PNPClass; friendly_name=$d.Name; instance_id=$d.PNPDeviceID; status=$d.Status; manufacturer=$d.Manufacturer; service=$d.Service; hardware_ids=@($d.HardwareID); compatible_ids=@($d.CompatibleID); device_id=$d.DeviceID }
}
$rows | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'device_inventory.json') -Encoding utf8
function TargetProperties($id) {
  $props = Get-PnpDeviceProperty -InstanceId $id -ErrorAction SilentlyContinue
  $wanted = @('DEVPKEY_Device_ContainerId','DEVPKEY_Device_Parent','DEVPKEY_Device_LocationPaths','DEVPKEY_Device_LocationInfo','DEVPKEY_Device_BusReportedDeviceDesc','DEVPKEY_Device_DriverVersion')
  $result = [ordered]@{}
  foreach ($key in $wanted) { $result[$key] = @($props | Where-Object KeyName -eq $key | Select-Object -ExpandProperty Data) }
  $result
}
$targets = foreach ($r in $rows | Where-Object { $_.instance_id -match 'VID_0416&PID_(5302|5408)' }) { [ordered]@{ device=$r; properties=(TargetProperties $r.instance_id) } }
$targets | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'device_topology.json') -Encoding utf8
