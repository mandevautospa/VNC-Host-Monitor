# P3D Host Watchdog - Technical Developer Sheet

## 1. Project Goal
Build a Windows monitoring-only MVP for six Prepar3D hosts to detect problems early and notify the Hanger Bay staff or ADP.

Monitor:
- Host reachability
- TightVNC availability
- Prepar3D process health
- Windows crash/hang events
- CPU/RAM/disk usage
- Heartbeat freshness
- Alert/recovery state

MVP behavior:
- Detect -> Log -> Alert -> Technician investigates
- No reboot/restart/kill actions

## 2. Architecture
- CONFLAG = central monitor machine
- Host watchdog = local script on each host
- Shared heartbeat folder = host JSON writes, central JSON reads

Central monitor responsibilities:
- Ping check
- VNC TCP port 5900 check
- VNC RFB banner check
- Heartbeat freshness check
- Status evaluation and failure counters
- Alerts and recovery notices
- Central logging and console dashboard

Host watchdog responsibilities:
- Check Prepar3D.exe process
- Check TightVNC service (tvnserver)
- Check CPU/RAM/disk
- Query recent Windows event logs
- Write heartbeat JSON every 30 seconds
- Write local log

## 3. Required Project Structure
- config/
  - central_config.example.json
  - hosts.example.json
  - host_watchdog_config.example.json
- src/common/
- src/central_monitor/
- src/host_agent/
- src/dashboard/
- scripts/
- tests/
- logs/

## 4. Setup by Machine

### 4.1 CONFLAG (central monitor machine)
1. Deploy repo to C:\P3DMonitor\
2. Install Python 3.11+
3. Install dependencies
4. Create/share heartbeat folder (example C:\P3DHealth\ as share P3DHealth)
5. Grant host identities read/write share access
6. Create real central config files
7. Register central scheduled task

Commands:

```powershell
cd C:\P3DMonitor
python -m pip install -r requirements.txt

.\scripts\install_central_task.ps1 `
  -PythonPath    "C:\Python311\python.exe" `
  -TaskUser      "DOMAIN\\svc-monitor" `
  -MonitorScript "C:\P3DMonitor\src\central_monitor\central_monitor.py" `
  -ConfigPath    "C:\P3DMonitor\config\central_config.json" `
  -HostsPath     "C:\P3DMonitor\config\hosts.json"
```

### 4.2 Each P3D host (host-01 to host-06)
1. Deploy repo to C:\P3DWatchdog\
2. Install Python 3.11+
3. Install dependencies
4. Create host-specific C:\P3DWatchdog\config.json
5. Verify write access to \\CONFLAG\P3DHealth\
6. Register host scheduled task

Commands:

```powershell
cd C:\P3DWatchdog
python -m pip install -r requirements.txt

.\scripts\install_host_task.ps1 `
  -PythonPath     "C:\Python311\python.exe" `
  -TaskUser       "DOMAIN\\svc-watchdog" `
  -WatchdogScript "C:\P3DWatchdog\src\host_agent\host_watchdog.py" `
  -ConfigPath     "C:\P3DWatchdog\config.json"
