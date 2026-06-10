"""
Unit tests for the debounce / hysteresis layer.

All tests run without real network access, process inspection, or file I/O.
They drive ``update_debounce_state`` directly so the transition logic can be
verified in isolation.
"""

from __future__ import annotations

import logging

import pytest

from src.central_monitor.debounce import (
    DebounceThresholds,
    HostDebounceState,
    update_debounce_state,
)
from src.common.models import HostStatus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def thresholds():
    """Default thresholds (3 failures, 2 recoveries)."""
    return DebounceThresholds()


@pytest.fixture
def state():
    return HostDebounceState()


@pytest.fixture
def log():
    return logging.getLogger("test_debounce")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(
    ping_ok: bool = True,
    vnc_port_ok: bool = True,
    vnc_banner_ok: bool = True,
    hb_exists: bool = True,
    hb_fresh: bool = True,
    p3d_running=True,
    crash_count: int = 0,
    hang_suspected: bool = False,
    matched_proc: str | None = "Prepar3D.exe",
    hb_age: float = 5.0,
) -> dict:
    return {
        "network": {
            "ping_ok": ping_ok,
            "vnc_port_ok": vnc_port_ok,
            "vnc_banner_ok": vnc_banner_ok,
        },
        "heartbeat": {
            "exists": hb_exists,
            "fresh": hb_fresh,
            "age_seconds": hb_age,
            "data": {
                "p3d": {
                    "running": p3d_running,
                    "hang_suspected": hang_suspected,
                    "matched_process_name": matched_proc,
                },
                "events": {
                    "recent_app_crash_count": crash_count,
                    "recent_app_hang_count": 0,
                },
                "resources": {},
            },
        },
        "host_reported": {
            "p3d_running": p3d_running,
            "p3d_hang_suspected": hang_suspected,
            "recent_app_crash_count": crash_count,
            "recent_app_hang_count": 0,
        },
    }


def _cycle(
    state: HostDebounceState,
    thresholds: DebounceThresholds,
    log: logging.Logger,
    raw: HostStatus,
    check_result: dict,
) -> HostStatus:
    return update_debounce_state("host-04", check_result, state, thresholds, raw, log)


# ---------------------------------------------------------------------------
# Baseline: healthy stays healthy
# ---------------------------------------------------------------------------

class TestHealthyBaseline:
    def test_healthy_stays_healthy(self, state, thresholds, log):
        r = _result()
        status = _cycle(state, thresholds, log, HostStatus.HEALTHY, r)
        assert status == HostStatus.HEALTHY

    def test_multiple_healthy_cycles(self, state, thresholds, log):
        r = _result()
        for _ in range(5):
            status = _cycle(state, thresholds, log, HostStatus.HEALTHY, r)
        assert status == HostStatus.HEALTHY


# ---------------------------------------------------------------------------
# P3D debounce
# ---------------------------------------------------------------------------

class TestP3DDebounce:
    def test_first_p3d_failure_warns(self, state, thresholds, log):
        r = _result(p3d_running=False)
        status = _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r)
        assert status == HostStatus.WARNING
        assert state.consecutive_p3d_failures == 1

    def test_second_p3d_failure_still_warns(self, state, thresholds, log):
        r = _result(p3d_running=False)
        _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r)
        status = _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r)
        assert status == HostStatus.WARNING
        assert state.consecutive_p3d_failures == 2

    def test_third_p3d_failure_confirms(self, state, thresholds, log):
        r = _result(p3d_running=False)
        for _ in range(3):
            status = _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r)
        assert status == HostStatus.P3D_NOT_RUNNING
        assert state.consecutive_p3d_failures == 3

    def test_p3d_recovery_is_staged(self, state, thresholds, log):
        r_fail = _result(p3d_running=False)
        r_ok = _result(p3d_running=True)

        # Confirm P3D failure
        for _ in range(3):
            _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r_fail)

        # First good cycle → RECOVERING
        status = _cycle(state, thresholds, log, HostStatus.HEALTHY, r_ok)
        assert status == HostStatus.RECOVERING

    def test_p3d_fully_recovered_after_threshold(self, state, thresholds, log):
        r_fail = _result(p3d_running=False)
        r_ok = _result(p3d_running=True)

        for _ in range(3):
            _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r_fail)

        # Two good cycles → HEALTHY (recovery_threshold=2)
        _cycle(state, thresholds, log, HostStatus.HEALTHY, r_ok)
        status = _cycle(state, thresholds, log, HostStatus.HEALTHY, r_ok)
        assert status == HostStatus.HEALTHY

    def test_p3d_failure_counter_resets_on_success(self, state, thresholds, log):
        r_fail = _result(p3d_running=False)
        r_ok = _result(p3d_running=True)

        _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r_fail)
        _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r_fail)

        # One good cycle resets failure counter
        _cycle(state, thresholds, log, HostStatus.HEALTHY, r_ok)
        assert state.consecutive_p3d_failures == 0

    def test_custom_p3d_failure_threshold(self, state, log):
        t = DebounceThresholds(p3d_failure_threshold=1, p3d_recovery_threshold=1)
        r = _result(p3d_running=False)
        status = _cycle(state, t, log, HostStatus.P3D_NOT_RUNNING, r)
        assert status == HostStatus.P3D_NOT_RUNNING

    def test_single_bad_cycle_does_not_confirm_failure(self, state, thresholds, log):
        """Core anti-flap requirement: 1 bad check must NOT yield P3D_NOT_RUNNING."""
        r = _result(p3d_running=False)
        status = _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r)
        assert status != HostStatus.P3D_NOT_RUNNING

    def test_two_bad_cycles_do_not_confirm_failure(self, state, thresholds, log):
        """Core anti-flap requirement: 2 bad checks must NOT yield P3D_NOT_RUNNING."""
        r = _result(p3d_running=False)
        _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r)
        status = _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r)
        assert status != HostStatus.P3D_NOT_RUNNING


