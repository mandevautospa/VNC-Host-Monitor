from pathlib import Path
import csv
import json
from datetime import datetime, timezone

HEARTBEAT_DIR = Path(r"C:\P3DHealth")
OUTPUT_CSV = Path("analysis/heartbeat_metrics.csv")


def get_nested(data, *keys, default=""):
    current = data

    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)

    return current if current is not None else default


def read_existing_keys(csv_path):
    """
    Prevent duplicate rows if this script is run repeatedly.
    We use host + heartbeat timestamp as the unique key.
    """
    existing = set()

    if not csv_path.exists():
        return existing

    with csv_path.open("r", newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        for row in reader:
            existing.add((row.get("host"), row.get("heartbeat_timestamp")))

    return existing


def parse_heartbeat(path):
    with path.open("r", encoding="utf-8", errors="ignore") as file:
        data = json.load(file)

    host = data.get("host", path.stem)
    heartbeat_timestamp = data.get("timestamp", "")

    return {
        "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "heartbeat_timestamp": heartbeat_timestamp,
        "heartbeat_file": str(path),
        "schema_version": data.get("schema_version", ""),
        "host": host,
        "watchdog_version": data.get("watchdog_version", ""),
        "status": data.get("status", ""),

        # Whole-host/server metrics
        "host_cpu_percent": get_nested(data, "resources", "cpu_percent"),
        "host_ram_percent": get_nested(data, "resources", "ram_percent"),
        "host_gpu_percent": get_nested(data, "resources", "gpu_percent"),
        "host_vram_percent": get_nested(data, "resources", "vram_percent"),
        "host_vram_used_mb": get_nested(data, "resources", "vram_used_mb"),
        "host_vram_total_mb": get_nested(data, "resources", "vram_total_mb"),
        "disk_free_percent": get_nested(data, "resources", "disk_free_percent"),
        "disk_free_gb": get_nested(data, "resources", "disk_free_gb"),

        # P3D-specific metrics
        "p3d_running": get_nested(data, "p3d", "running"),
        "p3d_pid": get_nested(data, "p3d", "pid"),
        "p3d_cpu_percent": get_nested(data, "p3d", "cpu_percent"),
        "p3d_memory_mb": get_nested(data, "p3d", "memory_mb"),
        "p3d_memory_percent": get_nested(data, "p3d", "memory_percent"),
        "p3d_hang_suspected": get_nested(data, "p3d", "hang_suspected"),

        # TightVNC
        "tightvnc_service_running": get_nested(data, "tightvnc", "service_running"),

        # Event counts
        "recent_app_crash_count": get_nested(data, "events", "recent_app_crash_count"),
        "recent_app_hang_count": get_nested(data, "events", "recent_app_hang_count"),
        "recent_display_error_count": get_nested(data, "events", "recent_display_error_count"),

        # Error summary
        "error_count": len(data.get("errors", [])) if isinstance(data.get("errors", []), list) else "",
    }


def collect_once():
    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "collected_at",
        "heartbeat_timestamp",
        "heartbeat_file",
        "schema_version",
        "host",
        "watchdog_version",
        "status",
        "host_cpu_percent",
        "host_ram_percent",
        "host_gpu_percent",
        "host_vram_percent",
        "host_vram_used_mb",
        "host_vram_total_mb",
        "disk_free_percent",
        "disk_free_gb",
        "p3d_running",
        "p3d_pid",
        "p3d_cpu_percent",
        "p3d_memory_mb",
        "p3d_memory_percent",
        "p3d_hang_suspected",
        "tightvnc_service_running",
        "recent_app_crash_count",
        "recent_app_hang_count",
        "recent_display_error_count",
        "error_count",
    ]

    existing_keys = read_existing_keys(OUTPUT_CSV)
    new_rows = []

    for heartbeat_file in sorted(HEARTBEAT_DIR.glob("host-*.json")):
        try:
            row = parse_heartbeat(heartbeat_file)
        except json.JSONDecodeError:
            print(f"Skipping invalid JSON: {heartbeat_file}")
            continue
        except OSError as error:
            print(f"Could not read {heartbeat_file}: {error}")
            continue

        unique_key = (str(row["host"]), str(row["heartbeat_timestamp"]))

        if unique_key not in existing_keys:
            new_rows.append(row)
            existing_keys.add(unique_key)

    file_exists = OUTPUT_CSV.exists()

    with OUTPUT_CSV.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        writer.writerows(new_rows)

    print(f"Collected {len(new_rows)} new rows into {OUTPUT_CSV}")


if __name__ == "__main__":
    collect_once()