```

Write-access check:

```powershell
New-Item "\\CONFLAG\P3DHealth\write-test.txt" -ItemType File
Remove-Item "\\CONFLAG\P3DHealth\write-test.txt"
```

## 5. Config Requirements

### 5.1 hosts.json (central)
Each host entry must include:
- name
- address
- vnc_port (default 5900)
- heartbeat_path (for example \\CONFLAG\P3DHealth\host-01.json)

### 5.2 central_config.json
Required keys:
- check_interval_seconds
- heartbeat_stale_seconds
- alert_after_failures
- critical_alert_after_failures
- active_hours
- alerts
- log_path

Recommended defaults:
- check_interval_seconds: 30
- heartbeat_stale_seconds: 90
- alert_after_failures: 3
- critical_alert_after_failures: 2

### 5.3 host config.json
Required keys:
- host_name
- p3d_process_name (Prepar3D.exe)
- tightvnc_service_name (tvnserver)
- heartbeat_output_path
- local_log_path
- check_interval_seconds
- event_lookback_minutes
- thresholds block

Recommended defaults:
- check_interval_seconds: 30
- event_lookback_minutes: 10

Threshold defaults:
- cpu_warning_percent: 85
- cpu_critical_percent: 95
- ram_warning_percent: 85
- ram_critical_percent: 92
- disk_warning_free_percent: 20
- disk_critical_free_percent: 10
- disk_warning_free_gb: 20
- disk_critical_free_gb: 10

## 6. Functional Requirements (Core)
- Central supports configurable host inventory
- Central ping check returns ping_ok, latency/error
- Central VNC TCP check returns vnc_port_ok/error
- Central banner check expects prefix RFB
- Host checks P3D process running + CPU + memory
- Host checks TightVNC service running
- Host checks CPU/RAM/disk resources
- Host checks recent event logs (1000, 1001, 1002 + display-related errors)
- Host writes heartbeat every 30 seconds
- Central marks heartbeat stale if older than 90 seconds
- Central classifies final state by priority
- Central uses failure counters to reduce false positives
- Central sends recovery only when unhealthy -> healthy transition occurs
- Both components log all checks/results/errors

## 7. Data Contracts

### 7.1 Heartbeat JSON (host output)
Must include:
- schema_version
- host
- timestamp
- watchdog_version
- status
- p3d
- tightvnc
- resources
- events
- errors

### 7.2 Central merged result (in-memory per host)
Must include:
- host
- timestamp
- network block
- heartbeat block
- host_reported block
- final_status
- failure_count
- should_alert

## 8. Status Priority (Central)
Apply in order:
1. HOST_UNREACHABLE
2. HEARTBEAT_STALE
3. VNC_DOWN
4. P3D_CRASH_DETECTED
5. P3D_NOT_RUNNING
6. P3D_HANG_SUSPECTED
7. RESOURCE_CRITICAL
8. RESOURCE_WARNING
9. WARNING
10. HEALTHY

## 9. Alert Rules
- Normal unhealthy status alerts after 3 consecutive failures
- Critical statuses can alert after 2 failures
- Recovery alert when previous status unhealthy and current status HEALTHY
- Keep monitoring and logging even if alert transport fails
- Avoid repeat alert spam for same unresolved incident

## 10. Safety and Operational Constraints
Must not:
- Auto-reboot hosts
- Auto-restart P3D
- Auto-restart TightVNC
- Kill processes
- Interrupt active flight sessions
- Store credentials in source
- Expose monitor/share/VNC externally

Must:
- Continue monitoring other hosts if one host fails
- Handle missing/malformed heartbeat files gracefully
- Keep logs useful for post-incident review

## 11. Validation and Testing
Unit tests should cover:
- Threshold evaluation
- State priority evaluation
- Heartbeat stale detection
- Malformed heartbeat handling
- VNC banner parsing
- Alert suppression/recovery behavior

Manual checks:
- Disconnect one host
- Stop TightVNC
- Close Prepar3D.exe
- Age heartbeat file beyond threshold
- Corrupt heartbeat JSON
- Restore host and verify recovery behavior

Quick command (from CONFLAG):

```powershell
cd C:\P3DMonitor
.\scripts\test_single_host.ps1 -HostName host-03 -HeartbeatPath "\\CONFLAG\P3DHealth\host-03.json"
```

Expected:
- Ping OK
- VNC 5900 OK

## 17. Running Central Monitor Frontends

### 17.1 Console Dashboard (existing behavior)

Run from repo root with external config paths:

```powershell
python src\central_monitor\central_monitor.py config\central_config.json config\hosts.json
```

Optional host picker before launch:

```powershell
python src\central_monitor\central_monitor.py --gui config\central_config.json config\hosts.json
```

### 17.2 Tkinter GUI

Run from repo root:

```powershell
python src\gui\monitor_gui.py config\central_config.json config\hosts.json
```

Behavior:
- A config selector window appears first.
- The host selector appears after config files are confirmed.
- Startup host selection uses the same selector as console mode.
- Monitoring runs on a background thread.
- UI updates are delivered through a thread-safe queue and Tkinter `after()` loop.
- Config files remain external and editable at runtime.

### 17.3 Local Dev Mode

Use the dev configs when working from home or when the real lab network is unavailable:

```powershell
python src\gui\monitor_gui.py config\central_config.dev.json config\hosts.dev.json
```

Or launch the helper script:

```powershell
.\scripts\run_gui_dev.ps1
```

The dev configs are intentionally separate from the production config files and only use local placeholder values.

### 17.4 Example Files

The `*.example.json` files are templates for creating real configs. They are not intended to be used as live runtime configs unless you are intentionally testing against them.

### 17.5 Startup Flow

When the GUI or packaged executable starts, it:

1. Opens the config selector.
2. Loads the selected central and hosts config files.
3. Opens the host selector.
4. Starts the main dashboard with the chosen hosts.

## 18. Packaging GUI with PyInstaller

Install dev tooling:

```powershell
python -m pip install -r requirements-dev.txt
```

Build one-file executable from repo root:

```powershell
pyinstaller --noconfirm --onefile --name P3DMonitorGUI src\gui\monitor_gui.py
```

Build output:
- Executable: `dist\P3DMonitorGUI.exe`

Deployment notes:
- Keep `config\central_config.json` and `config\hosts.json` outside the executable so they remain editable.
- Pass explicit config paths when launching packaged app:

```powershell
dist\P3DMonitorGUI.exe C:\P3DMonitor\config\central_config.json C:\P3DMonitor\config\hosts.json
```

## 19. Home / Dev Testing

This workflow lets you validate the GUI, heartbeat parsing, stale detection, failure counts, and resource state handling without access to CONFLAG or the lab hosts.

### 19.1 Start the fake heartbeat writer

In one terminal:

```powershell
python scripts\write_fake_heartbeat.py --output dev_health\host-01.json --interval 10
```

### 19.2 Start the GUI in dev mode

In a second terminal:

```powershell
.\scripts\run_gui_dev.ps1
```

### 19.3 Verify a fresh heartbeat

- Confirm `host-01` shows a fresh heartbeat in the GUI.
- The fake-offline host should begin failing ping/VNC and eventually show `HOST_UNREACHABLE` after the configured failure count.

### 19.4 Test stale heartbeat handling

- Stop the fake heartbeat writer with Ctrl+C.
- Wait longer than `heartbeat_stale_seconds` in `config/central_config.dev.json`.
- Restart or refresh the GUI and confirm the heartbeat becomes `STALE`.

### 19.5 Test P3D state and resource states

Write a one-shot heartbeat with alternate values:

```powershell
python scripts\write_fake_heartbeat.py --once --output dev_health\host-01.json --p3d-running false
python scripts\write_fake_heartbeat.py --once --output dev_health\host-01.json --cpu-percent 96
python scripts\write_fake_heartbeat.py --once --output dev_health\host-01.json --disk-free-percent 8 --disk-free-gb 5
```

Use those values to confirm the GUI and central logic show `P3D_NOT_RUNNING`, `RESOURCE_WARNING`, or `RESOURCE_CRITICAL` as expected.

### 19.6 Re-test packaging later at work

- Build the executable with PyInstaller after pulling the latest source.
- Run the packaged GUI against real `config\central_config.json` and `config\hosts.json` on CONFLAG.
- Keep the dev files separate so home testing never touches production configs.

```powershell
P3DMonitorGUI.exe C:\P3DMonitor\config\central_config.json C:\P3DMonitor\config\hosts.json
```
- Heartbeat fresh (<= 90 seconds)

## 12. MVP Definition of Done
MVP is complete when:
- Central checks all six hosts continuously
- Each host writes heartbeat every 30 seconds
- Central detects ping, VNC, heartbeat stale, and P3D-not-running failures
- Status changes and check results are logged
- Failure counters suppress one-off transient failures
- Recovery notifications work
- No automated reboot/restart exists in code path

---

## 13. Service Account Permissions

### Central Monitor Service Account (svc-monitor)
**Required permissions:**

1. **Scheduled Task execution:**
   - Run the central_monitor.py script on CONFLAG every 30 seconds
   - Log off after each run

2. **File system:**
   - Read: `C:\P3DMonitor\config\` (configs, hosts.json, central_config.json)
   - Write: `C:\P3DMonitor\logs\` (rotating log files)

3. **Network share read:**
   - Read heartbeat JSON files from `\\CONFLAG\P3DHealth\*`

4. **Network access:**
   - Outbound TCP:5900 (VNC to all hosts)
   - ICMP ping to all host addresses

**Create in Active Directory:**
```powershell
$params = @{
    Name                   = "svc-monitor"
    AccountPassword        = (ConvertTo-SecureString "PASSWORD_PLACEHOLDER" -AsPlainText -Force)
    PasswordNeverExpires   = $false
    Enabled                = $true
    CannotChangePassword   = $false
    Description            = "Service account for P3D central monitor on CONFLAG"
}
New-ADUser @params
```

**Assign logon right (Group Policy):**
- Computer Configuration → Windows Settings → Security Settings → Local Policies → User Rights Assignment
- Add `svc-monitor` to "Log on as a batch job"

---

## 14. Shared Folder Permissions: \\CONFLAG\P3DHealth

### Share Setup
1. **Create directory:**
   ```powershell
   New-Item -Path "C:\P3DHealth" -ItemType Directory -Force
   ```

2. **Create network share:**
   ```powershell
   New-SmbShare -Name "P3DHealth" -Path "C:\P3DHealth" -Description "P3D Heartbeat Share" `
     -ChangeAccess "DOMAIN\svc-monitor","DOMAIN\svc-watchdog" `
     -FullAccess   "DOMAIN\Domain Admins"
   ```

3. **NTFS permissions (on C:\P3DHealth):**

   | Identity | Permissions | Type |
   |----------|------------|------|
   | `DOMAIN\svc-monitor` | Read, Write | Allow |
   | `DOMAIN\svc-watchdog` | Read, Write | Allow |
   | `DOMAIN\Domain Admins` | Full Control | Allow |
   | `SYSTEM` | Full Control | Allow |
   | `Authenticated Users` | Remove | Deny |

4. **Set permissions via PowerShell:**
   ```powershell
   $path = "C:\P3DHealth"
   $acl = Get-Acl $path
   
   # Add svc-monitor
   $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
       "DOMAIN\svc-monitor",
       [System.Security.AccessControl.FileSystemRights]::Modify,
       [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit,
       [System.Security.AccessControl.PropagationFlags]::None,
       [System.Security.AccessControl.AccessControlType]::Allow
   )
   $acl.AddAccessRule($rule)
   
   # Add svc-watchdog (same permissions)
   $rule2 = New-Object System.Security.AccessControl.FileSystemAccessRule(
       "DOMAIN\svc-watchdog",
       [System.Security.AccessControl.FileSystemRights]::Modify,
       [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit,
       [System.Security.AccessControl.PropagationFlags]::None,
       [System.Security.AccessControl.AccessControlType]::Allow
   )
   $acl.AddAccessRule($rule2)
   
   Set-Acl -Path $path -AclObject $acl
   ```

5. **Verify heartbeat file permissions:**
   - Each heartbeat JSON file (e.g., `host-01.json`) should be readable/writable by both service accounts
   - Cleanup old files: keep only the most recent heartbeat per host

---

## 15. Uninstall & Rollback Procedures

### Scenario A: Rollback Central Monitor (CONFLAG)

1. **Stop the scheduled task:**
   ```powershell
   Disable-ScheduledTask -TaskName "P3D-Central-Monitor"
   ```

2. **Unregister the task:**
   ```powershell
   Unregister-ScheduledTask -TaskName "P3D-Central-Monitor" -Confirm:$false
   ```

3. **Archive logs & configs (for post-incident review):**
   ```powershell
   Compress-Archive -Path "C:\P3DMonitor\logs\*" -DestinationPath "C:\Archive\P3DMonitor-$(Get-Date -Format 'yyyyMMdd-HHmmss').zip"
   ```

4. **Remove repository (optional):**
   ```powershell
   Remove-Item -Path "C:\P3DMonitor" -Recurse -Force
   ```

### Scenario B: Rollback Host Watchdog (Each P3D Host)

1. **Stop the scheduled task:**
   ```powershell
   Disable-ScheduledTask -TaskName "P3D-Host-Watchdog"
   ```

2. **Unregister the task:**
   ```powershell
   Unregister-ScheduledTask -TaskName "P3D-Host-Watchdog" -Confirm:$false
   ```

3. **Archive logs for review:**
   ```powershell
   Compress-Archive -Path "C:\P3DWatchdog\logs\*" -DestinationPath "C:\Archive\P3DWatchdog-$(Get-Date -Format 'yyyyMMdd-HHmmss').zip"
   ```

4. **Remove repository:**
   ```powershell
   Remove-Item -Path "C:\P3DWatchdog" -Recurse -Force
   ```

### Scenario C: Clean up heartbeat share

1. **Clear old heartbeat files:**
   ```powershell
   Remove-Item -Path "C:\P3DHealth\*.json" -Force
   ```

2. **To fully remove share:**
   ```powershell
   Remove-SmbShare -Name "P3DHealth" -Force
   Remove-Item -Path "C:\P3DHealth" -Recurse -Force
   ```

### Verification After Rollback
- Confirm scheduled tasks are gone: `Get-ScheduledTask | findstr P3D` (should return empty)
- Confirm log dirs removed or archived
- Confirm share is inaccessible: `net view \\CONFLAG | findstr P3DHealth` (should return not found)
- Manual check of each host: ensure no Python processes lingering (`Get-Process python -ErrorAction SilentlyContinue`)

---

## 16. One-Host Pilot Deployment Plan

### Phase 1: Single-Host Validation (2–3 days)
**Objective:** Verify core monitoring and alert workflows before six-host rollout.

**Host:** `host-01` (designated pilot)

**Steps:**

1. **Deploy Python + dependencies on host-01:**
   ```powershell
   # SSH/RDP into host-01
   cd C:\
   python -m pip install -r C:\P3DWatchdog\requirements.txt
   ```

2. **Create host-01 config:**
   ```json
   {
     "host_name": "host-01",
     "p3d_process_name": "Prepar3D.exe",
     "tightvnc_service_name": "tvnserver",
     "heartbeat_output_path": "\\\\CONFLAG\\P3DHealth\\host-01.json",
     "local_log_path": "C:\\P3DWatchdog\\logs\\host_watchdog.log",
     "disk_path": "C:\\",
     "check_interval_seconds": 30,
     "event_lookback_minutes": 10,
     "thresholds": {
       "cpu_warning_percent": 85,
       "cpu_critical_percent": 95,
       "ram_warning_percent": 85,
       "ram_critical_percent": 92,
       "disk_warning_free_percent": 20,
       "disk_critical_free_percent": 10,
       "disk_warning_free_gb": 20,
       "disk_critical_free_gb": 10
     }
   }
   ```

3. **Register scheduled task on host-01:**
   ```powershell
   .\scripts\install_host_task.ps1 `
     -PythonPath    "C:\Python311\python.exe" `
     -TaskUser      "DOMAIN\\svc-watchdog" `
     -WatchdogScript "C:\P3DWatchdog\src\host_agent\host_watchdog.py" `
     -ConfigPath    "C:\P3DWatchdog\config.json"
   ```

4. **Monitor heartbeat on CONFLAG (30 seconds × 2):**
   ```powershell
   Get-ChildItem "\\CONFLAG\P3DHealth\host-01.json" -Force
   Get-Content "\\CONFLAG\P3DHealth\host-01.json" | ConvertFrom-Json
   ```

   **Expected:** Fresh JSON file with status: `HEALTHY`

5. **Deploy central monitor (CONFLAG):**
   ```powershell
   cd C:\P3DMonitor
   python -m pip install -r requirements.txt

   # Create central_config.json with require_heartbeat: false (allow grace period)
   # Create hosts.json with only host-01

   .\scripts\install_central_task.ps1 `
     -PythonPath    "C:\Python311\python.exe" `
     -TaskUser      "DOMAIN\\svc-monitor" `
     -MonitorScript "C:\P3DMonitor\src\central_monitor\central_monitor.py" `
     -ConfigPath    "C:\P3DMonitor\config\central_config.json" `
     -HostsPath     "C:\P3DMonitor\config\hosts.json"
   ```

6. **Test central monitor manually (console mode):**
   ```powershell
   cd C:\P3DMonitor
   python src\central_monitor\central_monitor.py .\config\central_config.json .\config\hosts.json
   ```

   **Expected:**
   - Ping to host-01 succeeds
   - VNC port 5900 reachable
   - Heartbeat read successfully
   - Status: HEALTHY
   - Output to console + log file

### Phase 2: Failure Mode Testing (host-01, 1 day)

7. **Test: Stop P3D process**
   - SSH into host-01
   - Kill Prepar3D.exe process
   - Monitor CONFLAG logs: should detect P3D_NOT_RUNNING within 2 cycles (60 seconds)
   - Restart P3D
   - Monitor recovery to HEALTHY

8. **Test: Disconnect network (simulate ping failure)**
   - Disconnect host-01 from network or drop routing
   - Monitor CONFLAG: should detect HOST_UNREACHABLE after 2 cycles
   - Restore network
   - Monitor recovery

9. **Test: Stop TightVNC service**
   - SSH into host-01
   - Stop tvnserver service
   - Monitor CONFLAG: should detect VNC_DOWN after 2 cycles
   - Start service
   - Monitor recovery

10. **Test: Age heartbeat file**
    - On CONFLAG, artificially age host-01.json to >90 seconds old
    - Monitor: should detect HEARTBEAT_STALE
    - Restore and verify recovery

11. **Test: Corrupt heartbeat JSON**
    - On CONFLAG, truncate or corrupt host-01.json
    - Monitor: should log error and treat as stale
    - Verify watchdog on host-01 overwrites with fresh JSON
    - Monitor recovery

### Phase 3: Alert & Recovery Testing (1 day)

12. **Configure SMTP (test mode):**
    - Set `email_enabled: true` in central_config.json
    - Set test recipient (technician email)
    - Trigger a failure (stop P3D)
    - Verify alert email received within 2 minutes
    - Restore P3D
    - Verify recovery email

13. **Validate logs for audit trail:**
    - Check CONFLAG logs: `C:\P3DMonitor\logs\central_monitor.log`
    - Check host-01 logs: `\\host-01\C$\P3DWatchdog\logs\host_watchdog.log`
    - Verify timestamps, statuses, and incident transitions are recorded

### Phase 4: Sign-Off & Rollout Decision

14. **Collect pilot results:**
    -  Heartbeats written every 30 seconds (host-01)
    -  Central monitor detects all failure modes
    -  Status transitions logged correctly
    -  Alerts sent on failure, recovery on restoration
    -  Failure counters suppress transient flaps
    -  No unexpected crashes or hangs observed

15. **Rollout decision criteria:**
    - **PROCEED to six-host:** All tests pass, no open issues
    - **CONTINUE pilot:** Minor issues found, fix and retest
    - **ABORT & REVISE:** Critical issues or unexpected behavior

16. **If PROCEED: Deploy to remaining hosts (host-02 through host-06)**
    - Repeat steps 1–5 for each host (can run in parallel)
    - Use a staggered schedule to avoid overloading CONFLAG
    - Example: Deploy 1 host per hour to verify no cascade failures
    - Monitor central console dashboard for all six hosts green

17. **Final rollout checklist:**
    - [ ] All six hosts writing heartbeats
    - [ ] Central monitor polling all six hosts
    - [ ] No error spam in central logs
    - [ ] Technician trained on alert response
    - [ ] Rollback plan documented and tested
    - [ ] On-call rotation established
    - [ ] Post-deployment review scheduled (7 days)

---

## 17. Cyber Review Notes

### Security Posture
- **Monitoring-only scope:** No automation, no state changes, no reboot/restart/kill actions. Safe by design.
- **No embedded credentials:** SMTP credentials loaded from environment variables; no secrets in code or config files.
- **Service account segregation:** Dedicated service accounts (`svc-monitor`, `svc-watchdog`) with minimal permissions.
- **Network isolation:** Internal-only communication (CONFLAG → hosts via TCP 5900 VNC, hosts → heartbeat share); no external egress.
- **Log retention:** Local logs on each host; central logs on CONFLAG (7-day example retention in rotation policy).

### Known Limitations & Mitigations
1. **Event log hang detection (Event ID 1002) is experimental:**
   - Low-confidence signal; relies on heuristic message parsing
   - Mitigation: Treat hang alerts as secondary indicators; prioritize crash detection (1000/1001)
   - Future: Consider adding P3D debug logs or simpler heartbeat health metrics

2. **Heartbeat share is trust-boundary:**
   - Any user with write access can corrupt host files
   - Mitigation: Apply restrictive NTFS ACLs; audit share access; monitor file tampering
   - Future: Add cryptographic signatures to heartbeat JSON (SHA256 with service-account-only key)

3. **No multi-site replication:**
   - Current design supports six hosts + one central monitor only
   - Mitigation: For future expansion, consider adding standby central monitor or cloud-based aggregation
   - Future: Design DR plan before adding second site

4. **VNC port 5900 assumed open:**
   - Relies on host firewall or network segmentation to block external access
   - Mitigation: Ensure hosts are on internal network only; implement perimeter firewall rules
   - Future: Consider adding TLS-encrypted VNC tunnel instead of raw TCP

### Operational Hygiene
- **Config files are examples:** Always review and customize before deploying to production.
- **Credentials in PowerShell commands:** When running install scripts, substitute real domain, service account names, and paths.
- **Logs are audit trail:** Retain logs for 30+ days; review for anomalies (repeated failures, unexpected status changes).
- **Scheduled tasks run hidden:** Use Task Scheduler GUI or `Get-ScheduledTask` to monitor execution history; watch for failures.
