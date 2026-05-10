"""
Unit tests for state_evaluator.evaluate_host_status().

All tests run without real network access.  Each test passes a hand-crafted
result dict that matches the structure built by central_monitor._check_host().
"""

import pytest
from src.common.models import HostStatus
from src.central_monitor.state_evaluator import evaluate_host_status


def _make(
    ping_ok: bool = True,
    vnc_port_ok: bool = True,
    vnc_banner_ok: bool = True,
    hb_exists: bool = True,
    hb_fresh: bool = True,
    p3d_running: bool = True,
    hang_suspected: bool = False,
    crash_count: int = 0,
    hang_count: int = 0,
    reported_status: str = "HEALTHY",
) -> dict:
    """Helper: build a minimal result dict for evaluate_host_status()."""
    return {
        "network": {
            "ping_ok": ping_ok,
            "vnc_port_ok": vnc_port_ok,
            "vnc_banner_ok": vnc_banner_ok,
        },
        "heartbeat": {
            "exists": hb_exists,
            "fresh": hb_fresh,
        },
        "host_reported": {
            "status": reported_status,
            "p3d_running": p3d_running,
            "p3d_hang_suspected": hang_suspected,
            "recent_app_crash_count": crash_count,
            "recent_app_hang_count": hang_count,
        },
    }


# ── Baseline ──────────────────────────────────────────────────────────────────

def test_fully_healthy():
    assert evaluate_host_status(_make()) == HostStatus.HEALTHY


# ── Priority 1: HOST_UNREACHABLE ─────────────────────────────────────────────

def test_ping_fails():
    assert evaluate_host_status(_make(ping_ok=False)) == HostStatus.HOST_UNREACHABLE

def test_ping_fails_overrides_vnc_down():
    assert evaluate_host_status(_make(ping_ok=False, vnc_port_ok=False)) == HostStatus.HOST_UNREACHABLE

def test_ping_fails_overrides_p3d_not_running():
    assert evaluate_host_status(_make(ping_ok=False, p3d_running=False)) == HostStatus.HOST_UNREACHABLE


# ── Priority 2: HEARTBEAT_STALE ──────────────────────────────────────────────

def test_stale_heartbeat():
    assert evaluate_host_status(_make(hb_fresh=False)) == HostStatus.HEARTBEAT_STALE

def test_stale_beats_vnc_down():
    assert evaluate_host_status(_make(hb_fresh=False, vnc_port_ok=False)) == HostStatus.HEARTBEAT_STALE

def test_missing_heartbeat_file_not_stale():
    # hb_exists=False means the file is not present at all — do not penalise with STALE
    result = _make(hb_exists=False, hb_fresh=False)
    # Should fall through to a network-only evaluation
    assert evaluate_host_status(result) != HostStatus.HEARTBEAT_STALE


# ── Priority 3: VNC_DOWN ─────────────────────────────────────────────────────

def test_vnc_port_closed():
    assert evaluate_host_status(_make(vnc_port_ok=False)) == HostStatus.VNC_DOWN

def test_vnc_bad_banner_is_down():
    assert evaluate_host_status(_make(vnc_port_ok=True, vnc_banner_ok=False)) == HostStatus.VNC_DOWN

def test_vnc_banner_missing_field_backward_compatible():
    result = _make()
    result["network"].pop("vnc_banner_ok")
    assert evaluate_host_status(result) == HostStatus.HEALTHY


# ── Priority 4: P3D_CRASH_DETECTED ───────────────────────────────────────────

def test_crash_detected():
    assert evaluate_host_status(_make(crash_count=1)) == HostStatus.P3D_CRASH_DETECTED

def test_crash_beats_not_running():
    # Crash takes priority over P3D_NOT_RUNNING
    assert evaluate_host_status(_make(crash_count=2, p3d_running=False)) == HostStatus.P3D_CRASH_DETECTED


# ── Priority 5: P3D_NOT_RUNNING ──────────────────────────────────────────────

def test_p3d_not_running():
    assert evaluate_host_status(_make(p3d_running=False)) == HostStatus.P3D_NOT_RUNNING


# ── Priority 6: P3D_HANG_SUSPECTED ───────────────────────────────────────────

def test_hang_flag():
    assert evaluate_host_status(_make(hang_suspected=True)) == HostStatus.P3D_HANG_SUSPECTED

def test_hang_via_event_count():
    assert evaluate_host_status(_make(hang_count=1)) == HostStatus.P3D_HANG_SUSPECTED


# ── Priority 7 / 8: RESOURCE levels ─────────────────────────────────────────

def test_resource_critical():
    assert evaluate_host_status(_make(reported_status="RESOURCE_CRITICAL")) == HostStatus.RESOURCE_CRITICAL

def test_resource_warning():
    assert evaluate_host_status(_make(reported_status="RESOURCE_WARNING")) == HostStatus.RESOURCE_WARNING


# ── Priority 9: WARNING ───────────────────────────────────────────────────────

def test_generic_warning():
    assert evaluate_host_status(_make(reported_status="WARNING")) == HostStatus.WARNING

def test_critical_check_failed_status():
    assert evaluate_host_status(_make(reported_status="CRITICAL_CHECK_FAILED")) == HostStatus.CRITICAL_CHECK_FAILED


# ── No heartbeat data at all ─────────────────────────────────────────────────

def test_no_host_reported_data_healthy():
    result = {
        "network": {"ping_ok": True, "vnc_port_ok": True},
        "heartbeat": {"exists": False, "fresh": False},
        "host_reported": {},
    }
    assert evaluate_host_status(result) == HostStatus.HEALTHY
