# P3D Host Monitor Deployment Dev Sheet

## Scope
This runbook lists exactly what must be done on each machine so the full monitoring stack runs smoothly.

- Central monitor machine: runs central monitor loop
- Six P3D hosts: each runs local watchdog loop
- Shared heartbeat folder: hosts write JSON, central monitor reads JSON

---

## CONFLAG

### Runs the central monitor process:
- ping checks
- VNC TCP and banner checks
- heartbeat freshness checks
- state evaluation and failure counters
- dashboard output and central logging

### One-time setup
1. Copy this repo to C:\P3DMonitor\.
2. Install Python 3.11+ and add Python to PATH.
3. Install dependencies:

```powershell
cd C:\P3DMonitor
python -m pip install -r requirements.txt
```

4. Create and share the heartbeat folder:
- Create C:\P3DHealth\ (or your preferred local path).
- Share it as P3DHealth.
- Grant Change permission (read/write) to all host machine accounts, or one dedicated service account used by all hosts.
- Resulting UNC path pattern: \\\\CONFLAG\P3DHealth\

5. Create real config files:
- Copy config/central_config.example.json to config/central_config.json
- Copy config/hosts.example.json to config/hosts.json
- Edit config/hosts.json:
  - set each address to real hostname or IP
  - set each heartbeat_path to real share path, for example:
    - \\\\CONFLAG\P3DHealth\host-01.json

6. Register scheduled task as Administrator:

```powershell
cd C:\P3DMonitor
.\scripts\install_central_task.ps1 `
  -PythonPath    "C:\Python311\python.exe" `
  -TaskUser      "DOMAIN\svc-monitor" `
  -MonitorScript "C:\P3DMonitor\src\central_monitor\central_monitor.py" `
  -ConfigPath    "C:\P3DMonitor\config\central_config.json" `
  -HostsPath     "C:\P3DMonitor\config\hosts.json"
```

### Runtime output and logs
- Console dashboard updates every interval
- Central log file: C:\P3DMonitor\logs\central_monitor.log

---

## P3D Host 01 to Host 06

### Purpose
Each host runs the local watchdog process:
- checks Prepar3D process
- checks TightVNC service
- collects CPU/RAM/disk
- checks recent Windows event logs
- writes heartbeat JSON to shared folder
- writes local watchdog logs

### One-time setup on each host
1. Copy the repo (or required source/config files) to C:\P3DWatchdog\.
2. Install Python 3.11+ and add Python to PATH.
3. Install dependencies:

```powershell
cd C:\P3DWatchdog
python -m pip install -r requirements.txt
```

4. Verify heartbeat share write access from this host:

```powershell
New-Item "\\CONFLAG\P3DHealth\write-test.txt" -ItemType File
Remove-Item "\\CONFLAG\P3DHealth\write-test.txt"
```

If this fails, fix share permissions before continuing.

5. Create host config at C:\P3DWatchdog\config.json (copy from config/host_watchdog_config.example.json) and set:
- host_name to this machine host name (example host-03)
- heartbeat_output_path to this machine file on share (example \\\\CONFLAG\P3DHealth\host-03.json)
- local_log_path (example C:\P3DWatchdog\logs\host_watchdog.log)
- p3d_process_name (normally Prepar3D.exe)
- tightvnc_service_name (normally tvnserver)

6. Register scheduled task as Administrator on the host:

```powershell
cd C:\P3DWatchdog
.\scripts\install_host_task.ps1 `
  -PythonPath     "C:\Python311\python.exe" `
  -TaskUser       "DOMAIN\svc-watchdog" `
  -WatchdogScript "C:\P3DWatchdog\src\host_agent\host_watchdog.py" `
  -ConfigPath     "C:\P3DWatchdog\config.json"
