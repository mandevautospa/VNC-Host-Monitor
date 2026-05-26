<#
.SYNOPSIS
    Launch the P3D Host Monitor GUI against local development config files.

.DESCRIPTION
    Starts the Tkinter GUI with config/central_config.dev.json and
    config/hosts.dev.json so the monitor can be tested safely from home.

.PARAMETER PythonPath
    Python executable to use. Defaults to 'python'.
#>

param(
    [string]$PythonPath = "python"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

& $PythonPath "src\gui\monitor_gui.py" "config\central_config.dev.json" "config\hosts.dev.json"
