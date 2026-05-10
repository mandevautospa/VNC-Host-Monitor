#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Registers the P3D central monitor as a Windows Scheduled Task.

.DESCRIPTION
    Run this script ONCE on the central monitor / technician PC.
    It creates a task that starts at system boot and restarts automatically
    if the Python process exits unexpectedly.

.PARAMETER MonitorScript
    Full path to central_monitor.py on the monitor PC.
    Default: C:\P3DMonitor\src\central_monitor\central_monitor.py

.PARAMETER ConfigPath
    Full path to central_config.json.
    Default: C:\P3DMonitor\config\central_config.json

.PARAMETER HostsPath
    Full path to hosts.json.
    Default: C:\P3DMonitor\config\hosts.json

.PARAMETER PythonPath
    Full path to python.exe. Example: C:\Python311\python.exe

.PARAMETER TaskUser
    Explicit account to run the scheduled task (e.g. DOMAIN\svc-monitor or MACHINE\svc-monitor).

.PARAMETER StartNow
    If set, starts the task immediately after registration.

.EXAMPLE
    .\install_central_task.ps1 -PythonPath "C:\Python311\python.exe"
#>

param(
    [string]$MonitorScript = "C:\P3DMonitor\src\central_monitor\central_monitor.py",
    [string]$ConfigPath    = "C:\P3DMonitor\config\central_config.json",
    [string]$HostsPath     = "C:\P3DMonitor\config\hosts.json",
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

if (-not (Test-Path $MonitorScript)) {
    throw "MonitorScript does not exist: $MonitorScript"
}

if (-not (Test-Path $ConfigPath)) {
    throw "ConfigPath does not exist: $ConfigPath"
}

if (-not (Test-Path $HostsPath)) {
    throw "HostsPath does not exist: $HostsPath"
}

$TaskName        = "P3DCentralMonitor"
$TaskDescription = "P3D Central Monitor — checks ping, VNC, heartbeat, and logs host health."
$WorkingDir      = Split-Path $MonitorScript

$action = New-ScheduledTaskAction `
    -Execute   $PythonPath `
    -Argument  "`"$MonitorScript`" `"$ConfigPath`" `"$HostsPath`"" `
    -WorkingDirectory $WorkingDir

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount       5 `
    -RestartInterval    (New-TimeSpan -Minutes 1) `
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
