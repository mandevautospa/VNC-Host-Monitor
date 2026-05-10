"""
Console status dashboard — Phase 5.

Clears the terminal and prints a human-readable table of all host results
after each monitoring cycle.  Uses ANSI colour codes (supported on
Windows 10+ and all modern terminals).

print_dashboard() is the only public function.
"""

import os
from datetime import datetime
from typing import List

# ── ANSI colours ──────────────────────────────────────────────────────────────
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_GREEN  = "\033[92m"
_CYAN   = "\033[96m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"

_STATUS_COLOUR = {
    "HEALTHY":            _GREEN,
    "RECOVERED":          _GREEN,
    "WARNING":            _YELLOW,
    "RESOURCE_WARNING":   _YELLOW,
    "HEARTBEAT_STALE":    _YELLOW,
    "P3D_HANG_SUSPECTED": _YELLOW,
    "VNC_DOWN":           _RED,
    "HOST_UNREACHABLE":   _RED,
    "P3D_NOT_RUNNING":    _RED,
    "P3D_CRASH_DETECTED": _RED,
    "RESOURCE_CRITICAL":  _RED,
    "CRITICAL":           _RED,
    "UNKNOWN":            _CYAN,
}


def _c(text: str, colour: str) -> str:
    return f"{colour}{text}{_RESET}"


def _bool_cell(val, ok: str = "OK  ", fail: str = "FAIL") -> str:
    if val is True:
        return _c(ok, _GREEN)
    if val is False:
        return _c(fail, _RED)
    return _c("?   ", _CYAN)


def _pct(val) -> str:
    return f"{val:.0f}%" if val is not None else "-"


def _status_cell(status: str) -> str:
    colour = _STATUS_COLOUR.get(status, _RESET)
    return _c(status, colour)


def print_dashboard(results: List[dict]) -> None:
    """
    Clear the screen and render the host status table.

    Args:
        results: List of host result dicts as built by central_monitor._check_host(),
                 with 'final_status', 'failure_count', and 'should_alert' already set.
    """
    os.system("cls" if os.name == "nt" else "clear")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(_c(f"P3D Host Monitor  —  {now}", _BOLD))
    print("=" * 108)

    # Header
    print(
        _c(
            f"{'HOST':<12}{'PING':<10}{'VNC':<10}{'HEARTBEAT':<18}"
            f"{'P3D':<8}{'CPU':<7}{'RAM':<7}{'DISK FREE':<11}STATUS",
            _BOLD,
        )
    )
    print("-" * 108)

    for r in results:
        host    = r.get("host", "?")
        net     = r.get("network", {})
        hb      = r.get("heartbeat", {})
        hr      = r.get("host_reported", {})
        status  = str(r.get("final_status", "UNKNOWN"))
        fails   = r.get("failure_count", 0)

        ping_cell = _bool_cell(net.get("ping_ok"))
        vnc_cell  = _bool_cell(net.get("vnc_port_ok"))

        # Heartbeat freshness
        hb_fresh = hb.get("fresh")
        hb_age   = hb.get("age_seconds")
        hb_exists = hb.get("exists", False)
        if hb_fresh is True and hb_age is not None:
            hb_cell = _c(f"FRESH {hb_age:.0f}s  ", _GREEN)
        elif hb_exists and hb_fresh is False:
            hb_cell = _c(f"STALE {hb_age:.0f}s  " if hb_age else "STALE      ", _RED)
        else:
            hb_cell = _c("N/A        ", _CYAN)

        p3d_cell  = _bool_cell(hr.get("p3d_running"), ok="RUN ", fail="DOWN")
        cpu_cell  = _pct(hr.get("cpu_percent"))
        ram_cell  = _pct(hr.get("ram_percent"))
        disk_cell = _pct(hr.get("disk_free_percent"))

        fail_tag = f" (×{fails})" if fails > 0 else ""
        status_cell = _status_cell(status) + fail_tag

        # Columns: fixed-width plain text; colour codes add invisible bytes so
        # we pad the plain text part, then append the coloured cell.
        print(
            f"{host:<12}"
            f"{ping_cell:<22}"
            f"{vnc_cell:<22}"
            f"{hb_cell:<30}"
            f"{p3d_cell:<20}"
            f"{cpu_cell:<7}"
            f"{ram_cell:<7}"
            f"{disk_cell:<11}"
            f"{status_cell}"
        )

    print("-" * 108)

    # ── Alert section ────────────────────────────────────────────────────────
    alerts    = [r for r in results if r.get("should_alert")]
    recovered = [r for r in results if r.get("recovered")]

    if recovered:
        print()
        for r in recovered:
            print(_c(f"  RECOVERY: {r['host']} returned to HEALTHY", _GREEN))

    if alerts:
        print()
        print(_c("ACTIVE ALERTS:", _BOLD + _RED))
        for r in alerts:
            host   = r.get("host", "?")
            status = str(r.get("final_status", "?"))
            net    = r.get("network", {})
            hb     = r.get("heartbeat", {})
            hr     = r.get("host_reported", {})

            ping_s  = "OK" if net.get("ping_ok")      else "FAIL"
            vnc_s   = "OK" if net.get("vnc_port_ok")   else "FAIL"
            hb_age  = hb.get("age_seconds")
            hb_s    = f"Fresh ({hb_age:.0f}s)" if hb.get("fresh") else "STALE / MISSING"
            p3d_s   = "Running" if hr.get("p3d_running") else "NOT RUNNING"

            print()
            print(_c(f"  ▶ ALERT: {host}  —  {status}", _RED))
            print(f"    Ping: {ping_s}  |  VNC Port 5900: {vnc_s}  |  Heartbeat: {hb_s}  |  P3D: {p3d_s}")

            if net.get("ping_error"):
                print(f"    Ping error   : {net['ping_error']}")
            if net.get("vnc_port_error"):
                print(f"    VNC error    : {net['vnc_port_error']}")
            if net.get("vnc_banner_error"):
                print(f"    Banner error : {net['vnc_banner_error']}")
    else:
        print(_c("\n  No active alerts.", _GREEN))
