"""
DIS (Distributed Interactive Simulation) session-layer health monitoring.

This module provides passive, read-only DIS traffic monitoring so the central
monitor can distinguish between:
  - P3D process running (OS-level)
  - P3D DIS/multiplayer session traffic appearing healthy (network-level)

Safety design principles
------------------------
* NO packets are ever sent.
* NO UDP port 3000 binding that could conflict with P3D.
* NO multicast group joins unless explicitly enabled in config.
* NO host-side agent changes required.
* If data is unavailable the status is DIS_UNKNOWN — the monitor continues normally.
* All exceptions are caught and converted to DIS_ERROR without crashing the monitor.

Status values
-------------
DIS_ACTIVE   — recent packet/byte deltas are above the configured threshold.
DIS_QUIET    — P3D running but packet/byte deltas have been zero for the quiet window.
DIS_STALLED  — traffic was previously active, then dropped to zero for the stall window.
DIS_UNKNOWN  — DIS monitoring is enabled but data could not be safely collected.
DIS_DISABLED — DIS monitoring is disabled in config (or for this host).
DIS_ERROR    — an exception occurred; logged but host is not marked as failed.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class DisStatus(str, Enum):
    """Possible DIS/session health states."""

    DIS_ACTIVE = "DIS_ACTIVE"
    DIS_QUIET = "DIS_QUIET"
    DIS_STALLED = "DIS_STALLED"
    DIS_UNKNOWN = "DIS_UNKNOWN"
    DIS_DISABLED = "DIS_DISABLED"
    DIS_ERROR = "DIS_ERROR"


# ---------------------------------------------------------------------------
# Raw sample returned by a collector
# ---------------------------------------------------------------------------

@dataclass
class DisSample:
    """
    Raw DIS traffic sample from a passive collector.

    All numeric fields are ``None`` when data is unavailable.
    ``available`` is ``False`` when the collector could not obtain data at all.
    """

    available: bool = False
    packets_total: Optional[int] = None
    bytes_total: Optional[int] = None
    collection_time: float = field(default_factory=time.monotonic)
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Collector abstraction
# ---------------------------------------------------------------------------

class DisCollector(ABC):
    """
    Abstract passive collector that returns a :class:`DisSample`.

    Implementations must be read-only and must never:
    - Send packets
    - Bind to UDP port 3000 in a way that conflicts with P3D
    - Join or modify multicast groups (unless explicitly enabled in config)
    - Restart any service or process
    """

    @abstractmethod
    def collect(self, host_name: str) -> DisSample:
        """Return a :class:`DisSample` for *host_name*.

        Must never raise — catch all exceptions and return a sample with
        ``available=False`` and ``error`` set.
        """


class PlaceholderCollector(DisCollector):
    """
    Safe no-op collector used when no real data source is available.

    Always returns ``available=False`` so the classifier produces DIS_UNKNOWN.
    This is the default for the first rollout, especially on host-01 while
    students are flying.
    """

    def collect(self, host_name: str) -> DisSample:
        return DisSample(available=False)


# ---------------------------------------------------------------------------
# Per-host DIS state (tracks history for STALLED detection)
# ---------------------------------------------------------------------------

@dataclass
class DisHostState:
    """Persisted across polling cycles to detect traffic transitions."""

    last_packets_total: Optional[int] = None
    last_bytes_total: Optional[int] = None
    last_sample_time: Optional[float] = None

    # Epoch when traffic was last seen above threshold (monotonic)
    last_active_time: Optional[float] = None
    # Whether the previous cycle was classified as active
    was_active: bool = False


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def classify_dis_status(
    *,
    sample: DisSample,
    state: DisHostState,
    p3d_running: Optional[bool],
    quiet_window_seconds: float = 30.0,
    stall_window_seconds: float = 120.0,
    active_pps_threshold: float = 0.1,
    active_bps_threshold: float = 1.0,
) -> DisStatus:
    """
    Derive a :class:`DisStatus` from *sample*, *state*, and P3D process status.

    Parameters
    ----------
    sample:
        Raw sample from the collector for this cycle.
    state:
        Persisted per-host state.  **Mutated in place** to reflect current
        cycle — callers must preserve this object across calls.
    p3d_running:
        Whether Prepar3D.exe is currently running, or ``None`` if unknown.
    quiet_window_seconds:
        How many seconds of zero deltas (while P3D is running) before the
        status changes from DIS_ACTIVE/DIS_UNKNOWN to DIS_QUIET.
    stall_window_seconds:
        How many seconds of zero deltas (after traffic was previously seen)
        before the status changes to DIS_STALLED.
    active_pps_threshold:
        Minimum packets-per-second delta to consider traffic "active".
    active_bps_threshold:
        Minimum bytes-per-second delta to consider traffic "active".

    Returns
    -------
    DisStatus
    """
    if sample.error and not sample.available:
        return DisStatus.DIS_ERROR

    if not sample.available:
        return DisStatus.DIS_UNKNOWN

    now = sample.collection_time

    # Compute deltas if we have a previous sample to compare against.
    pps: Optional[float] = None
    bps: Optional[float] = None

    if (
        state.last_packets_total is not None
        and sample.packets_total is not None
        and state.last_sample_time is not None
        and state.last_sample_time < now
    ):
        elapsed = now - state.last_sample_time
        if elapsed > 0:
            pps = (sample.packets_total - state.last_packets_total) / elapsed
            if sample.bytes_total is not None and state.last_bytes_total is not None:
                bps = (sample.bytes_total - state.last_bytes_total) / elapsed

    # Update persisted state for next cycle.
    state.last_packets_total = sample.packets_total
    state.last_bytes_total = sample.bytes_total
    state.last_sample_time = now

    # If we don't have a delta yet (first sample), return UNKNOWN.
    if pps is None:
        return DisStatus.DIS_UNKNOWN

    traffic_active = pps >= active_pps_threshold or (
        bps is not None and bps >= active_bps_threshold
    )

    if traffic_active:
        state.last_active_time = now
        state.was_active = True
        return DisStatus.DIS_ACTIVE

    # Traffic is zero / below threshold.
    if state.was_active and state.last_active_time is not None:
        idle_seconds = now - state.last_active_time
        if idle_seconds >= stall_window_seconds:
            return DisStatus.DIS_STALLED

    # P3D running with no traffic and no prior active period.
    if p3d_running is True:
        if state.last_active_time is None or (now - (state.last_active_time or now)) >= quiet_window_seconds:
            return DisStatus.DIS_QUIET

    return DisStatus.DIS_UNKNOWN


# ---------------------------------------------------------------------------
# High-level check function used by monitor_engine
# ---------------------------------------------------------------------------

@dataclass
class DisCheckResult:
    """Result of one DIS health check cycle."""

    dis_status: DisStatus = DisStatus.DIS_UNKNOWN
    dis_last_checked: Optional[str] = None
    dis_packets_per_sec: Optional[float] = None
    dis_bytes_per_sec: Optional[float] = None
    dis_error: Optional[str] = None
    dis_monitoring_mode: str = "placeholder"


def check_dis_health(
    *,
    host_name: str,
    p3d_running: Optional[bool],
    dis_config: dict,
    host_dis_config: dict,
    collector: DisCollector,
    state: DisHostState,
) -> DisCheckResult:
    """
    Run one DIS health check cycle and return a :class:`DisCheckResult`.

    This function is the only entry point called by the monitor engine.  It
    handles all exceptions internally so the monitor never crashes due to DIS
    monitoring.

    Parameters
    ----------
    host_name:
        Name of the host being checked (for logging).
    p3d_running:
        Whether Prepar3D.exe is running on this host, or ``None`` if unknown.
    dis_config:
        Top-level ``dis_monitoring`` section from central config.
    host_dis_config:
        Per-host override dict from ``dis_monitoring.hosts.<host_name>``.
    collector:
        Passive collector implementation (default: PlaceholderCollector).
    state:
        Per-host state persisted across polling cycles.

    Returns
    -------
    DisCheckResult
        Always returns a result — never raises.
    """
    from datetime import datetime, timezone

    result = DisCheckResult()
    result.dis_last_checked = datetime.now(timezone.utc).isoformat()

    try:
        # ── feature flags ────────────────────────────────────────────────────
        global_enabled = dis_config.get("enabled", False)
        host_enabled = host_dis_config.get("enabled", True)
        safe_mode = dis_config.get("safe_mode", True)
        default_unavailable = dis_config.get(
            "default_status_when_unavailable", "DIS_UNKNOWN"
        )
        mode = host_dis_config.get("mode", "placeholder")
        result.dis_monitoring_mode = mode

        if not global_enabled or not host_enabled:
            result.dis_status = DisStatus.DIS_DISABLED
            return result

        # ── thresholds ───────────────────────────────────────────────────────
        quiet_window = float(dis_config.get("quiet_window_seconds", 30.0))
        stall_window = float(dis_config.get("stall_window_seconds", 120.0))
        active_pps = float(dis_config.get("active_pps_threshold", 0.1))
        active_bps = float(dis_config.get("active_bps_threshold", 1.0))

        # ── collect ──────────────────────────────────────────────────────────
        sample = collector.collect(host_name)

        if sample.error:
            result.dis_error = sample.error
            _logger.debug(
                "dis host=%s collector error: %s", host_name, sample.error
            )

        # ── classify ─────────────────────────────────────────────────────────
        status = classify_dis_status(
            sample=sample,
            state=state,
            p3d_running=p3d_running,
            quiet_window_seconds=quiet_window,
            stall_window_seconds=stall_window,
            active_pps_threshold=active_pps,
            active_bps_threshold=active_bps,
        )

        # Honour default_status_when_unavailable config for UNKNOWN results.
        if status == DisStatus.DIS_UNKNOWN:
            try:
                status = DisStatus(default_unavailable)
            except ValueError:
                pass

        result.dis_status = status

        # Populate rate metrics when we have deltas.
        if (
            state.last_packets_total is not None
            and state.last_sample_time is not None
            and sample.available
        ):
            # Rates were already computed inside classify_dis_status; we
            # re-derive them here for reporting purposes only.
            if sample.packets_total is not None and state.last_sample_time is not None:
                elapsed = sample.collection_time - state.last_sample_time
                if elapsed > 0 and state.last_packets_total is not None:
                    result.dis_packets_per_sec = round(
                        (sample.packets_total - state.last_packets_total) / elapsed, 2
                    )
                if (
                    sample.bytes_total is not None
                    and state.last_bytes_total is not None
                ):
                    result.dis_bytes_per_sec = round(
                        (sample.bytes_total - state.last_bytes_total) / elapsed, 2
                    )

    except Exception as exc:
        _logger.warning(
            "DIS check failed for host=%s (non-fatal): %s", host_name, exc
        )
        result.dis_status = DisStatus.DIS_ERROR
        result.dis_error = str(exc)

    return result
