"""
Collects system-wide CPU, RAM, and disk usage using psutil.

check_resources() is the only public function.  It never raises.
"""

import csv
import io
import logging
import subprocess
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
    gpu_percent: Optional[float] = None
    vram_percent: Optional[float] = None
    vram_used_mb: Optional[float] = None
    vram_total_mb: Optional[float] = None
    error: Optional[str] = None


def _read_gpu_metrics() -> dict[str, Optional[float]]:
    """
    Best-effort GPU metrics via nvidia-smi.

    Returns None values when nvidia-smi is unavailable or returns no rows.
    """
    empty = {
        "gpu_percent": None,
        "vram_percent": None,
        "vram_used_mb": None,
        "vram_total_mb": None,
    }

    cmd = [
        "nvidia-smi",
        "--query-gpu=utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return empty

    if proc.returncode != 0 or not proc.stdout.strip():
        return empty

    reader = csv.reader(io.StringIO(proc.stdout.strip()))
    gpu_values: list[float] = []
    used_values: list[float] = []
    total_values: list[float] = []
    for row in reader:
        if len(row) < 3:
            continue
        try:
            gpu_values.append(float(row[0].strip()))
            used_values.append(float(row[1].strip()))
            total_values.append(float(row[2].strip()))
        except ValueError:
            continue

    if not gpu_values or not used_values or not total_values:
        return empty

    used_sum = sum(used_values)
    total_sum = sum(total_values)
    vram_percent = (used_sum / total_sum * 100.0) if total_sum > 0 else None
    gpu_percent = sum(gpu_values) / len(gpu_values)

    return {
        "gpu_percent": round(gpu_percent, 1),
        "vram_percent": round(vram_percent, 1) if vram_percent is not None else None,
        "vram_used_mb": round(used_sum, 1),
        "vram_total_mb": round(total_sum, 1),
    }


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
        gpu = _read_gpu_metrics()

        return ResourceResult(
            cpu_percent=round(cpu, 1),
            ram_percent=round(ram, 1),
            disk_free_percent=round(disk_free_pct, 1),
            disk_free_gb=round(disk_free_gb, 1),
            gpu_percent=gpu["gpu_percent"],
            vram_percent=gpu["vram_percent"],
            vram_used_mb=gpu["vram_used_mb"],
            vram_total_mb=gpu["vram_total_mb"],
        )

    except FileNotFoundError:
        err = f"Disk path not found: {disk_path}"
        logger.error(err)
        return ResourceResult(error=err)
    except Exception as exc:
        logger.error("Resource check failed: %s", exc)
        return ResourceResult(error=str(exc))
