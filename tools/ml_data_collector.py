"""
tools/ml_data_collector.py

Lightweight ML data collection script for P3D Host Monitor.
Collects system and P3D process metrics on a fixed interval and writes
one row per sample to a daily CSV file.  Designed to run safely in the
background – read-only, no restarts, no remediation.

Usage
-----
    python tools/ml_data_collector.py --host host-01 --mission "Test Mission"
    python tools/ml_data_collector.py --host host-01 --mission "Test Mission" --interval 10
    python tools/ml_data_collector.py --host host-01 --mission "Test Mission" --out analysis/ml_data

Stop with Ctrl+C.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional dependency: psutil
# ---------------------------------------------------------------------------
try:
    import psutil

    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False
    print(
        "[ml_data_collector] psutil is not installed.  System CPU/RAM/disk/uptime "
        "metrics will not be collected.\n"
        "Install it with:  pip install psutil",
        file=sys.stderr,
    )

# ---------------------------------------------------------------------------
# CSV field names (order is preserved in the output file)
# ---------------------------------------------------------------------------
FIELDNAMES = [
    "timestamp_local",
    "timestamp_utc",
    "host_name",
    "mission_name",
    "sample_interval_seconds",
    "system_cpu_percent",
    "system_ram_percent",
    "system_ram_used_mb",
    "system_ram_total_mb",
    "disk_percent",
    "disk_free_gb",
    "windows_uptime_seconds",
    "p3d_running",
    "p3d_process_count",
    "p3d_pid",
    "p3d_name",
    "p3d_responding",
    "p3d_cpu_seconds_total",
    "p3d_memory_mb",
    "p3d_start_time",
    "p3d_runtime_seconds",
    "p3d_status_text",
    "collector_error_count",
    "incident_label",
]

# Running total of non-fatal errors encountered since the script started.
_error_count: int = 0


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _build_error_logger(log_path: Path) -> logging.Logger:
    """Return a file logger that appends collector errors to *log_path*."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ml_collector_errors")
    logger.setLevel(logging.ERROR)
    if not logger.handlers:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)s  %(message)s")
        )
        logger.addHandler(handler)
    return logger


def _log_error(logger: logging.Logger, message: str, exc: BaseException | None = None) -> None:
    global _error_count
    _error_count += 1
    if exc is not None:
        logger.error("%s: %s", message, exc, exc_info=True)
    else:
        logger.error(message)


# ---------------------------------------------------------------------------
# System metrics (psutil)
# ---------------------------------------------------------------------------

def _collect_system_metrics(logger: logging.Logger) -> dict:
    result: dict = {
        "system_cpu_percent": "",
        "system_ram_percent": "",
        "system_ram_used_mb": "",
        "system_ram_total_mb": "",
        "disk_percent": "",
        "disk_free_gb": "",
        "windows_uptime_seconds": "",
    }

    if not _PSUTIL_AVAILABLE:
        return result

    try:
        result["system_cpu_percent"] = psutil.cpu_percent(interval=None)
    except Exception as exc:
        _log_error(logger, "cpu_percent failed", exc)

    try:
        vm = psutil.virtual_memory()
        result["system_ram_percent"] = vm.percent
        result["system_ram_used_mb"] = round(vm.used / 1024 / 1024, 1)
        result["system_ram_total_mb"] = round(vm.total / 1024 / 1024, 1)
    except Exception as exc:
        _log_error(logger, "virtual_memory failed", exc)

    try:
        du = psutil.disk_usage("/")
        result["disk_percent"] = du.percent
        result["disk_free_gb"] = round(du.free / 1024 / 1024 / 1024, 2)
    except Exception as exc:
        _log_error(logger, "disk_usage('/') failed", exc)

    try:
        result["windows_uptime_seconds"] = round(time.time() - psutil.boot_time(), 1)
    except Exception as exc:
        _log_error(logger, "boot_time failed", exc)

    return result


# ---------------------------------------------------------------------------
# P3D process metrics (PowerShell)
# ---------------------------------------------------------------------------

_PS_SCRIPT = (
    "Get-Process -Name *Prepar3D*,*P3D* -ErrorAction SilentlyContinue "
    "| Select-Object Name,Id,CPU,WorkingSet64,StartTime,Responding "
    "| ConvertTo-Json -Depth 2"
)


