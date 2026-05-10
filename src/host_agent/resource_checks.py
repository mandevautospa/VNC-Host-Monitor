"""
Collects system-wide CPU, RAM, and disk usage using psutil.

check_resources() is the only public function.  It never raises.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import psutil

logger = logging.getLogger(__name__)


@dataclass
class ResourceResult:
    cpu_percent: float = 0.0
    ram_percent: float = 0.0
    disk_free_percent: float = 0.0
    disk_free_gb: float = 0.0
    error: Optional[str] = None


def check_resources(disk_path: str = "C:\\") -> ResourceResult:
    """
    Sample CPU (1-second blocking), RAM, and disk for *disk_path*.

    disk_free_percent is the complement of psutil's `percent` field:
        disk_free_percent = 100.0 - disk.percent
    """
    try:
        cpu = psutil.cpu_percent(interval=1.0)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage(disk_path)
        disk_free_pct = 100.0 - disk.percent
        disk_free_gb = disk.free / (1024 ** 3)

        return ResourceResult(
            cpu_percent=round(cpu, 1),
            ram_percent=round(ram, 1),
            disk_free_percent=round(disk_free_pct, 1),
            disk_free_gb=round(disk_free_gb, 1),
        )

    except FileNotFoundError:
        err = f"Disk path not found: {disk_path}"
        logger.error(err)
        return ResourceResult(error=err)
    except Exception as exc:
        logger.error("Resource check failed: %s", exc)
        return ResourceResult(error=str(exc))
