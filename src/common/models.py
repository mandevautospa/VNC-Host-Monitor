"""
Data models shared between the host watchdog and the central monitor.

HostStatus  — all possible states a host can be in (priority order matches spec §10)
HostConfig  — one entry from hosts.json
PingResult  — output of a single ping check
VncResult   — output of a single VNC port / banner check
HeartbeatResult — result of reading one heartbeat JSON file
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class HostStatus(str, Enum):
    """
    Host state priority (highest → lowest):
      1. HOST_UNREACHABLE
      2. HEARTBEAT_STALE
      3. VNC_DOWN
      4. P3D_CRASH_DETECTED
      5. P3D_NOT_RUNNING
      6. P3D_HANG_SUSPECTED
      7. RESOURCE_CRITICAL
      8. RESOURCE_WARNING
      9. WARNING
     10. HEALTHY
    """

    HOST_UNREACHABLE = "HOST_UNREACHABLE"
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
