"""Write local development heartbeat files for the P3D Host Monitor GUI.

This script is intentionally simple and Windows-friendly. It repeatedly writes a
heartbeat JSON file using the same shape produced by the real host watchdog so
that central-monitor behavior can be tested without live lab systems.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WATCHDOG_VERSION = "dev-1.0"
DEFAULT_OUTPUT = Path("dev_health") / "host-01.json"
DEFAULT_INTERVAL = 10.0


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def _classify_status(
    *,
    p3d_running: bool,
    cpu_percent: float,
    ram_percent: float,
    disk_free_percent: float,
    disk_free_gb: float,
    recent_app_crash_count: int,
    recent_app_hang_count: int,
) -> str:
    if recent_app_crash_count > 0:
        return "P3D_CRASH_DETECTED"
    if not p3d_running:
        return "P3D_NOT_RUNNING"
    if recent_app_hang_count > 0:
        return "P3D_HANG_SUSPECTED"

    critical = (
        cpu_percent >= 95.0
        or ram_percent >= 92.0
        or disk_free_percent <= 10.0
        or disk_free_gb <= 10.0
    )
    warning = (
        cpu_percent >= 85.0
        or ram_percent >= 85.0
        or disk_free_percent <= 20.0
        or disk_free_gb <= 20.0
    )

    if critical:
        return "RESOURCE_CRITICAL"
    if warning:
        return "RESOURCE_WARNING"
    return "HEALTHY"


def build_heartbeat_payload(
    *,
    host_name: str,
    p3d_running: bool,
    cpu_percent: float,
    ram_percent: float,
    disk_free_percent: float,
    disk_free_gb: float,
    recent_app_crash_count: int = 0,
    recent_app_hang_count: int = 0,
    recent_display_error_count: int = 0,
    tightvnc_running: bool = True,
    pid: int | None = 4321,
) -> dict[str, Any]:
    """Build a single heartbeat payload matching the host watchdog schema."""
    status = _classify_status(
        p3d_running=p3d_running,
        cpu_percent=cpu_percent,
        ram_percent=ram_percent,
        disk_free_percent=disk_free_percent,
        disk_free_gb=disk_free_gb,
        recent_app_crash_count=recent_app_crash_count,
        recent_app_hang_count=recent_app_hang_count,
    )

    return {
        "schema_version": "1.0",
        "host": host_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "watchdog_version": WATCHDOG_VERSION,
        "status": status,
        "p3d": {
            "process_name": "Prepar3D.exe",
            "running": p3d_running,
            "pid": pid if p3d_running else None,
            "cpu_percent": round(cpu_percent, 1),
            "memory_mb": round(cpu_percent * 8.0, 1),
            "memory_percent": round(min(100.0, cpu_percent + 5.0), 1),
            "hang_suspected": False,
        },
        "tightvnc": {
            "service_name": "tvnserver",
            "service_running": tightvnc_running,
        },
        "resources": {
            "cpu_percent": round(cpu_percent, 1),
            "ram_percent": round(ram_percent, 1),
            "disk_free_percent": round(disk_free_percent, 1),
            "disk_free_gb": round(disk_free_gb, 1),
        },
        "events": {
            "lookback_minutes": 10,
            "recent_app_crash_count": recent_app_crash_count,
            "recent_app_hang_count": recent_app_hang_count,
            "recent_display_error_count": recent_display_error_count,
            "recent_events_summary": "Dev heartbeat payload",
        },
        "errors": [],
    }


def write_heartbeat_file(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")

    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    os.replace(tmp_path, output_path)
    os.utime(output_path, None)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write fake P3D heartbeat JSON for local testing.")
    parser.add_argument("--host", default="host-01", help="Heartbeat host name.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Heartbeat output path.")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="Write interval in seconds.")
    parser.add_argument("--p3d-running", type=_parse_bool, default=True, help="Set P3D running true/false.")
    parser.add_argument("--cpu-percent", type=float, default=18.0, help="CPU percent to report.")
    parser.add_argument("--ram-percent", type=float, default=42.0, help="RAM percent to report.")
    parser.add_argument("--disk-free-percent", type=float, default=61.0, help="Disk free percent to report.")
    parser.add_argument("--disk-free-gb", type=float, default=120.0, help="Disk free GB to report.")
    parser.add_argument(
        "--recent-app-crash-count",
        type=int,
        default=0,
        help="Crash count to report in the heartbeat events block.",
    )
    parser.add_argument(
        "--recent-app-hang-count",
        type=int,
        default=0,
        help="Hang count to report in the heartbeat events block.",
    )
    parser.add_argument(
        "--recent-display-error-count",
        type=int,
        default=0,
        help="Display error count to report in the heartbeat events block.",
    )
    parser.add_argument(
        "--tightvnc-running",
        type=_parse_bool,
        default=True,
        help="Set TightVNC service running true/false.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Write one heartbeat and exit instead of looping.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    output_path = Path(args.output)

    try:
        while True:
            payload = build_heartbeat_payload(
                host_name=args.host,
                p3d_running=args.p3d_running,
                cpu_percent=args.cpu_percent,
                ram_percent=args.ram_percent,
                disk_free_percent=args.disk_free_percent,
                disk_free_gb=args.disk_free_gb,
                recent_app_crash_count=args.recent_app_crash_count,
                recent_app_hang_count=args.recent_app_hang_count,
                recent_display_error_count=args.recent_display_error_count,
                tightvnc_running=args.tightvnc_running,
            )
            write_heartbeat_file(output_path, payload)
            print(f"Wrote {output_path} -> status={payload['status']} timestamp={payload['timestamp']}")
            if args.once:
                return
            time.sleep(max(1.0, args.interval))
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
