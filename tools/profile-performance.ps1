param(
    [double]$Duration = 5,
    [double]$Interval = 0.25,
    [string]$Output = "analysis/performance-profile.json"
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot "src"
& python -m thermalright_lcd.performance --duration $Duration --interval $Interval --output (Join-Path $projectRoot $Output)
if ($LASTEXITCODE -ne 0) { throw "Performance profiler failed with exit code $LASTEXITCODE" }