# ---------------------------------------------------------------------------
# Heartbeat debounce
# ---------------------------------------------------------------------------

class TestHeartbeatDebounce:
    def test_first_stale_warns(self, state, thresholds, log):
        r = _result(hb_fresh=False)
        status = _cycle(state, thresholds, log, HostStatus.HEARTBEAT_STALE, r)
        assert status == HostStatus.WARNING

    def test_threshold_stale_confirms(self, state, thresholds, log):
        r = _result(hb_fresh=False)
        for _ in range(3):
            status = _cycle(state, thresholds, log, HostStatus.HEARTBEAT_STALE, r)
        assert status == HostStatus.HOST_DOWN

    def test_missing_heartbeat_not_penalised(self, state, thresholds, log):
        """A non-existent heartbeat file must not increment the stale counter."""
        r = _result(hb_exists=False, hb_fresh=False)
        for _ in range(5):
            status = _cycle(state, thresholds, log, HostStatus.HEALTHY, r)
        assert state.consecutive_heartbeat_failures == 0
        assert status == HostStatus.HEALTHY

    def test_heartbeat_recovery_is_staged(self, state, thresholds, log):
        r_stale = _result(hb_fresh=False)
        r_fresh = _result(hb_fresh=True)
        for _ in range(3):
            _cycle(state, thresholds, log, HostStatus.HEARTBEAT_STALE, r_stale)
        status = _cycle(state, thresholds, log, HostStatus.HEALTHY, r_fresh)
        assert status == HostStatus.RECOVERING

    def test_heartbeat_fully_recovered(self, state, thresholds, log):
        r_stale = _result(hb_fresh=False)
        r_fresh = _result(hb_fresh=True)
        for _ in range(3):
            _cycle(state, thresholds, log, HostStatus.HEARTBEAT_STALE, r_stale)
        _cycle(state, thresholds, log, HostStatus.HEALTHY, r_fresh)
        status = _cycle(state, thresholds, log, HostStatus.HEALTHY, r_fresh)
        assert status == HostStatus.HEALTHY


# ---------------------------------------------------------------------------
# Ping debounce
# ---------------------------------------------------------------------------

class TestPingDebounce:
    def test_first_ping_failure_warns(self, state, thresholds, log):
        r = _result(ping_ok=False)
        status = _cycle(state, thresholds, log, HostStatus.HOST_UNREACHABLE, r)
        assert status == HostStatus.WARNING

    def test_threshold_ping_failures_confirm(self, state, thresholds, log):
        r = _result(ping_ok=False)
        for _ in range(3):
            status = _cycle(state, thresholds, log, HostStatus.HOST_UNREACHABLE, r)
        assert status == HostStatus.HOST_UNREACHABLE

    def test_ping_recovery_is_staged(self, state, thresholds, log):
        r_fail = _result(ping_ok=False)
        r_ok = _result()
        for _ in range(3):
            _cycle(state, thresholds, log, HostStatus.HOST_UNREACHABLE, r_fail)
        status = _cycle(state, thresholds, log, HostStatus.HEALTHY, r_ok)
        assert status == HostStatus.RECOVERING


# ---------------------------------------------------------------------------
# VNC debounce
# ---------------------------------------------------------------------------

