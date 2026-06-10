"""
Checks whether Prepar3D.exe is running and collects its resource usage.

Uses psutil, which must be installed:  pip install psutil

check_p3d_process() is the only public function.  It never raises.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import psutil

logger = logging.getLogger(__name__)


@dataclass
class P3DProcessResult:
    running: bool
    pid: Optional[int] = None
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    memory_percent: Optional[float] = None
    hang_suspected: bool = False
    error: Optional[str] = None


def check_p3d_process(process_name: str = "Prepar3D.exe") -> P3DProcessResult:
    """
    Scan running processes for *process_name* (case-insensitive).

    CPU percent is sampled with a 1-second interval so the value reflects
    actual recent usage rather than a meaningless snapshot.

    The hang_suspected flag is set when:
      - The process is running
      - CPU usage rounds to 0 %
    This is a weak signal only — call it repeatedly before acting on it.
    """
    try:
        target = process_name.lower()
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() == target:
                    # First call seeds the counter; interval=1 waits for a real sample
                    try:
                        cpu = proc.cpu_percent(interval=1.0)
                        mem_info = proc.memory_info()
                        mem_mb = mem_info.rss / (1024 * 1024)
                        mem_pct = proc.memory_percent()
                        hang_suspected = round(cpu, 1) == 0.0
                        return P3DProcessResult(
                            running=True,
                            pid=proc.info["pid"],
                            cpu_percent=round(cpu, 1),
                            memory_mb=round(mem_mb, 1),
                            memory_percent=round(mem_pct, 1),
                            hang_suspected=hang_suspected,
                        )
                    except psutil.AccessDenied:
                        # Process is running but stats are not readable under this account
                        logger.warning(
                            "AccessDenied reading stats for %s (pid=%s); "
                            "reporting as running with no stats",
                            process_name,
                            proc.info["pid"],
                        )
                        return P3DProcessResult(running=True, pid=proc.info["pid"])
            except psutil.NoSuchProcess:
                # Process vanished between iter and attribute access — skip it
                continue

        return P3DProcessResult(running=False)

    except Exception as exc:
        logger.error("P3D process check failed: %s", exc)
        return P3DProcessResult(running=False, error=str(exc))
