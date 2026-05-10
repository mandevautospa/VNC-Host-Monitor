"""
Writes the host heartbeat JSON file to the shared health folder.

The file is written atomically:
  1. Write to <path>.tmp
  2. os.replace() renames it to <path>

This prevents the central monitor from reading a half-written file.

write_heartbeat() is the only public function.  It returns True on success
and False on failure (error is logged — never raised).
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import List

logger = logging.getLogger(__name__)

WATCHDOG_VERSION = "0.1.0"


def write_heartbeat(
    host_name: str,
    output_path: str,
    status: str,
    p3d: dict,
    tightvnc: dict,
    resources: dict,
    events: dict,
    errors: List[str],
) -> bool:
    """
    Assemble and atomically write a heartbeat JSON file.

    Args:
        host_name:   Identifier written into the "host" field (e.g. "host-01").
        output_path: Full path where the file should land (may be a UNC path).
        status:      Local status string from classify_local_status().
        p3d:         Dict of P3D process fields.
        tightvnc:    Dict of TightVNC service fields.
        resources:   Dict of CPU/RAM/disk fields.
        events:      Dict of event-log summary fields.
        errors:      List of non-fatal error strings collected during the run.

    Returns:
        True if the file was written successfully, False otherwise.
    """
    heartbeat = {
        "schema_version": "1.0",
        "host": host_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "watchdog_version": WATCHDOG_VERSION,
        "status": status,
        "p3d": p3d,
        "tightvnc": tightvnc,
        "resources": resources,
        "events": events,
        "errors": errors,
    }

    tmp_path = output_path + ".tmp"
    try:
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(heartbeat, fh, indent=2)

        os.replace(tmp_path, output_path)
        logger.debug("Heartbeat written → %s", output_path)
        return True

    except PermissionError as exc:
        logger.error(
            "Permission denied writing heartbeat to %s: %s "
            "(check share permissions for the watchdog user account)",
            output_path, exc,
        )
    except OSError as exc:
        logger.error("OS error writing heartbeat to %s: %s", output_path, exc)
    except Exception as exc:
        logger.error("Unexpected error writing heartbeat to %s: %s", output_path, exc)

    # Clean up orphaned .tmp file if it exists
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except OSError:
        pass

    return False
