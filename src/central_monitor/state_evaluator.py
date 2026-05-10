"""
Converts the raw per-host check dict into a single HostStatus value.

Priority order (spec §10):
  1. HOST_UNREACHABLE   — ping fails
  2. HEARTBEAT_STALE    — file exists but is too old
  3. VNC_DOWN           — TCP port closed / banner wrong
  4. P3D_CRASH_DETECTED — recent Application Error events
  5. P3D_NOT_RUNNING    — Prepar3D.exe absent
  6. P3D_HANG_SUSPECTED — hang flag or recent hang events
  7. RESOURCE_CRITICAL  — CPU/RAM/disk above critical threshold
  8. RESOURCE_WARNING   — CPU/RAM/disk above warning threshold
  9. WARNING            — other generic warning from host
 10. HEALTHY

evaluate_host_status() is the only public function.
"""

from src.common.models import HostStatus


def evaluate_host_status(result: dict) -> HostStatus:
    """
    Derive the final HostStatus from the aggregated check result dict.

    The dict is expected to have the structure built by central_monitor.check_host():
        result["network"]       — ping_ok, vnc_port_ok
        result["heartbeat"]     — exists, fresh
        result["host_reported"] — status, p3d_running, p3d_hang_suspected,
                                   recent_app_crash_count, recent_app_hang_count
    """
    network = result.get("network", {})
    heartbeat = result.get("heartbeat", {})
    host_reported = result.get("host_reported", {})

    ping_ok = network.get("ping_ok", False)
    vnc_port_ok = network.get("vnc_port_ok", False)
    # Default True for backward compatibility with older payloads that never
    # included this field; when present and False it is treated as unhealthy.
    vnc_banner_ok = network.get("vnc_banner_ok", True)
    hb_exists = heartbeat.get("exists", False)
    hb_fresh = heartbeat.get("fresh", False)

    # ── 1. HOST_UNREACHABLE ──────────────────────────────────────────────────
    if not ping_ok:
        return HostStatus.HOST_UNREACHABLE

    # ── 2. HEARTBEAT_STALE ───────────────────────────────────────────────────
    # Only flag stale if the file is known to exist but is too old.
    # A missing file (e.g. watchdog not yet deployed) is not penalised here.
    if hb_exists and not hb_fresh:
        return HostStatus.HEARTBEAT_STALE

    # ── 3. VNC_DOWN ──────────────────────────────────────────────────────────
    if not vnc_port_ok or not vnc_banner_ok:
        return HostStatus.VNC_DOWN

    # If we have no heartbeat data yet, assess network-only health
    if not host_reported:
        return HostStatus.HEALTHY if ping_ok and vnc_port_ok else HostStatus.UNKNOWN

    crash_count = host_reported.get("recent_app_crash_count") or 0
    hang_count = host_reported.get("recent_app_hang_count") or 0
    p3d_running = host_reported.get("p3d_running")      # may be None
    hang_suspected = host_reported.get("p3d_hang_suspected", False)
    reported_status = host_reported.get("status", "UNKNOWN")

    # ── 4. P3D_CRASH_DETECTED ────────────────────────────────────────────────
    if crash_count > 0:
        return HostStatus.P3D_CRASH_DETECTED

    # ── 5. P3D_NOT_RUNNING ───────────────────────────────────────────────────
    if p3d_running is False:
        return HostStatus.P3D_NOT_RUNNING

    # ── 6. P3D_HANG_SUSPECTED ────────────────────────────────────────────────
    if hang_suspected or hang_count > 0:
        return HostStatus.P3D_HANG_SUSPECTED

    if reported_status == "CRITICAL_CHECK_FAILED":
        return HostStatus.CRITICAL_CHECK_FAILED

    # ── 7 / 8. RESOURCE_CRITICAL / RESOURCE_WARNING ──────────────────────────
    if reported_status == "RESOURCE_CRITICAL":
        return HostStatus.RESOURCE_CRITICAL
    if reported_status == "RESOURCE_WARNING":
        return HostStatus.RESOURCE_WARNING

    # ── 9. WARNING ───────────────────────────────────────────────────────────
    if reported_status == "WARNING":
        return HostStatus.WARNING

    # ── 10. HEALTHY ──────────────────────────────────────────────────────────
    return HostStatus.HEALTHY
