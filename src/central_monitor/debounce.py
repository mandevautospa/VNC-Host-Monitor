"""
Debounce / hysteresis layer for the central monitor.

Prevents the dashboard from flapping between HEALTHY and failure states due
to a single bad check.  Each check type (P3D, heartbeat, ping, VNC) has its
own consecutive-failure and consecutive-success counter.

Rules
-----
- After ``failure_threshold`` consecutive failures  → confirm the failure state.
- After fewer failures                               → WARNING (intermediate state).
- On first good check after a failure               → RECOVERING.
- After ``recovery_threshold`` consecutive successes → HEALTHY.

Public API
----------
  DebounceThresholds  — configurable thresholds (all with sensible defaults).
  HostDebounceState   — per-host mutable state (one instance per host).
  update_debounce_state()  — call once per poll cycle; returns the new HostStatus.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.common.models import HostStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable thresholds
# ---------------------------------------------------------------------------

@dataclass
class DebounceThresholds:
    """Failure / recovery count thresholds, loaded from central_config.json."""

    p3d_failure_threshold: int = 3
    p3d_recovery_threshold: int = 2
    heartbeat_failure_threshold: int = 3
    heartbeat_recovery_threshold: int = 2
    ping_failure_threshold: int = 3
    ping_recovery_threshold: int = 2
    vnc_failure_threshold: int = 3
    vnc_recovery_threshold: int = 2

    @classmethod
    def from_config(cls, config: dict) -> "DebounceThresholds":
        """Build a DebounceThresholds from a central_config dict.

        Supports both a flat layout (``"p3d_failure_threshold": 3`` at the top
        level) and a nested layout (``"debounce": {"p3d_failure_threshold": 3}``).
        The nested ``"debounce"`` sub-dict takes precedence when present.
        """
        merged = dict(config)
        if isinstance(config.get("debounce"), dict):
            merged.update(config["debounce"])
        return cls(
            p3d_failure_threshold=int(merged.get("p3d_failure_threshold", 3)),
            p3d_recovery_threshold=int(merged.get("p3d_recovery_threshold", 2)),
            heartbeat_failure_threshold=int(merged.get("heartbeat_failure_threshold", 3)),
            heartbeat_recovery_threshold=int(merged.get("heartbeat_recovery_threshold", 2)),
            ping_failure_threshold=int(merged.get("ping_failure_threshold", 3)),
            ping_recovery_threshold=int(merged.get("ping_recovery_threshold", 2)),
            vnc_failure_threshold=int(merged.get("vnc_failure_threshold", 3)),
            vnc_recovery_threshold=int(merged.get("vnc_recovery_threshold", 2)),
        )


# ---------------------------------------------------------------------------
# Per-host mutable state
# ---------------------------------------------------------------------------

@dataclass
class HostDebounceState:
    """Mutable per-host state tracked across poll cycles."""

    # P3D consecutive counters
    consecutive_p3d_failures: int = 0
    consecutive_p3d_successes: int = 0

    # Heartbeat consecutive counters
    consecutive_heartbeat_failures: int = 0
    consecutive_heartbeat_successes: int = 0

    # Ping consecutive counters
    consecutive_ping_failures: int = 0
    consecutive_ping_successes: int = 0

    # VNC consecutive counters
    consecutive_vnc_failures: int = 0
    consecutive_vnc_successes: int = 0

    # Tracking / display helpers
    last_known_good_p3d_status: bool = True
    last_successful_heartbeat_time: Optional[datetime] = field(default=None)
    last_status_change_time: Optional[datetime] = field(default=None)
    current_debounced_status: HostStatus = HostStatus.UNKNOWN
    last_matched_process_name: Optional[str] = field(default=None)
    last_config_path_used: Optional[str] = field(default=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAILURE_STATUSES: frozenset[HostStatus] = frozenset({
    HostStatus.HOST_UNREACHABLE,
    HostStatus.HOST_DOWN,
    HostStatus.HEARTBEAT_STALE,
    HostStatus.VNC_DOWN,
    HostStatus.P3D_CRASH_DETECTED,
    HostStatus.P3D_NOT_RUNNING,
    HostStatus.P3D_HANG_SUSPECTED,
    HostStatus.CRITICAL_CHECK_FAILED,
    HostStatus.RESOURCE_CRITICAL,
    HostStatus.RESOURCE_WARNING,
    HostStatus.WARNING,
})

_NON_FAILURE_STATUSES: frozenset[HostStatus] = frozenset({
    HostStatus.HEALTHY,
    HostStatus.RECOVERING,
    HostStatus.UNKNOWN,
})


def _is_failure_status(status: HostStatus) -> bool:
    return status in _FAILURE_STATUSES


def _log_transition(
    host_name: str,
    old_status: HostStatus,
    new_status: HostStatus,
    reason: str,
    state: HostDebounceState,
    hb_age: Optional[float],
    thresholds: DebounceThresholds,
    log: logging.Logger,
) -> None:
    """Emit a structured log line whenever the debounced status changes."""
    hb_age_str = f"{hb_age:.0f}s" if hb_age is not None else "unknown"
    log.info(
        "%s status changed %s -> %s: %s | "
        "p3d_failures=%d/%d p3d_successes=%d/%d "
        "hb_failures=%d/%d hb_successes=%d/%d "
        "ping_failures=%d/%d "
        "heartbeat_age=%s last_matched_process=%s",
        host_name,
        old_status,
        new_status,
        reason,
        state.consecutive_p3d_failures,
        thresholds.p3d_failure_threshold,
        state.consecutive_p3d_successes,
        thresholds.p3d_recovery_threshold,
        state.consecutive_heartbeat_failures,
        thresholds.heartbeat_failure_threshold,
        state.consecutive_heartbeat_successes,
        thresholds.heartbeat_recovery_threshold,
        state.consecutive_ping_failures,
        thresholds.ping_failure_threshold,
        hb_age_str,
        state.last_matched_process_name or "unknown",
    )


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def update_debounce_state(
    host_name: str,
    check_result: dict,
    state: HostDebounceState,
    thresholds: DebounceThresholds,
    raw_status: HostStatus,
    log: Optional[logging.Logger] = None,
) -> HostStatus:
    """
    Update *state* with the signals from *check_result* and return the
    debounced HostStatus.

    Parameters
    ----------
    host_name:     Display name used in log messages.
    check_result:  Dict built by _check_host(); contains "network",
                   "heartbeat", "host_reported" sub-dicts.
    state:         Per-host mutable state (mutated in place).
    thresholds:    Configurable failure / recovery thresholds.
    raw_status:    Output of evaluate_host_status() for this cycle.
    log:           Logger to use; falls back to module logger.

    Returns
    -------
    HostStatus  — the debounced status to use as the host's final status.
    """
    if log is None:
        log = logger

    try:
        return _compute_debounced_status(
            host_name, check_result, state, thresholds, raw_status, log
        )
    except Exception:
        log.error(
            "Unhandled exception in debounce logic for host %s:\n%s",
            host_name,
            traceback.format_exc(),
        )
        # Fall back to raw_status so we never silently hide a real problem.
        return raw_status


def _compute_debounced_status(
    host_name: str,
    check_result: dict,
    state: HostDebounceState,
    thresholds: DebounceThresholds,
    raw_status: HostStatus,
    log: logging.Logger,
) -> HostStatus:
    now = datetime.now(timezone.utc)
    network = check_result.get("network", {})
    heartbeat = check_result.get("heartbeat", {})
    host_reported = check_result.get("host_reported", {})

    ping_ok = network.get("ping_ok", False)
    vnc_ok = network.get("vnc_port_ok", False) and network.get("vnc_banner_ok", True)
    hb_exists = heartbeat.get("exists", False)
    hb_fresh = heartbeat.get("fresh", False)
    hb_age: Optional[float] = heartbeat.get("age_seconds")
    p3d_running = host_reported.get("p3d_running")  # True / False / None

    # Extract display metadata from heartbeat data ---------------------------
    hb_data = heartbeat.get("data") or {}
    p3d_data = hb_data.get("p3d", {}) if isinstance(hb_data, dict) else {}
    matched_proc = p3d_data.get("matched_process_name") if isinstance(p3d_data, dict) else None
    config_path = hb_data.get("config_path_used") if isinstance(hb_data, dict) else None

    if matched_proc:
        state.last_matched_process_name = matched_proc
    if config_path:
        state.last_config_path_used = config_path

    # ── Update per-check counters ────────────────────────────────────────────

    # Ping
    if ping_ok:
        state.consecutive_ping_failures = 0
        state.consecutive_ping_successes += 1
    else:
        state.consecutive_ping_failures += 1
        state.consecutive_ping_successes = 0

    # VNC (only penalise when ping is up so we distinguish network from VNC)
    if ping_ok:
        if vnc_ok:
            state.consecutive_vnc_failures = 0
            state.consecutive_vnc_successes += 1
        else:
            state.consecutive_vnc_failures += 1
            state.consecutive_vnc_successes = 0

    # Heartbeat freshness (only penalise when file is known to exist)
    if hb_fresh:
        state.consecutive_heartbeat_failures = 0
        state.consecutive_heartbeat_successes += 1
        state.last_successful_heartbeat_time = now
    elif hb_exists:
        state.consecutive_heartbeat_failures += 1
        state.consecutive_heartbeat_successes = 0

    # P3D running (only when we have a non-None value from the heartbeat)
    if p3d_running is True:
        state.last_known_good_p3d_status = True
        state.consecutive_p3d_failures = 0
        state.consecutive_p3d_successes += 1
    elif p3d_running is False:
        state.consecutive_p3d_failures += 1
        state.consecutive_p3d_successes = 0

    # ── Determine new debounced status (priority order) ───────────────────────

    new_status = _resolve_status(
        state, thresholds, raw_status,
        ping_ok=ping_ok, vnc_ok=vnc_ok,
        hb_exists=hb_exists, hb_fresh=hb_fresh,
        p3d_running=p3d_running,
        host_reported=host_reported,
    )

    # ── Detect transition and log ─────────────────────────────────────────────
    old_status = state.current_debounced_status
    if new_status != old_status:
        reason = _build_reason(
            old_status, new_status, state, thresholds,
            ping_ok=ping_ok, hb_fresh=hb_fresh, hb_exists=hb_exists, p3d_running=p3d_running,
            hb_age=hb_age,
        )
        _log_transition(host_name, old_status, new_status, reason, state, hb_age, thresholds, log)
        state.last_status_change_time = now
        state.current_debounced_status = new_status

    return new_status


def _resolve_status(
    state: HostDebounceState,
    thresholds: DebounceThresholds,
    raw_status: HostStatus,
    *,
    ping_ok: bool,
    vnc_ok: bool,
    hb_exists: bool,
    hb_fresh: bool,
    p3d_running: Optional[bool],
    host_reported: dict,
) -> HostStatus:
    """Derive the debounced status from the current counters and raw signal."""
    old = state.current_debounced_status

    # ── 1. PING ──────────────────────────────────────────────────────────────
    if not ping_ok:
        if state.consecutive_ping_failures >= thresholds.ping_failure_threshold:
            return HostStatus.HOST_UNREACHABLE
        return HostStatus.WARNING

    # Ping is now OK — if we were HOST_UNREACHABLE, start recovery
    if old == HostStatus.HOST_UNREACHABLE:
        if state.consecutive_ping_successes >= thresholds.ping_recovery_threshold:
            pass  # fall through to re-evaluate
        else:
            return HostStatus.RECOVERING

    # ── 2. HEARTBEAT staleness ────────────────────────────────────────────────
    if hb_exists and not hb_fresh:
        if state.consecutive_heartbeat_failures >= thresholds.heartbeat_failure_threshold:
            return HostStatus.HOST_DOWN
        return HostStatus.WARNING

    # ── 3. VNC ────────────────────────────────────────────────────────────────
    if not vnc_ok:
        if state.consecutive_vnc_failures >= thresholds.vnc_failure_threshold:
            return HostStatus.VNC_DOWN
        return HostStatus.WARNING

    # ── 4. P3D crash (always immediate — crash events are definitive) ─────────
    crash_count = host_reported.get("recent_app_crash_count") or 0
    if crash_count > 0:
        return HostStatus.P3D_CRASH_DETECTED

    # ── 5. P3D not running (debounced) ───────────────────────────────────────
    if p3d_running is False:
        if state.consecutive_p3d_failures >= thresholds.p3d_failure_threshold:
            return HostStatus.P3D_NOT_RUNNING
        return HostStatus.WARNING

    # ── 6. P3D hang (immediate — hang events are definitive) ─────────────────
    hang_suspected = host_reported.get("p3d_hang_suspected", False)
    hang_count = host_reported.get("recent_app_hang_count") or 0
    if hang_suspected or hang_count > 0:
        return HostStatus.P3D_HANG_SUSPECTED

    # ── 7/8. Resource levels (pass through from raw_status) ──────────────────
    if raw_status in (HostStatus.RESOURCE_CRITICAL, HostStatus.RESOURCE_WARNING,
                      HostStatus.CRITICAL_CHECK_FAILED):
        return raw_status

    # ── All checks pass — determine whether RECOVERING or HEALTHY ─────────────
    was_failing = _is_failure_status(old)

    if was_failing or old == HostStatus.RECOVERING:
        # Require simultaneous recovery of all signals we track
        p3d_ok = (
            p3d_running is True
            and state.consecutive_p3d_successes >= thresholds.p3d_recovery_threshold
        ) or p3d_running is None  # no P3D data — don't block recovery on it

        hb_ok = (
            hb_fresh
            and state.consecutive_heartbeat_successes >= thresholds.heartbeat_recovery_threshold
        ) or not hb_exists  # heartbeat not configured — don't block recovery

        ping_ok_recovered = state.consecutive_ping_successes >= thresholds.ping_recovery_threshold
        vnc_ok_recovered = state.consecutive_vnc_successes >= thresholds.vnc_recovery_threshold

        if p3d_ok and hb_ok and ping_ok_recovered and vnc_ok_recovered:
            return HostStatus.HEALTHY
        return HostStatus.RECOVERING

    return HostStatus.HEALTHY


def _build_reason(
    old: HostStatus,
    new: HostStatus,
    state: HostDebounceState,
    thresholds: DebounceThresholds,
    *,
    ping_ok: bool,
    hb_fresh: bool,
    hb_exists: bool,
    p3d_running: Optional[bool],
    hb_age: Optional[float],
) -> str:
    """Compose a human-readable reason string for a status transition."""
    proc = state.last_matched_process_name or "unknown"
    hb_age_str = f"{hb_age:.0f}s" if hb_age is not None else "unknown"

    if new == HostStatus.HOST_UNREACHABLE:
        return (
            f"Ping unresponsive for {state.consecutive_ping_failures} "
            f"consecutive checks (threshold={thresholds.ping_failure_threshold})"
        )
    if new == HostStatus.HOST_DOWN:
        return (
            f"Heartbeat stale for {state.consecutive_heartbeat_failures} "
            f"consecutive checks (threshold={thresholds.heartbeat_failure_threshold})"
        )
    if new == HostStatus.HEARTBEAT_STALE:
        return "Heartbeat file exists but is too old"
    if new == HostStatus.VNC_DOWN:
        return (
            f"VNC unresponsive for {state.consecutive_vnc_failures} "
            f"consecutive checks (threshold={thresholds.vnc_failure_threshold})"
        )
    if new == HostStatus.P3D_NOT_RUNNING:
        return (
            f"P3D missing for {state.consecutive_p3d_failures} consecutive checks "
            f"(threshold={thresholds.p3d_failure_threshold}), "
            f"heartbeat_age={hb_age_str}"
        )
    if new == HostStatus.WARNING:
        if not ping_ok:
            return f"Ping failing, missed_ping_checks={state.consecutive_ping_failures}/{thresholds.ping_failure_threshold}"
        if hb_exists and not hb_fresh:
            return (
                f"Heartbeat stale, missed_hb_checks="
                f"{state.consecutive_heartbeat_failures}/{thresholds.heartbeat_failure_threshold}"
            )
        if p3d_running is False:
            return (
                f"P3D not detected this cycle, "
                f"missed_p3d_checks={state.consecutive_p3d_failures}/{thresholds.p3d_failure_threshold}, "
                f"last_matched_process={proc}"
            )
        return "One or more checks degraded"
    if new == HostStatus.RECOVERING:
        return (
            f"P3D detected again, "
            f"recovery_checks={state.consecutive_p3d_successes}/{thresholds.p3d_recovery_threshold}, "
            f"matched_process={proc}"
        )
    if new == HostStatus.HEALTHY:
        if old == HostStatus.RECOVERING:
            return (
                f"P3D detected for {state.consecutive_p3d_successes} consecutive checks "
                f"and heartbeat is fresh"
            )
        return "All checks passed"
    return f"Transitioned from {old}"
