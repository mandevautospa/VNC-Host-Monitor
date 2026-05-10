"""Sanity checks for host watchdog module import and fail-safe classification."""

from types import SimpleNamespace

from src.common.thresholds import Thresholds
from src.host_agent.host_watchdog import _classify_local_status


def test_host_watchdog_module_classification_fail_safe_errors():
    status = _classify_local_status(
        p3d=SimpleNamespace(running=True, hang_suspected=False),
        resources=SimpleNamespace(cpu_percent=10.0, ram_percent=20.0, disk_free_percent=80.0, disk_free_gb=100.0),
        events=SimpleNamespace(recent_app_crash_count=0),
        thresholds=Thresholds(),
        has_core_check_errors=True,
    )
    assert status == "CRITICAL_CHECK_FAILED"


def test_host_watchdog_module_classification_healthy_without_errors():
    status = _classify_local_status(
        p3d=SimpleNamespace(running=True, hang_suspected=False),
        resources=SimpleNamespace(cpu_percent=10.0, ram_percent=20.0, disk_free_percent=80.0, disk_free_gb=100.0),
        events=SimpleNamespace(recent_app_crash_count=0),
        thresholds=Thresholds(),
        has_core_check_errors=False,
    )
    assert status == "HEALTHY"