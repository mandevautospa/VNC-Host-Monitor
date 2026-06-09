<#
.SYNOPSIS
    Start the P3D ML data collector in a background PowerShell process.

.DESCRIPTION
    Launches tools/ml_data_collector.py using the system Python interpreter
    and redirects stdout/stderr to log files under analysis/ml_data/.
    The collector runs until explicitly stopped; use Stop-Process on the
    returned job or close the spawned window.

.PARAMETER HostName
    Host identifier written to the CSV (e.g. host-01).

.PARAMETER MissionName
    Current mission name written to the CSV (e.g. "Test Mission").

.PARAMETER Interval
    Sample interval in seconds (default: 5).

.PARAMETER OutDir
    Output directory for CSV and log files (default: analysis/ml_data).

.EXAMPLE
    .\tools\start_ml_collector.ps1 -HostName host-01 -MissionName "Test Mission"

.EXAMPLE
    .\tools\start_ml_collector.ps1 -HostName host-02 -MissionName "Training Run" -Interval 10
#>

[CmdletBinding()]
param (
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [Parameter(Mandatory = $false)]
    [string]$MissionName = "",

    [Parameter(Mandatory = $false)]
    [int]$Interval = 5,

    [Parameter(Mandatory = $false)]
    [string]$OutDir = "analysis/ml_data"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Resolve paths relative to the repository root (parent of the tools folder)
# ---------------------------------------------------------------------------
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot   = Split-Path -Parent $ScriptDir
$CollectorScript = Join-Path $RepoRoot "tools\ml_data_collector.py"
$OutDirFull      = Join-Path $RepoRoot $OutDir

# Ensure the output directory exists before launching
New-Item -ItemType Directory -Force -Path $OutDirFull | Out-Null

$StdoutLog = Join-Path $OutDirFull "ml_collector_stdout.log"
$StderrLog = Join-Path $OutDirFull "ml_collector_stderr.log"

# ---------------------------------------------------------------------------
# Build the python command
# ---------------------------------------------------------------------------
$PythonArgs = @(
    "`"$CollectorScript`"",
    "--host",   "`"$HostName`"",
    "--mission", "`"$MissionName`"",
    "--interval", $Interval,
    "--out",    "`"$OutDirFull`""
)

$PythonCmd = "python $($PythonArgs -join ' ')"

Write-Host ""
Write-Host "=== P3D ML Data Collector Launcher ===" -ForegroundColor Cyan
Write-Host "Host      : $HostName"
Write-Host "Mission   : $MissionName"
Write-Host "Interval  : ${Interval}s"
Write-Host "Output dir: $OutDirFull"
Write-Host "Stdout log: $StdoutLog"
Write-Host "Stderr log: $StderrLog"
Write-Host ""

# ---------------------------------------------------------------------------
# Launch as a detached background process
# ---------------------------------------------------------------------------
$ProcessArgs = @{
    FilePath         = "powershell"
    ArgumentList     = @(
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle", "Hidden",
        "-Command",
        "& { $PythonCmd } 1>`"$StdoutLog`" 2>`"$StderrLog`""
    )
    WindowStyle      = "Hidden"
    PassThru         = $true
}

$job = Start-Process @ProcessArgs

Write-Host "Collector started in background (PID: $($job.Id))." -ForegroundColor Green
Write-Host "To stop it, run:  Stop-Process -Id $($job.Id)"
Write-Host ""
Write-Host "Tail live stdout:  Get-Content -Wait `"$StdoutLog`""
Write-Host "Tail live stderr:  Get-Content -Wait `"$StderrLog`""
Write-Host ""
