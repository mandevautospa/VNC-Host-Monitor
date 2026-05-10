"""
Resource threshold definitions and single-value evaluators.

The Thresholds dataclass holds all configurable limits.
Each evaluate_* function returns "OK", "WARNING", or "CRITICAL".

Usage:
    from src.common.thresholds import Thresholds, evaluate_cpu, evaluate_ram, evaluate_disk

    t = Thresholds(**config.get("thresholds", {}))
    level = evaluate_cpu(cpu_percent, t)
"""

from dataclasses import dataclass


@dataclass
class Thresholds:
    cpu_warning_percent: float = 85.0
    cpu_critical_percent: float = 95.0
    ram_warning_percent: float = 85.0
    ram_critical_percent: float = 92.0
    disk_warning_free_percent: float = 20.0
    disk_critical_free_percent: float = 10.0
    disk_warning_free_gb: float = 20.0
    disk_critical_free_gb: float = 10.0


def evaluate_cpu(cpu_percent: float, thresholds: Thresholds) -> str:
    if cpu_percent >= thresholds.cpu_critical_percent:
        return "CRITICAL"
    if cpu_percent >= thresholds.cpu_warning_percent:
        return "WARNING"
    return "OK"


def evaluate_ram(ram_percent: float, thresholds: Thresholds) -> str:
    if ram_percent >= thresholds.ram_critical_percent:
        return "CRITICAL"
    if ram_percent >= thresholds.ram_warning_percent:
        return "WARNING"
    return "OK"


def evaluate_disk(disk_free_percent: float, disk_free_gb: float, thresholds: Thresholds) -> str:
    """
    Evaluate disk health by checking both percentage and GB free space.
    
    Returns CRITICAL if EITHER metric falls below its critical threshold,
    ensuring that problems are caught whether they manifest as a low percentage
    (e.g., on a small volume) or low absolute GB (e.g., on a large volume).
    
    Example:
        - A 1TB drive with 50GB free: 5% free but 50GB available
        - With defaults (10% / 10GB critical): CRITICAL on both metrics
        - A 100GB drive with 5GB free: 5% free and 5GB available
        - With defaults: CRITICAL on both metrics
    
    This OR-logic ensures we catch capacity issues regardless of volume size.
    """
    if (
        disk_free_percent <= thresholds.disk_critical_free_percent
        or disk_free_gb <= thresholds.disk_critical_free_gb
    ):
        return "CRITICAL"
    if (
        disk_free_percent <= thresholds.disk_warning_free_percent
        or disk_free_gb <= thresholds.disk_warning_free_gb
    ):
        return "WARNING"
    return "OK"
