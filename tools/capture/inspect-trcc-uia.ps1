param([string]$Output = "analysis/trcc-uia-tree.json")
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$proc = Get-Process TRCC -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $proc) { throw 'TRCC is not running; inspection intentionally does not launch it.' }
$root = [System.Windows.Automation.AutomationElement]::FromHandle($proc.MainWindowHandle)
if (-not $root -or $root.Current.ProcessId -ne $proc.Id) { throw 'Target window identity verification failed.' }
$condition = [System.Windows.Automation.Condition]::TrueCondition
$nodes = foreach ($e in $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)) {
  [ordered]@{ name=$e.Current.Name; automation_id=$e.Current.AutomationId; control_type=$e.Current.ControlType.ProgrammaticName; class_name=$e.Current.ClassName; process_id=$e.Current.ProcessId; enabled=$e.Current.IsEnabled }
}
[ordered]@{ mode='semantic-read-only-inspection'; process_id=$proc.Id; executable=$proc.Path; window_title=$root.Current.Name; controls=@($nodes) } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Output -Encoding utf8