```

### Runtime output and logs
- Heartbeat file path per host:
  - \\\\CONFLAG\P3DHealth\host-01.json through host-06.json
- Host local log:
  - C:\P3DWatchdog\logs\host_watchdog.log

---

## Shared Heartbeat Folder Requirements

### Required behavior
- Every host can write its own file.
- Central monitor can read all host files.
- Files are overwritten continuously by host watchdog.

### Required naming convention
- host-01.json
- host-02.json
- host-03.json
- host-04.json
- host-05.json
- host-06.json

### Freshness target
- Host write interval: 30 seconds
- Central stale threshold: 90 seconds

---

## Bring-up Sequence (Recommended)

1. Prepare and verify monitor machine.
2. Prepare one host first (pilot host).
3. Confirm pilot host heartbeat appears and updates.
4. Start central monitor and validate one-host status.
5. Roll out to remaining five hosts one at a time.
6. Re-check central dashboard and logs after each host comes online.

---

## Validation 

### CONFLAG:
- hosts.json contains all six hosts and correct heartbeat paths.
- central_config.json exists and points to valid central log path.
- Central scheduled task exists and is Running.
- Central log file is updating.

### HOST-01 - HOST-06
- config.json exists with host-specific values.
- Host scheduled task exists and is Running.
- Host log file is updating.
- Host JSON heartbeat exists on shared folder and updates every ~30 seconds.

### End-to-end checks
Use script from CONFLAG

```powershell
cd C:\P3DMonitor
.\scripts\test_single_host.ps1 -HostName host-03 -HeartbeatPath "\\CONFLAG\P3DHealth\host-03.json"
```

Expected:
- Ping OK
- VNC port 5900 OK
- Heartbeat fresh (<= 90s)

---

## Operational Constraints (MVP)

This version is monitoring-only. It must not:
- reboot hosts
- restart Prepar3D
- kill processes
- restart TightVNC automatically
- interrupt active student sessions

Workflow is strictly:
Detect -> Log -> Alert -> Technician investigates manually

---

## Troubleshooting Fast Path

### If heartbeat is missing
- check host scheduled task status
- check host config heartbeat_output_path
- verify share permissions from that host
- inspect host log for write or permission errors

### If ping fails but heartbeat is fresh
- central network path issue or DNS issue likely
- verify name resolution and routing from monitor PC

### If VNC fails but ping works
- verify TightVNC service status on host
- verify port/firewall policy for 5900 internally

### If central task runs but no dashboard updates
- verify central config and hosts paths in scheduled task arguments
- run central script manually in terminal to view immediate errors

---

## Final Machine Mapping

| Machine | Runs | Main Config | Main Log |
|---|---|---|---|
| CONFLAG | src/central_monitor/central_monitor.py | config/central_config.json + config/hosts.json | C:\P3DMonitor\logs\central_monitor.log |
| Host 01 | src/host_agent/host_watchdog.py | C:\P3DWatchdog\config.json | C:\P3DWatchdog\logs\host_watchdog.log |
| Host 02 | src/host_agent/host_watchdog.py | C:\P3DWatchdog\config.json | C:\P3DWatchdog\logs\host_watchdog.log |
| Host 03 | src/host_agent/host_watchdog.py | C:\P3DWatchdog\config.json | C:\P3DWatchdog\logs\host_watchdog.log |
| Host 04 | src/host_agent/host_watchdog.py | C:\P3DWatchdog\config.json | C:\P3DWatchdog\logs\host_watchdog.log |
| Host 05 | src/host_agent/host_watchdog.py | C:\P3DWatchdog\config.json | C:\P3DWatchdog\logs\host_watchdog.log |
| Host 06 | src/host_agent/host_watchdog.py | C:\P3DWatchdog\config.json | C:\P3DWatchdog\logs\host_watchdog.log |

---

## GUI Run and Packaging

### Run GUI from source

```powershell
cd C:\P3DMonitor
python src\gui\monitor_gui.py .\config\central_config.json .\config\hosts.json
```

### Build GUI executable (PyInstaller)

```powershell
cd C:\P3DMonitor
python -m pip install -r requirements-dev.txt
pyinstaller --noconfirm --onefile --name P3DMonitorGUI src\gui\monitor_gui.py
```

### Keep config editable after packaging

Do not embed config JSON into the executable. Keep them as external files and pass them at launch:

```powershell
dist\P3DMonitorGUI.exe C:\P3DMonitor\config\central_config.json C:\P3DMonitor\config\hosts.json
```

---

## Home / Dev Mode

When you do not have access to CONFLAG or the lab network, use the dev config files and the fake heartbeat writer:

```powershell
cd C:\P3DMonitor
python scripts\write_fake_heartbeat.py --output dev_health\host-01.json --interval 10
```

In a second terminal:

```powershell
.\scripts\run_gui_dev.ps1
```

Useful one-shot tests:

```powershell
python scripts\write_fake_heartbeat.py --once --output dev_health\host-01.json --p3d-running false
python scripts\write_fake_heartbeat.py --once --output dev_health\host-01.json --cpu-percent 96
python scripts\write_fake_heartbeat.py --once --output dev_health\host-01.json --disk-free-percent 8 --disk-free-gb 5
```

Stop the writer and wait longer than the dev stale threshold to verify `STALE` behavior.

