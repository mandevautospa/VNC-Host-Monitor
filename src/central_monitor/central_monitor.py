"""
Central monitor — main polling loop.

Loads host list and configuration, checks every host every interval,
evaluates state with failure-count suppression, and drives the dashboard.

Run directly:
    python -m src.central_monitor.central_monitor
    python src/central_monitor/central_monitor.py [central_config.json] [hosts.json]
    python src/central_monitor/central_monitor.py --gui [central_config.json] [hosts.json]

The config paths are optional; defaults point to config/ in the repo root.
Use --gui flag to show host selector at startup to choose which hosts to monitor.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, time as dt_time, timezone
from pathlib import Path
from typing import Dict, List

# Allow running the file directly from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.common.logging_setup import setup_logger
from src.common.models import HostConfig, HostStatus
from src.central_monitor.ping_check import ping_host
from src.central_monitor.vnc_check import check_vnc
from src.central_monitor.heartbeat_reader import read_heartbeat
from src.central_monitor.state_evaluator import evaluate_host_status
from src.central_monitor.alerting import send_alert, send_recovery
from src.dashboard.console_dashboard import print_dashboard
from src.gui.host_selector import show_host_selector

_REPO_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "central_config.json"
_DEFAULT_HOSTS  = _REPO_ROOT / "config" / "hosts.json"
_DEFAULT_LOG    = _REPO_ROOT / "logs" / "central_monitor.log"

# ── Statuses that warrant faster alerting ───────────────────────────────────
_CRITICAL_STATUSES = {
    HostStatus.HOST_UNREACHABLE,
    HostStatus.P3D_CRASH_DETECTED,
}


def _parse_hhmm(value: str) -> dt_time:
    return datetime.strptime(value, "%H:%M").time()


def _is_within_active_hours(config: dict, now: datetime | None = None) -> bool:
    """Return True when current local time falls within configured active hours."""
    active_hours = config.get("active_hours", {})
    if not active_hours.get("enabled", False):
        return True

    try:
        start = _parse_hhmm(active_hours.get("start", "07:00"))
        end = _parse_hhmm(active_hours.get("end", "18:00"))
    except ValueError:
        logging.getLogger(__name__).warning(
            "Invalid active_hours start/end format; expected HH:MM. Falling back to always-active."
        )
        return True

    current = (now or datetime.now()).time()

    # Same-day window (e.g. 07:00-18:00)
    if start <= end:
        return start <= current <= end

    # Overnight window (e.g. 22:00-06:00)
    return current >= start or current <= end


def _select_alert_threshold(
    final_status: HostStatus,
    *,
    alert_threshold: int,
    critical_threshold: int,
    is_active_hours: bool,
) -> int:
    """Resolve failure-count threshold used before dispatching an alert."""
    if final_status in _CRITICAL_STATUSES:
        return critical_threshold

    # Per spec: P3D_NOT_RUNNING can be treated as critical during active lab hours.
    if final_status == HostStatus.P3D_NOT_RUNNING and is_active_hours:
        return critical_threshold

    return alert_threshold


def _build_alert_detail(result: dict) -> str:
    """Create concise multi-line context for alert transports."""
    net = result.get("network", {})
    hb = result.get("heartbeat", {})
    hr = result.get("host_reported", {})

    hb_age = hb.get("age_seconds")
    hb_state = (
        f"Fresh ({hb_age:.0f}s)" if hb.get("fresh") and hb_age is not None else "STALE / MISSING"
    )

    lines = [
        f"Host: {result.get('host', '?')}",
        f"Status: {result.get('final_status', 'UNKNOWN')}",
        f"Time: {result.get('timestamp', '')}",
        f"Ping: {'OK' if net.get('ping_ok') else 'FAIL'}",
        f"VNC Port: {'OK' if net.get('vnc_port_ok') else 'FAIL'}",
        f"VNC Banner: {'OK' if net.get('vnc_banner_ok') else 'FAIL'}",
        f"Heartbeat: {hb_state}",
        f"P3D Running: {hr.get('p3d_running')}",
    ]

    if net.get("ping_error"):
        lines.append(f"Ping error: {net['ping_error']}")
    if net.get("vnc_port_error"):
        lines.append(f"VNC error: {net['vnc_port_error']}")
    if hb.get("error"):
        lines.append(f"Heartbeat error: {hb['error']}")

    return "\n".join(lines)


def _update_incident_state(
    *,
    final_status: HostStatus,
    prev_status: HostStatus,
    failure_count: int,
    threshold: int,
    incident_status: HostStatus | None,
    alert_sent_for_incident: bool,
) -> dict:
    """Pure transition helper used to dedupe alerts and handle recovery."""
    is_unhealthy = final_status != HostStatus.HEALTHY
    is_new_incident = False

    # New incident starts when entering unhealthy state or unhealthy status changes.
    if is_unhealthy and incident_status != final_status:
        incident_status = final_status
        alert_sent_for_incident = False
        is_new_incident = True

    should_alert = (
        is_unhealthy
        and failure_count >= threshold
        and not alert_sent_for_incident
    )

    recovered = (
        final_status == HostStatus.HEALTHY
        and prev_status not in (HostStatus.HEALTHY, HostStatus.UNKNOWN)
    )

    if recovered:
        incident_status = None

    return {
        "should_alert": should_alert,
        "recovered": recovered,
        "incident_status": incident_status,
        "alert_sent_for_incident": alert_sent_for_incident,
        "is_new_incident": is_new_incident,
    }


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_hosts(path: str) -> List[HostConfig]:
    data = _load_json(path)
    return [HostConfig(**h) for h in data["hosts"]]


def _check_host(host: HostConfig, stale_seconds: int) -> dict:
    """
    Run all central checks for *host*.  Never raises — exceptions per sub-check
    are caught individually so a broken host doesn't stall other hosts.
    """
    result: dict = {
        "host": host.name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "network": {},
        "heartbeat": {},
        "host_reported": {},
        "final_status": HostStatus.UNKNOWN,
        "failure_count": 0,
        "should_alert": False,
    }

    # ── Ping ────────────────────────────────────────────────────────────────
    try:
        ping = ping_host(host.address)
        result["network"].update(
            ping_ok=ping.ping_ok,
            ping_latency_ms=ping.ping_latency_ms,
            ping_error=ping.ping_error,
        )
    except Exception as exc:
        result["network"].update(ping_ok=False, ping_error=str(exc))

    # ── VNC ─────────────────────────────────────────────────────────────────
    try:
        vnc = check_vnc(host.address, host.vnc_port)
        result["network"].update(
            vnc_port_ok=vnc.vnc_port_ok,
            vnc_banner_ok=vnc.vnc_banner_ok,
            vnc_banner_text=vnc.vnc_banner_text,
            vnc_port_error=vnc.vnc_port_error,
            vnc_banner_error=vnc.vnc_banner_error,
        )
    except Exception as exc:
        result["network"].update(vnc_port_ok=False, vnc_banner_ok=False, vnc_port_error=str(exc))

    # ── Heartbeat ───────────────────────────────────────────────────────────
    if host.heartbeat_path:
        try:
            hb = read_heartbeat(host.heartbeat_path, stale_seconds)
            result["heartbeat"].update(
                exists=hb.exists,
                fresh=hb.fresh,
                age_seconds=hb.age_seconds,
                path=hb.path,
                error=hb.error,
            )
            if hb.data:
                d = hb.data
                result["host_reported"] = {
                    "status": d.get("status", "UNKNOWN"),
                    "p3d_running": d.get("p3d", {}).get("running"),
                    "p3d_hang_suspected": d.get("p3d", {}).get("hang_suspected"),
                    "cpu_percent": d.get("resources", {}).get("cpu_percent"),
                    "ram_percent": d.get("resources", {}).get("ram_percent"),
                    "disk_free_percent": d.get("resources", {}).get("disk_free_percent"),
                    "recent_app_crash_count": d.get("events", {}).get("recent_app_crash_count", 0),
                    "recent_app_hang_count": d.get("events", {}).get("recent_app_hang_count", 0),
                }
        except Exception as exc:
            result["heartbeat"].update(exists=False, fresh=False, error=str(exc))
    else:
        result["heartbeat"].update(exists=False, error="No heartbeat path configured")

    return result


def main() -> None:
    # Check for --gui flag to show host selector
    use_gui = "--gui" in sys.argv
    
    # Filter out flags from positional arguments
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    config_path = args[0] if len(args) > 0 else _DEFAULT_CONFIG
    hosts_path  = args[1] if len(args) > 1 else _DEFAULT_HOSTS

    config = _load_json(config_path)
    all_hosts  = _load_hosts(hosts_path)
    
    # Show GUI host selector if requested
    if use_gui:
        selected_hosts = show_host_selector(all_hosts)
        if selected_hosts is None:
            print("No hosts selected. Exiting.")
            sys.exit(0)
        hosts = selected_hosts
    else:
        hosts = all_hosts

    log_path = config.get("log_path", _DEFAULT_LOG)
    logger   = setup_logger("central_monitor", log_path)

    interval         = config.get("check_interval_seconds", 30)
    stale_seconds    = config.get("heartbeat_stale_seconds", 90)
    require_heartbeat = config.get("require_heartbeat", False)
    alert_threshold  = config.get("alert_after_failures", 3)
    critical_threshold = config.get("critical_alert_after_failures", 2)
    alert_retry_seconds = config.get("alert_retry_seconds", 60)

    failure_counts: Dict[str, int]       = {h.name: 0 for h in hosts}
    previous_statuses: Dict[str, HostStatus] = {h.name: HostStatus.UNKNOWN for h in hosts}
    incident_statuses: Dict[str, HostStatus | None] = {h.name: None for h in hosts}
    alert_sent_by_incident: Dict[str, bool] = {h.name: False for h in hosts}
    next_alert_retry_epoch: Dict[str, float] = {h.name: 0.0 for h in hosts}

    logger.info(
        "Central monitor started. Monitoring %d host(s). Interval: %ds.", len(hosts), interval
    )

    while True:
        results = []

        for host in hosts:
            try:
                result = _check_host(host, stale_seconds)
                final_status = evaluate_host_status(result)
                
                # ── require_heartbeat enforcement ────────────────────────────────────
                # If require_heartbeat is True and heartbeat doesn't exist/fresh, fail the host
                if require_heartbeat:
                    hb = result.get("heartbeat", {})
                    if not hb.get("exists") or not hb.get("fresh"):
                        final_status = HostStatus.HEARTBEAT_STALE
                        logger.warning(
                            "host=%s require_heartbeat=True but heartbeat missing/stale; forcing HEARTBEAT_STALE",
                            host.name,
                        )
                
                result["final_status"] = final_status

                prev = previous_statuses[host.name]

                # Reset counter on healthy; increment on any problem
                if final_status == HostStatus.HEALTHY:
                    failure_counts[host.name] = 0
                else:
                    failure_counts[host.name] += 1

                result["failure_count"] = failure_counts[host.name]

                # Determine alert threshold for this status
                threshold = _select_alert_threshold(
                    final_status,
                    alert_threshold=alert_threshold,
                    critical_threshold=critical_threshold,
                    is_active_hours=_is_within_active_hours(config),
                )
                transition = _update_incident_state(
                    final_status=final_status,
                    prev_status=prev,
                    failure_count=failure_counts[host.name],
                    threshold=threshold,
                    incident_status=incident_statuses[host.name],
                    alert_sent_for_incident=alert_sent_by_incident[host.name],
                )
                result["should_alert"] = transition["should_alert"]
                result["recovered"] = transition["recovered"]
                incident_statuses[host.name] = transition["incident_status"]
                if transition["is_new_incident"]:
                    next_alert_retry_epoch[host.name] = 0.0

                now_epoch = time.time()
                if result["should_alert"] and now_epoch < next_alert_retry_epoch[host.name]:
                    result["should_alert"] = False

                previous_statuses[host.name] = final_status
                results.append(result)

                logger.info(
                    "host=%-10s status=%-20s failures=%d ping=%s vnc=%s hb_fresh=%s",
                    host.name,
                    final_status,
                    failure_counts[host.name],
                    result["network"].get("ping_ok"),
                    result["network"].get("vnc_port_ok"),
                    result["heartbeat"].get("fresh"),
                )

                if result["should_alert"]:
                    detail = _build_alert_detail(result)
                    dispatched = send_alert(
                        host.name,
                        str(final_status),
                        detail,
                        config,
                    )
                    result["alert_dispatched"] = dispatched
                    if dispatched:
                        alert_sent_by_incident[host.name] = True
                        next_alert_retry_epoch[host.name] = 0.0
                    else:
                        next_alert_retry_epoch[host.name] = now_epoch + max(5, int(alert_retry_seconds))
                    logger.warning(
                        "ALERT: host=%s status=%s failure_count=%d dispatched=%s",
                        host.name, final_status, failure_counts[host.name], dispatched,
                    )
                if result.get("recovered"):
                    if alert_sent_by_incident[host.name]:
                        send_recovery(host.name, str(prev), config)
                    alert_sent_by_incident[host.name] = False
                    logger.info("RECOVERY: host=%s returned to HEALTHY", host.name)

            except Exception as exc:
                logger.error(
                    "Unhandled error checking host %s: %s", host.name, exc, exc_info=True
                )

        print_dashboard(results)
        time.sleep(interval)


if __name__ == "__main__":
    main()
