#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Registers the P3D host watchdog as a Windows Scheduled Task.

.DESCRIPTION
    Run this script ONCE on each P3D host after deploying the watchdog files.
    It creates a task that starts at system boot and restarts automatically if
    the Python process exits unexpectedly.

    The task runs the watchdog in a continuous loop (sleep is inside the
    Python script itself), so no repeat trigger is needed.

.PARAMETER WatchdogScript
    Full path to host_watchdog.py on this host.
    Default: C:\P3DWatchdog\src\host_agent\host_watchdog.py

.PARAMETER ConfigPath
    Full path to the host config JSON file.
    Default: C:\P3DWatchdog\config.json

.PARAMETER PythonPath
    Full path to python.exe. Example: C:\Python311\python.exe

.PARAMETER TaskUser
    Explicit account to run the scheduled task (e.g. DOMAIN\svc-watchdog or MACHINE\svc-watchdog).

.PARAMETER StartNow
    If set, starts the task immediately after registration.

.EXAMPLE
    .\install_host_task.ps1 -PythonPath "C:\Python311\python.exe"
#>

param(
    [string]$WatchdogScript = "C:\P3DWatchdog\src\host_agent\host_watchdog.py",
    [string]$ConfigPath     = "C:\P3DWatchdog\config.json",
    [Parameter(Mandatory = $true)]
    [string]$PythonPath,
    [Parameter(Mandatory = $true)]
    [string]$TaskUser,
    [switch]$StartNow
)

if (-not (Test-Path $PythonPath)) {
    throw "PythonPath does not exist: $PythonPath"
}

if (-not ([System.IO.Path]::IsPathRooted($PythonPath))) {
    throw "PythonPath must be a full absolute path to python.exe"
}

if (-not (Test-Path $WatchdogScript)) {
    throw "WatchdogScript does not exist: $WatchdogScript"
}

if (-not (Test-Path $ConfigPath)) {
    throw "ConfigPath does not exist: $ConfigPath"
}

$TaskName        = "P3DHostWatchdog"
$TaskDescription = "P3D Host Watchdog — monitors Prepar3D health and writes heartbeat JSON."
$WorkingDir      = Split-Path $WatchdogScript

$action = New-ScheduledTaskAction `
    -Execute   $PythonPath `
    -Argument  "`"$WatchdogScript`" `"$ConfigPath`"" `
    -WorkingDirectory $WorkingDir

# Start at boot; the Python loop handles the 30-second interval internally
$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit   (New-TimeSpan -Hours 0) `
    -RestartCount         5 `
    -RestartInterval      (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

$principal = New-ScheduledTaskPrincipal `
    -UserId $TaskUser `
    -LogonType ServiceAccount `
    -RunLevel Limited

try {
    Register-ScheduledTask `
        -TaskName    $TaskName `
        -Description $TaskDescription `
        -Action      $action `
        -Trigger     $trigger `
        -Settings    $settings `
        -Principal   $principal `
        -Force | Out-Null

    Write-Host "Task '$TaskName' registered successfully." -ForegroundColor Green
}
catch {
    Write-Host "Failed to register task: $_" -ForegroundColor Red
    exit 1
}

if ($StartNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "Task started." -ForegroundColor Green
}
