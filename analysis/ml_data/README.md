# ML Data Collector

This folder contains time-series CSV files collected by `tools/ml_data_collector.py`.
The data is intended for future ML model training to predict P3D host/session hangs.

---

## What the collector does

- Runs continuously on a configurable interval (default: every 5 seconds).
- Writes **one row per sample** to a daily CSV file named:
  `<host>_ml_metrics_YYYY-MM-DD.csv`
- Records system-level metrics (CPU, RAM, disk, uptime) via `psutil`.
- Queries the Windows `Responding` property of the Prepar3D process via PowerShell.
- Logs any non-fatal collection errors to `collector_errors_YYYY-MM-DD.log`.
- **Read-only** — it never restarts, kills, or modifies P3D or Windows.

---

## How to start

### Option A — directly from a terminal

```
python tools/ml_data_collector.py --host host-01 --mission "Test Mission"
```

Optional arguments:

| Argument | Default | Description |
|---|---|---|
| `--host` | `host-01` | Host name used in the filename and CSV column |
| `--mission` | _(empty)_ | Current mission name written to the CSV |
| `--interval` | `5` | Sample interval in seconds |
| `--out` | `analysis/ml_data` | Output directory |

### Option B — PowerShell background launcher

```powershell
.\tools\start_ml_collector.ps1 -HostName host-01 -MissionName "Test Mission"
```

This starts the collector as a hidden background process and streams
stdout/stderr to:

- `analysis/ml_data/ml_collector_stdout.log`
- `analysis/ml_data/ml_collector_stderr.log`

Tail the log while it runs:

```powershell
Get-Content -Wait "analysis\ml_data\ml_collector_stdout.log"
```

---

## How to stop

- **Direct terminal**: press `Ctrl+C`.
- **Background launcher**: note the PID printed at startup, then run:
  ```powershell
  Stop-Process -Id <PID>
  ```

---

## Where the CSV is saved

```
analysis/ml_data/<host>_ml_metrics_YYYY-MM-DD.csv
```

A new file is created automatically each day at midnight.
The output directory is created automatically if it does not exist.

---

## CSV columns

| Column | Description |
|---|---|
| `timestamp_local` | Local wall-clock time of the sample |
| `timestamp_utc` | UTC time of the sample |
| `host_name` | Host identifier (from `--host`) |
| `mission_name` | Mission name (from `--mission`) |
| `sample_interval_seconds` | Configured interval |
| `system_cpu_percent` | Whole-system CPU % |
| `system_ram_percent` | RAM usage % |
| `system_ram_used_mb` | RAM used (MB) |
| `system_ram_total_mb` | Total RAM (MB) |
| `disk_percent` | Disk usage % |
| `disk_free_gb` | Disk free space (GB) |
| `windows_uptime_seconds` | Seconds since last Windows boot |
| `p3d_running` | `True` / `False` |
| `p3d_process_count` | Number of matching P3D processes found |
| `p3d_pid` | PID of the main P3D process |
| `p3d_name` | Process name (e.g. `Prepar3D`) |
| `p3d_responding` | `True` / `False` / blank |
| `p3d_cpu_seconds_total` | Total CPU time consumed by P3D (seconds) |
| `p3d_memory_mb` | Working set of P3D (MB) |
| `p3d_start_time` | P3D process start time (raw from PowerShell) |
| `p3d_runtime_seconds` | Seconds since P3D started |
| `p3d_status_text` | Human-readable status (see below) |
| `collector_error_count` | Running count of non-fatal errors this session |
| `incident_label` | Label for supervised ML (default: `unlabeled`) |

### `p3d_status_text` values

| Value | Meaning |
|---|---|
| `P3D_NOT_RUNNING` | No Prepar3D/P3D process found |
| `P3D_RUNNING_RESPONDING` | P3D is running and the OS reports it as responding |
| `P3D_RUNNING_NOT_RESPONDING` | P3D is running but the OS reports it as **not** responding (hang) |
| `P3D_STATUS_UNKNOWN` | P3D exists but the Responding check failed |

---

## Labelling data for ML

Every row is written with `incident_label = unlabeled`.

After a session you can open the CSV in Excel or a text editor and change
the label on rows where you know something happened:

| Label | Meaning |
|---|---|
| `healthy` | Normal, expected operation |
| `p3d_hang` | P3D became unresponsive (white "Application Not Responding" screen) |
| `session_disconnect` | The VNC/sim session dropped unexpectedly |
| `manual_restart` | A manual P3D or host restart was performed |
| `mission_reload` | The mission was reloaded |

Keep `unlabeled` on rows where the state is uncertain.