def _query_p3d_powershell() -> list[dict]:
    """
    Run a PowerShell one-liner to retrieve P3D process info.
    Returns a (possibly empty) list of process-info dicts.
    Raises on PowerShell execution failure so callers can handle it.
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_SCRIPT],
        capture_output=True,
        text=True,
        timeout=15,
    )
    raw = result.stdout.strip()
    if not raw:
        return []
    data = json.loads(raw)
    # PowerShell returns a single object (not array) when there is only one match.
    if isinstance(data, dict):
        data = [data]
    return data


def _collect_p3d_metrics(logger: logging.Logger) -> dict:
    result: dict = {
        "p3d_running": False,
        "p3d_process_count": 0,
        "p3d_pid": "",
        "p3d_name": "",
        "p3d_responding": "",
        "p3d_cpu_seconds_total": "",
        "p3d_memory_mb": "",
        "p3d_start_time": "",
        "p3d_runtime_seconds": "",
        "p3d_status_text": "P3D_NOT_RUNNING",
    }

    try:
        processes = _query_p3d_powershell()
    except FileNotFoundError:
        # powershell.exe not on PATH (non-Windows dev machine)
        _log_error(logger, "powershell not found; skipping P3D metrics")
        result["p3d_status_text"] = "P3D_STATUS_UNKNOWN"
        return result
    except subprocess.TimeoutExpired as exc:
        _log_error(logger, "PowerShell timed out while querying P3D", exc)
        result["p3d_status_text"] = "P3D_STATUS_UNKNOWN"
        return result
    except json.JSONDecodeError as exc:
        _log_error(logger, "Could not parse PowerShell JSON output", exc)
        result["p3d_status_text"] = "P3D_STATUS_UNKNOWN"
        return result
    except Exception as exc:
        _log_error(logger, "Unexpected error querying P3D via PowerShell", exc)
        result["p3d_status_text"] = "P3D_STATUS_UNKNOWN"
        return result

    if not processes:
        result["p3d_status_text"] = "P3D_NOT_RUNNING"
        return result

    result["p3d_running"] = True
    result["p3d_process_count"] = len(processes)

    # Pick the main process: largest WorkingSet64
    try:
        main_proc = max(processes, key=lambda p: p.get("WorkingSet64") or 0)
    except Exception as exc:
        _log_error(logger, "Could not determine main P3D process", exc)
        result["p3d_status_text"] = "P3D_STATUS_UNKNOWN"
        return result

    try:
        result["p3d_pid"] = main_proc.get("Id", "")
    except Exception:
        pass

    try:
        result["p3d_name"] = main_proc.get("Name", "")
    except Exception:
        pass

    responding: bool | None = None
    try:
        raw_resp = main_proc.get("Responding")
        if raw_resp is not None:
            responding = bool(raw_resp)
            result["p3d_responding"] = responding
    except Exception as exc:
        _log_error(logger, "Could not read Responding field", exc)

    try:
        cpu_val = main_proc.get("CPU")
        if cpu_val is not None:
            result["p3d_cpu_seconds_total"] = round(float(cpu_val), 3)
    except Exception as exc:
        _log_error(logger, "Could not read CPU field", exc)

    try:
        ws = main_proc.get("WorkingSet64")
        if ws is not None:
            result["p3d_memory_mb"] = round(int(ws) / 1024 / 1024, 1)
    except Exception as exc:
        _log_error(logger, "Could not read WorkingSet64 field", exc)

    try:
        start_raw = main_proc.get("StartTime")
        if start_raw:
            result["p3d_start_time"] = start_raw
            # PowerShell serialises dates like "/Date(1234567890000)/"
            if isinstance(start_raw, str) and start_raw.startswith("/Date("):
                ms = int(start_raw[6:start_raw.index(")")])
                start_epoch = ms / 1000.0
                result["p3d_runtime_seconds"] = round(time.time() - start_epoch, 1)
    except Exception as exc:
        _log_error(logger, "Could not parse P3D StartTime", exc)

    # Determine status text
    if responding is True:
        result["p3d_status_text"] = "P3D_RUNNING_RESPONDING"
    elif responding is False:
        result["p3d_status_text"] = "P3D_RUNNING_NOT_RESPONDING"
    else:
        result["p3d_status_text"] = "P3D_STATUS_UNKNOWN"

    return result


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def _csv_path(out_dir: Path, host: str) -> Path:
    date_str = datetime.now().strftime("%Y-%m-%d")
    return out_dir / f"{host}_ml_metrics_{date_str}.csv"


def _ensure_csv(csv_path: Path) -> bool:
    """Create file with header row if it does not exist.  Returns True if new."""
    if csv_path.exists():
        return False
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
    return True


def _write_row(csv_path: Path, row: dict) -> None:
    with csv_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writerow(row)
        fh.flush()


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _collect_one(host: str, mission: str, interval: int, logger: logging.Logger) -> dict:
    now_local = datetime.now()
    now_utc = datetime.now(timezone.utc)

    row: dict = {
        "timestamp_local": now_local.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "host_name": host,
        "mission_name": mission,
        "sample_interval_seconds": interval,
        "incident_label": "unlabeled",
    }

    row.update(_collect_system_metrics(logger))
    row.update(_collect_p3d_metrics(logger))
    row["collector_error_count"] = _error_count

    return row


def _run(args: argparse.Namespace) -> None:
    global _error_count
    _error_count = 0

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    error_log_path = out_dir / f"collector_errors_{date_str}.log"
    logger = _build_error_logger(error_log_path)

    # Prime psutil CPU measurement (first call always returns 0.0)
    if _PSUTIL_AVAILABLE:
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    print(
        f"[ml_data_collector] Starting — host={args.host!r}, "
        f"mission={args.mission!r}, interval={args.interval}s"
    )
    print(f"[ml_data_collector] Output directory: {out_dir.resolve()}")
    print("[ml_data_collector] Press Ctrl+C to stop.\n")

    try:
        while True:
            # Recalculate CSV path each iteration to handle midnight rollovers.
            csv_path = _csv_path(out_dir, args.host)
            is_new = _ensure_csv(csv_path)
            if is_new:
                print(f"[ml_data_collector] Created new CSV: {csv_path}")

            try:
                row = _collect_one(args.host, args.mission, args.interval, logger)
                _write_row(csv_path, row)
                status = row.get("p3d_status_text", "")
                ts = row.get("timestamp_local", "")
                print(f"[{ts}]  p3d_status={status}  errors={row['collector_error_count']}")
            except Exception as exc:
                _log_error(logger, "Unexpected error during sample collection", exc)
                print(f"[ml_data_collector] ERROR during sample: {exc}", file=sys.stderr)

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\n[ml_data_collector] Stopped by user (Ctrl+C).")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect P3D host metrics for ML training data."
    )
    parser.add_argument(
        "--host",
        default="host-01",
        help="Host name used in output filenames and the host_name column (default: host-01)",
    )
    parser.add_argument(
        "--mission",
        default="",
        help="Current mission name written to the mission_name column",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Sample interval in seconds (default: 5)",
    )
    parser.add_argument(
        "--out",
        default="analysis/ml_data",
        help="Output directory for CSV and log files (default: analysis/ml_data)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    _run(_parse_args())
