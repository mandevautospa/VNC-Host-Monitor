"""Unit tests for central alert threshold and incident de-duplication transitions."""

from datetime import datetime

from src.common.models import HostStatus
from src.central_monitor.central_monitor import (
    _is_within_active_hours,
    _select_alert_threshold,
    _update_incident_state,
)


def test_active_hours_day_window_true_and_false():
    cfg = {"active_hours": {"enabled": True, "start": "07:00", "end": "18:00"}}
    assert _is_within_active_hours(cfg, now=datetime(2026, 5, 10, 12, 0, 0))
    assert not _is_within_active_hours(cfg, now=datetime(2026, 5, 10, 22, 0, 0))


def test_active_hours_overnight_window():
    cfg = {"active_hours": {"enabled": True, "start": "22:00", "end": "06:00"}}
    assert _is_within_active_hours(cfg, now=datetime(2026, 5, 10, 23, 0, 0))
    assert _is_within_active_hours(cfg, now=datetime(2026, 5, 10, 3, 0, 0))
    assert not _is_within_active_hours(cfg, now=datetime(2026, 5, 10, 12, 0, 0))


def test_active_hours_invalid_time_falls_back_to_true():
    cfg = {"active_hours": {"enabled": True, "start": "bad", "end": "18:00"}}
    assert _is_within_active_hours(cfg, now=datetime(2026, 5, 10, 12, 0, 0))


def test_p3d_not_running_threshold_respects_active_hours():
    normal = _select_alert_threshold(
        HostStatus.P3D_NOT_RUNNING,
        alert_threshold=3,
        critical_threshold=2,
        is_active_hours=False,
    )
    active = _select_alert_threshold(
        HostStatus.P3D_NOT_RUNNING,
        alert_threshold=3,
        critical_threshold=2,
        is_active_hours=True,
    )
    assert normal == 3
    assert active == 2


def test_alert_dedup_same_incident():
    first = _update_incident_state(
        final_status=HostStatus.HOST_UNREACHABLE,
        prev_status=HostStatus.HEALTHY,
        failure_count=2,
        threshold=2,
        incident_status=None,
        alert_sent_for_incident=False,
    )
    assert first["should_alert"]
    assert first["incident_status"] == HostStatus.HOST_UNREACHABLE

    second = _update_incident_state(
        final_status=HostStatus.HOST_UNREACHABLE,
        prev_status=HostStatus.HOST_UNREACHABLE,
        failure_count=3,
        threshold=2,
        incident_status=first["incident_status"],
        alert_sent_for_incident=True,
    )
    assert not second["should_alert"]
    assert second["incident_status"] == HostStatus.HOST_UNREACHABLE


def test_alert_retry_when_not_sent_yet():
    # Incident is already active but no alert has been successfully sent yet.
    r = _update_incident_state(
        final_status=HostStatus.HOST_UNREACHABLE,
        prev_status=HostStatus.HOST_UNREACHABLE,
        failure_count=4,
        threshold=2,
        incident_status=HostStatus.HOST_UNREACHABLE,
        alert_sent_for_incident=False,
    )
    assert r["should_alert"]


def test_new_unhealthy_status_starts_new_incident():
    changed = _update_incident_state(
        final_status=HostStatus.VNC_DOWN,
        prev_status=HostStatus.HOST_UNREACHABLE,
        failure_count=3,
        threshold=3,
        incident_status=HostStatus.HOST_UNREACHABLE,
        alert_sent_for_incident=True,
    )
    assert changed["should_alert"]
    assert changed["incident_status"] == HostStatus.VNC_DOWN


def test_recovery_transition_clears_incident_state():
    recovered = _update_incident_state(
        final_status=HostStatus.HEALTHY,
        prev_status=HostStatus.VNC_DOWN,
        failure_count=0,
        threshold=3,
        incident_status=HostStatus.VNC_DOWN,
        alert_sent_for_incident=True,
    )
    assert recovered["recovered"]
    assert recovered["incident_status"] is None
