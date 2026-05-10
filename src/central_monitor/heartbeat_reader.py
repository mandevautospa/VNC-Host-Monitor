"""
Reads a heartbeat JSON file written by a P3D host watchdog and
determines whether it is fresh enough to be trusted.

read_heartbeat() is the only public function.  It never raises.
"""

import json
import logging
import time as _time
from pathlib import Path

logger = logging.getLogger(__name__)


def read_heartbeat(path: str | Path, stale_seconds: int = 90) -> "HeartbeatResult":
    """
    Read and parse *path* (a host heartbeat JSON file).

    Freshness is measured against the file's OS modification time so that
    a frozen or dead host watchdog is detected even if the JSON timestamp
    field itself is wrong.

    Args:
        path:           Absolute path to the heartbeat file (str or Path, may be a UNC path).
        stale_seconds:  Max age in seconds before the heartbeat is considered stale.

    Returns:
        HeartbeatResult.  On any failure, exists/fresh may be False and
        error will describe the problem.
    """
    from src.common.models import HeartbeatResult
    
    path_obj = Path(path) if isinstance(path, str) else path
    
    if not path_obj.exists():
        return HeartbeatResult(exists=False, path=str(path), error="Heartbeat file not found")

    try:
        mtime = path_obj.stat().st_mtime
        age = _time.time() - mtime
        fresh = age <= stale_seconds

        with open(path_obj, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        return HeartbeatResult(
            exists=True,
            fresh=fresh,
            age_seconds=round(age, 1),
            path=str(path),
            data=data,
        )

    except json.JSONDecodeError as exc:
        logger.warning("Malformed heartbeat JSON at %s: %s", path, exc)
        return HeartbeatResult(
            exists=True,
            fresh=False,
            path=str(path),
            error=f"JSON parse error: {exc}",
        )
    except PermissionError as exc:
        logger.warning("Permission denied reading heartbeat at %s: %s", path, exc)
        return HeartbeatResult(exists=True, fresh=False, path=str(path), error=str(exc))
    except Exception as exc:
        logger.error("Failed to read heartbeat at %s: %s", path, exc)
        return HeartbeatResult(exists=True, fresh=False, path=str(path), error=str(exc))
