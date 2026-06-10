"""
Data models shared between the host watchdog and the central monitor.

HostStatus  — all possible states a host can be in (priority order matches spec §10)
HostConfig  — one entry from hosts.json
PingResult  — output of a single ping check
VncResult   — output of a single VNC port / banner check
HeartbeatResult — result of reading one heartbeat JSON file
DisStatus   — DIS/session-layer health status (re-exported from dis_monitor)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

# Re-export DisStatus so callers can import from models directly.
from src.common.dis_monitor import DisStatus  # noqa: F401


class HostStatus(str, Enum):
    """
    Host state priority (highest → lowest):
      1. HOST_UNREACHABLE   — ping unresponsive for >= ping_failure_threshold checks
      1a. HOST_DOWN         — heartbeat stale for >= heartbeat_failure_threshold checks
      2. HEARTBEAT_STALE    — heartbeat file exists but is too old (single-cycle)
      3. VNC_DOWN           — TCP port closed / banner wrong
      4. P3D_CRASH_DETECTED — recent Application Error events
      5. P3D_NOT_RUNNING    — Prepar3D.exe absent for >= p3d_failure_threshold checks
      6. P3D_HANG_SUSPECTED — hang flag or recent hang events
      7. RESOURCE_CRITICAL  — CPU/RAM/disk above critical threshold
      8. RESOURCE_WARNING   — CPU/RAM/disk above warning threshold
      9. WARNING            — intermediate debounce state (1-2 failed checks)
     10. RECOVERING         — recently returned from failure, awaiting recovery_threshold
     11. HEALTHY
    """

    HOST_UNREACHABLE = "HOST_UNREACHABLE"
    HOST_DOWN = "HOST_DOWN"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    VNC_DOWN = "VNC_DOWN"
    P3D_CRASH_DETECTED = "P3D_CRASH_DETECTED"
    P3D_NOT_RUNNING = "P3D_NOT_RUNNING"
    P3D_HANG_SUSPECTED = "P3D_HANG_SUSPECTED"
    CRITICAL_CHECK_FAILED = "CRITICAL_CHECK_FAILED"
    RESOURCE_CRITICAL = "RESOURCE_CRITICAL"
    RESOURCE_WARNING = "RESOURCE_WARNING"
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    RECOVERING = "RECOVERING"
    RECOVERED = "RECOVERED"
    HEALTHY = "HEALTHY"
    UNKNOWN = "UNKNOWN"


@dataclass
class HostConfig:
    """One monitored host entry loaded from hosts.json."""

    name: str
    address: str
    vnc_port: int = 5900
    heartbeat_path: str = ""


@dataclass
class PingResult:
    """Result of a single ICMP ping check."""

    ping_ok: bool
    ping_latency_ms: Optional[float] = None
    ping_error: Optional[str] = None


@dataclass
class VncResult:
    """Result of a VNC TCP-port and RFB-banner check."""

    vnc_port_ok: bool
    vnc_banner_ok: bool = False
    vnc_banner_text: Optional[str] = None
    vnc_port_error: Optional[str] = None
    vnc_banner_error: Optional[str] = None


@dataclass
class HeartbeatResult:
    """Result of reading one heartbeat JSON file from the shared folder."""

    exists: bool
    fresh: bool = False
    age_seconds: Optional[float] = None
    path: str = ""
    data: Optional[dict] = None
    error: Optional[str] = None
