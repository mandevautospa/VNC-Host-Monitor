"""
Checks whether Prepar3D.exe is running and collects its resource usage.

Uses psutil, which must be installed:  pip install psutil

check_p3d_process() is the only public function.  It never raises.

Process name matching is case-insensitive and normalises away the ``.exe``
suffix so that "Prepar3D.exe", "prepar3d.exe", "Prepar3D", and "prepar3d"
are all treated as the same target.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Union

import psutil

logger = logging.getLogger(__name__)

#: Default list of names that are all treated as Prepar3D
P3D_EXPECTED_NAMES: List[str] = [
    "Prepar3D.exe",
    "prepar3d.exe",
    "Prepar3D",
    "prepar3d",
]


@dataclass
class P3DProcessResult:
    running: bool
    pid: Optional[int] = None
    cpu_percent: Optional[float] = None
    memory_mb: Optional[float] = None
    memory_percent: Optional[float] = None
    hang_suspected: bool = False
    matched_process_name: Optional[str] = None
    error: Optional[str] = None


def _normalize_name(name: str) -> str:
    """Lower-case and strip the .exe suffix for comparison."""
    return name.lower().removesuffix(".exe")


def check_p3d_process(
    process_name: Union[str, List[str]] = "Prepar3D.exe",
) -> P3DProcessResult:
    """
    Scan running processes for any name in *process_name*.

    *process_name* may be a single string or a list of strings.
    All names are normalised (lower-case, `.exe` stripped) before comparison,
    so "Prepar3D.exe", "prepar3d.exe", "Prepar3D" and "prepar3d" are
    equivalent.

    CPU percent is sampled with a 1-second interval so the value reflects
    actual recent usage rather than a meaningless snapshot.

    The hang_suspected flag is set when:
      - The process is running
      - CPU usage rounds to 0 %
    This is a weak signal only — call it repeatedly before acting on it.
    """
    try:
        # Normalise input to a set of lowercase stems (no .exe)
        if isinstance(process_name, str):
            targets = {_normalize_name(process_name)}
        else:
            targets = {_normalize_name(n) for n in process_name}

        for proc in psutil.process_iter(["name", "pid"]):
            try:
                raw_name: Optional[str] = proc.info["name"]
                if raw_name and _normalize_name(raw_name) in targets:
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
                            matched_process_name=raw_name,
                        )
                    except psutil.AccessDenied:
                        # Process is running but stats are not readable under this account
                        logger.warning(
                            "AccessDenied reading stats for %s (pid=%s); "
                            "reporting as running with no stats",
                            raw_name,
                            proc.info["pid"],
                        )
                        return P3DProcessResult(
                            running=True,
                            pid=proc.info["pid"],
                            matched_process_name=raw_name,
                        )
            except psutil.NoSuchProcess:
                # Process vanished between iter and attribute access — skip it
                continue

        return P3DProcessResult(running=False)

    except Exception as exc:
        logger.error("P3D process check failed: %s", exc)
        return P3DProcessResult(running=False, error=str(exc))
