"""
Host watchdog — main polling loop.

Runs locally on each P3D host.  On every interval it:
  1. Checks Prepar3D.exe process health
  2. Checks TightVNC service status
  3. Collects CPU / RAM / disk usage
  4. Queries recent Windows event logs for crash / hang events
  5. Classifies local status
  6. Writes a heartbeat JSON file to the shared folder

The watchdog never reboots, kills, or restarts anything (MVP constraint).

Run:
    python host_watchdog.py [config.json]

The config path defaults to C:\\P3DWatchdog\\config.json.
Copy config/host_watchdog_config.example.json and edit it for each host.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

# Allow running directly from any working directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.common.logging_setup import setup_logger
from src.common.thresholds import Thresholds, evaluate_cpu, evaluate_ram, evaluate_disk
from src.host_agent.process_checks import P3D_EXPECTED_NAMES, check_p3d_process
from src.host_agent.resource_checks import check_resources
from src.host_agent.service_checks import check_service
from src.host_agent.event_log_checks import check_event_logs
from src.host_agent.heartbeat_writer import write_heartbeat

_DEFAULT_CONFIG = Path(r"C:\P3DWatchdog\config.json")


def _load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _classify_local_status(
    p3d,
    resources,
    events,
    thresholds: Thresholds,
    has_core_check_errors: bool,
) -> str:
    """Apply priority-ordered local status classification."""
    if has_core_check_errors:
        return "CRITICAL_CHECK_FAILED"

    if events.recent_app_crash_count > 0:
        return "P3D_CRASH_DETECTED"

    if not p3d.running:
        return "P3D_NOT_RUNNING"

    if p3d.hang_suspected:
        return "P3D_HANG_SUSPECTED"

    cpu_level = evaluate_cpu(resources.cpu_percent, thresholds)
    ram_level = evaluate_ram(resources.ram_percent, thresholds)
    disk_level = evaluate_disk(resources.disk_free_percent, resources.disk_free_gb, thresholds)

    if "CRITICAL" in (cpu_level, ram_level, disk_level):
        return "RESOURCE_CRITICAL"
    if "WARNING" in (cpu_level, ram_level, disk_level):
        return "RESOURCE_WARNING"

    return "HEALTHY"


def _run_once(config: dict, config_path: str, logger: logging.Logger) -> None:
    """Execute one complete watchdog check cycle and write the heartbeat."""
    host_name   = config["host_name"]
    # Support a list of process names or fall back to the single legacy key
    p3d_names = config.get("expected_process_names") or [
        config.get("p3d_process_name", "Prepar3D.exe")
    ]
    vnc_service = config.get("tightvnc_service_name", "tvnserver")
    lookback    = config.get("event_lookback_minutes", 10)
    disk_path   = config.get("disk_path", "C:\\")
    output_path = config["heartbeat_output_path"]

    thresholds = Thresholds(**config.get("thresholds", {}))
    errors: list[str] = []

    logger.info("Watchdog run start — host=%s", host_name)

    # ── Checks ──────────────────────────────────────────────────────────────
    p3d = check_p3d_process(p3d_names)
    if p3d.error:
        errors.append(f"P3D process check error: {p3d.error}")

    vnc_svc = check_service(vnc_service)
    if vnc_svc.error:
        errors.append(f"VNC service check error: {vnc_svc.error}")

    resources = check_resources(disk_path)
    if resources.error:
        errors.append(f"Resource check error: {resources.error}")

    events = check_event_logs(lookback)
    if events.error:
        errors.append(f"Event log check error: {events.error}")

    # ── Classification ───────────────────────────────────────────────────────
    status = _classify_local_status(
        p3d,
        resources,
        events,
        thresholds,
        has_core_check_errors=bool(errors),
    )

    # ── Build heartbeat payload ──────────────────────────────────────────────
    p3d_data = {
        "process_name": p3d_names[0] if len(p3d_names) == 1 else p3d_names,
        "expected_process_names": list(p3d_names),
        "running": p3d.running,
        "matched_process_name": p3d.matched_process_name or "unknown",
        "p3d_detection_method": "psutil_name_match",
        "pid": p3d.pid,
        "cpu_percent": p3d.cpu_percent,
        "memory_mb": p3d.memory_mb,
        "memory_percent": p3d.memory_percent,
        "hang_suspected": p3d.hang_suspected,
    }

    vnc_data = {
        "service_name": vnc_service,
        "service_running": vnc_svc.service_running,
    }

    res_data = {
        "cpu_percent": resources.cpu_percent,
        "ram_percent": resources.ram_percent,
        "disk_free_percent": resources.disk_free_percent,
        "disk_free_gb": resources.disk_free_gb,
    }

    events_data = {
        "lookback_minutes": lookback,
        "recent_app_crash_count": events.recent_app_crash_count,
        "recent_app_hang_count": events.recent_app_hang_count,
        "recent_display_error_count": events.recent_display_error_count,
        "recent_events_summary": events.recent_events_summary,
    }

    write_heartbeat(
        host_name,
        output_path,
        status,
        p3d_data,
        vnc_data,
        res_data,
        events_data,
        errors,
        config_path_used=str(config_path),
    )

    logger.info(
        "host=%s status=%s p3d=%s matched=%s cpu=%.1f%% ram=%.1f%% disk_free=%.1f%% errors=%d",
        host_name, status, p3d.running,
        p3d.matched_process_name or "none",
        resources.cpu_percent, resources.ram_percent, resources.disk_free_percent,
        len(errors),
    )


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_CONFIG
    config = _load_config(config_path)

    log_path = config.get("local_log_path", r"C:\P3DWatchdog\logs\host_watchdog.log")
    logger   = setup_logger("host_watchdog", log_path)

    interval = config.get("check_interval_seconds", 30)
    logger.info("Host watchdog started. Interval: %ds. Config: %s", interval, config_path)

    while True:
        try:
            _run_once(config, str(config_path), logger)
        except Exception as exc:
            logger.error("Unhandled error in watchdog run: %s", exc, exc_info=True)
        time.sleep(interval)


if __name__ == "__main__":
    main()