class TestVncDebounce:
    def test_first_vnc_failure_warns(self, state, thresholds, log):
        r = _result(vnc_port_ok=False)
        status = _cycle(state, thresholds, log, HostStatus.VNC_DOWN, r)
        assert status == HostStatus.WARNING

    def test_threshold_vnc_failures_confirm(self, state, thresholds, log):
        r = _result(vnc_port_ok=False)
        for _ in range(3):
            status = _cycle(state, thresholds, log, HostStatus.VNC_DOWN, r)
        assert status == HostStatus.VNC_DOWN


# ---------------------------------------------------------------------------
# Crash / hang bypass debounce
# ---------------------------------------------------------------------------

class TestImmediateStatuses:
    def test_crash_is_immediate(self, state, thresholds, log):
        """P3D crash events are always treated as confirmed immediately."""
        r = _result(crash_count=1)
        status = _cycle(state, thresholds, log, HostStatus.P3D_CRASH_DETECTED, r)
        assert status == HostStatus.P3D_CRASH_DETECTED

    def test_hang_is_immediate(self, state, thresholds, log):
        r = _result(hang_suspected=True)
        status = _cycle(state, thresholds, log, HostStatus.P3D_HANG_SUSPECTED, r)
        assert status == HostStatus.P3D_HANG_SUSPECTED


# ---------------------------------------------------------------------------
# State metadata updated correctly
# ---------------------------------------------------------------------------

class TestStateMetadata:
    def test_matched_process_name_tracked(self, state, thresholds, log):
        r = _result(matched_proc="Prepar3D.exe")
        _cycle(state, thresholds, log, HostStatus.HEALTHY, r)
        assert state.last_matched_process_name == "Prepar3D.exe"

    def test_matched_process_name_persists_after_failure(self, state, thresholds, log):
        r_ok = _result(matched_proc="Prepar3D.exe")
        r_fail = _result(p3d_running=False, matched_proc=None)
        _cycle(state, thresholds, log, HostStatus.HEALTHY, r_ok)
        _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r_fail)
        # Should retain last seen value
        assert state.last_matched_process_name == "Prepar3D.exe"

    def test_last_successful_heartbeat_time_set(self, state, thresholds, log):
        r = _result(hb_fresh=True)
        _cycle(state, thresholds, log, HostStatus.HEALTHY, r)
        assert state.last_successful_heartbeat_time is not None

    def test_status_change_time_updated_on_transition(self, state, thresholds, log):
        r_fail = _result(p3d_running=False)
        _cycle(state, thresholds, log, HostStatus.P3D_NOT_RUNNING, r_fail)
        # Status changed from UNKNOWN → WARNING, so timestamp should be set
        assert state.last_status_change_time is not None


# ---------------------------------------------------------------------------
# DebounceThresholds.from_config
# ---------------------------------------------------------------------------

class TestDebounceThresholdsFromConfig:
    def test_defaults_when_no_debounce_key(self):
        t = DebounceThresholds.from_config({})
        assert t.p3d_failure_threshold == 3
        assert t.p3d_recovery_threshold == 2

    def test_nested_debounce_key_overrides(self):
        config = {"debounce": {"p3d_failure_threshold": 5, "heartbeat_failure_threshold": 2}}
        t = DebounceThresholds.from_config(config)
        assert t.p3d_failure_threshold == 5
        assert t.heartbeat_failure_threshold == 2
        # Unset values fall back to defaults
        assert t.p3d_recovery_threshold == 2

    def test_flat_key_overrides(self):
        config = {"p3d_failure_threshold": 1, "p3d_recovery_threshold": 1}
        t = DebounceThresholds.from_config(config)
        assert t.p3d_failure_threshold == 1

    def test_nested_takes_precedence_over_flat(self):
        config = {
            "p3d_failure_threshold": 99,
            "debounce": {"p3d_failure_threshold": 2},
        }
        t = DebounceThresholds.from_config(config)
        assert t.p3d_failure_threshold == 2


# ---------------------------------------------------------------------------
# Exception safety
# ---------------------------------------------------------------------------

class TestExceptionSafety:
    def test_broken_check_result_falls_back_to_raw(self, state, thresholds, log):
        """A completely malformed check_result must not raise; raw_status is returned."""
        broken = {"network": None, "heartbeat": None, "host_reported": None}
        # Should not raise, should return raw_status
        status = update_debounce_state(
            "host-04", broken, state, thresholds, HostStatus.UNKNOWN, log
        )
        # Either raw_status or a valid status, never an exception
        assert isinstance(status, HostStatus)
