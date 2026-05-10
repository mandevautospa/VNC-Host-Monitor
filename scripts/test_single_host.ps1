<#
.SYNOPSIS
    Quick connectivity test for a single P3D host — no Python required.

.DESCRIPTION
    Tests ping, VNC TCP port, and (optionally) reads the heartbeat file for
    a given host.  Useful for manual troubleshooting before or after a lab
    session.

.PARAMETER HostName
    Hostname or IP of the P3D host (e.g. host-03 or 192.168.1.13).

.PARAMETER VncPort
    VNC TCP port to test.  Default: 5900.

.PARAMETER HeartbeatPath
    Optional UNC or local path to the heartbeat JSON file.
    If omitted, the heartbeat check is skipped.

.EXAMPLE
    .\test_single_host.ps1 -HostName host-03
    .\test_single_host.ps1 -HostName host-03 -HeartbeatPath "\\CONFLAG\P3DHealth\host-03.json"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$HostName,

    [int]$VncPort = 5900,

    [string]$HeartbeatPath = ""
)

Write-Host ""
Write-Host "=== P3D Host Connectivity Test: $HostName ===" -ForegroundColor Cyan

# ── Ping ─────────────────────────────────────────────────────────────────────
Write-Host "`nPing..." -ForegroundColor Yellow
$ping = Test-NetConnection -ComputerName $HostName -WarningAction SilentlyContinue
if ($ping.PingSucceeded) {
    $ms = $ping.PingReplyDetails.RoundtripTime
    Write-Host "  PING OK  (latency: ${ms}ms)" -ForegroundColor Green
} else {
    Write-Host "  PING FAIL" -ForegroundColor Red
}

# ── VNC TCP port ──────────────────────────────────────────────────────────────
Write-Host "`nVNC TCP port $VncPort..." -ForegroundColor Yellow
$tcp = Test-NetConnection -ComputerName $HostName -Port $VncPort -WarningAction SilentlyContinue
if ($tcp.TcpTestSucceeded) {
    Write-Host "  VNC PORT OK" -ForegroundColor Green
} else {
    Write-Host "  VNC PORT FAIL" -ForegroundColor Red
}

# ── Heartbeat file ────────────────────────────────────────────────────────────
if ($HeartbeatPath -ne "") {
    Write-Host "`nHeartbeat: $HeartbeatPath" -ForegroundColor Yellow

    if (Test-Path $HeartbeatPath) {
        $file      = Get-Item $HeartbeatPath
        $ageSpan   = (Get-Date) - $file.LastWriteTime
        $ageSecs   = [math]::Round($ageSpan.TotalSeconds)

        if ($ageSecs -le 90) {
            Write-Host "  Age: ${ageSecs}s  (FRESH)" -ForegroundColor Green
        } else {
            Write-Host "  Age: ${ageSecs}s  (STALE — expected <= 90s)" -ForegroundColor Red
        }

        try {
            $content = Get-Content $HeartbeatPath -Raw | ConvertFrom-Json
            Write-Host "  Status      : $($content.status)"      -ForegroundColor Cyan
            Write-Host "  P3D running : $($content.p3d.running)" -ForegroundColor Cyan
            Write-Host "  CPU         : $($content.resources.cpu_percent)%" -ForegroundColor Cyan
            Write-Host "  RAM         : $($content.resources.ram_percent)%" -ForegroundColor Cyan
            Write-Host "  Disk free   : $($content.resources.disk_free_percent)%" -ForegroundColor Cyan
        }
        catch {
            Write-Host "  Could not parse heartbeat JSON: $_" -ForegroundColor Red
        }
    } else {
        Write-Host "  Heartbeat file NOT FOUND" -ForegroundColor Red
    }
}

Write-Host "`nDone." -ForegroundColor Cyan
