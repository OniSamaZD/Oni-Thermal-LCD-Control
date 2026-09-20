[CmdletBinding()]
param(
    [string]$PyInstallerExe = "dist\Oni Thermal LCD Control.exe",
    [string]$NuitkaExe = "dist-nuitka\Oni Thermal LCD Control.exe",
    [int]$Runs = 5
)

$ErrorActionPreference = "Stop"
$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Python = "py"
$Script = Join-Path $PSScriptRoot "benchmark_executable.py"
$Output = Join-Path $RepoRoot "analysis\packaging-benchmark.json"
$Candidates = @()
foreach ($Item in @(@("pyinstaller", $PyInstallerExe), @("nuitka", $NuitkaExe))) {
    $Resolved = [IO.Path]::GetFullPath((Join-Path $RepoRoot $Item[1]))
    if (Test-Path -LiteralPath $Resolved) {
        $Candidates += @("--candidate", ("{0}={1}" -f $Item[0], $Resolved))
    }
}
if ($Candidates.Count -eq 0) { throw "No packaged executable was found to benchmark" }

& $Python -3.12 $Script --runs $Runs --output $Output @Candidates
if ($LASTEXITCODE -ne 0) { throw "Packaging benchmark failed" }
Write-Host "Benchmark: $Output"
