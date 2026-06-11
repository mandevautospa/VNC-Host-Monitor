"""Reusable central monitor engine used by CLI and GUI frontends."""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, time as dt_time, timezone
from pathlib import Path
from typing import Dict, List, Sequence

from src.common.models import HostConfig, HostStatus
from src.common.heartbeat_csv import append_poll_results, archive_day
from src.common.graph_archiver import save_daily_graph_images
from src.common.dis_monitor import (
    DisCheckResult,
    DisHostState,
    DisStatus,
    PlaceholderCollector,
    check_dis_health,
)
from src.central_monitor.alerting import send_alert, send_recovery
from src.central_monitor.debounce import DebounceThresholds, HostDebounceState, update_debounce_state
from src.central_monitor.heartbeat_reader import read_heartbeat
from src.central_monitor.ping_check import ping_host
from src.central_monitor.state_evaluator import evaluate_host_status
from src.central_monitor.vnc_check import check_vnc

_REPO_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "central_config.json"
_DEFAULT_HOSTS = _REPO_ROOT / "config" / "hosts.json"
_DEFAULT_LOG = _REPO_ROOT / "logs" / "central_monitor.log"

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

    if start <= end:
        return start <= current <= end

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

    if is_unhealthy and incident_status != final_status:
        incident_status = final_status
        alert_sent_for_incident = False
        is_new_incident = True

    should_alert = is_unhealthy and failure_count >= threshold and not alert_sent_for_incident

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


def _load_json(path: str | Path) -> dict:
    resolved = _resolve_input_path(path)
    with open(resolved, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_hosts(path: str | Path) -> List[HostConfig]:
    data = _load_json(path)
    return [HostConfig(**h) for h in data["hosts"]]


def _resolve_input_path(path: str | Path) -> Path:
    """Resolve config/hosts path from absolute, CWD-relative, or repo-root-relative input."""
    p = Path(path)
    if p.is_absolute():
        return p

    cwd_candidate = Path.cwd() / p
    if cwd_candidate.exists():
        return cwd_candidate

    repo_candidate = _REPO_ROOT / p
    if repo_candidate.exists():
        return repo_candidate

    return repo_candidate


def _check_host(
    host: HostConfig,
    stale_seconds: int,
    dis_config: dict | None = None,
    dis_state: DisHostState | None = None,
) -> dict:
    """
    Run all central checks for host and return merged result.

    Exceptions per sub-check are captured so one host cannot break polling.
    """
    result: dict = {
        "host": host.name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "network": {},
        "heartbeat": {},
        "host_reported": {},
        "dis": {},
        "final_status": HostStatus.UNKNOWN,
        "failure_count": 0,
        "should_alert": False,
    }

    try:
        ping = ping_host(host.address)
        result["network"].update(
            ping_ok=ping.ping_ok,
            ping_latency_ms=ping.ping_latency_ms,
            ping_error=ping.ping_error,
        )
    except Exception as exc:
        result["network"].update(ping_ok=False, ping_error=str(exc))

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

    if host.heartbeat_path:
        try:
            hb = read_heartbeat(host.heartbeat_path, stale_seconds)
            result["heartbeat"].update(
                exists=hb.exists,
                fresh=hb.fresh,
                age_seconds=hb.age_seconds,
                path=hb.path,
                data=hb.data,
                error=hb.error,
            )
            if hb.data:
                d = hb.data
                p3d_section = d.get("p3d", {}) if isinstance(d.get("p3d"), dict) else {}
                result["host_reported"] = {
                    "status": d.get("status", "UNKNOWN"),
                    "p3d_running": p3d_section.get("running"),
                    "p3d_hang_suspected": p3d_section.get("hang_suspected"),
                    "cpu_percent": d.get("resources", {}).get("cpu_percent"),
                    "ram_percent": d.get("resources", {}).get("ram_percent"),
                    "disk_free_percent": d.get("resources", {}).get("disk_free_percent"),
                    "gpu_percent": d.get("resources", {}).get("gpu_percent"),
                    "vram_percent": d.get("resources", {}).get("vram_percent"),
                    "vram_used_mb": d.get("resources", {}).get("vram_used_mb"),
                    "vram_total_mb": d.get("resources", {}).get("vram_total_mb"),
                    "recent_app_crash_count": d.get("events", {}).get("recent_app_crash_count", 0),
                    "recent_app_hang_count": d.get("events", {}).get("recent_app_hang_count", 0),
                    # New fields (backward-compatible: missing → "unknown")
                    "matched_process_name": p3d_section.get("matched_process_name", "unknown"),
                    "expected_process_names": p3d_section.get("expected_process_names", []),
                    "p3d_detection_method": p3d_section.get("p3d_detection_method", "unknown"),
                    "config_path_used": d.get("config_path_used", "unknown"),
                    "heartbeat_written_to": d.get("heartbeat_written_to", "unknown"),
                    "watchdog_version": d.get("watchdog_version", "unknown"),
                }
        except Exception as exc:
            result["heartbeat"].update(exists=False, fresh=False, error=str(exc))
    else:
        result["heartbeat"].update(exists=False, error="No heartbeat path configured")

    # ── DIS / session-layer health check ─────────────────────────────────────
    # Passive, read-only, safe by default. Never sends packets, never restarts
    # P3D, never joins multicast groups. If data is unavailable → DIS_UNKNOWN.
    if dis_config is not None:
        try:
            host_dis_cfg = dis_config.get("hosts", {}).get(host.name, {})
            p3d_running = result.get("host_reported", {}).get("p3d_running")
            dis_result = check_dis_health(
                host_name=host.name,
                p3d_running=p3d_running,
                dis_config=dis_config,
                host_dis_config=host_dis_cfg,
                collector=PlaceholderCollector(),
                state=dis_state or DisHostState(),
            )
            result["dis"] = {
                "dis_status": str(dis_result.dis_status),
                "dis_last_checked": dis_result.dis_last_checked,
                "dis_packets_per_sec": dis_result.dis_packets_per_sec,
                "dis_bytes_per_sec": dis_result.dis_bytes_per_sec,
                "dis_error": dis_result.dis_error,
                "dis_monitoring_mode": dis_result.dis_monitoring_mode,
            }
        except Exception as exc:
            result["dis"] = {
                "dis_status": str(DisStatus.DIS_ERROR),
                "dis_error": str(exc),
                "dis_monitoring_mode": "error",
            }
    else:
        result["dis"] = {
            "dis_status": str(DisStatus.DIS_DISABLED),
            "dis_monitoring_mode": "disabled",
        }

    return result


class MonitorEngine:
    """Stateful polling engine that returns dashboard-ready host result dictionaries."""

    def __init__(
        self,
        config_path: str | Path = _DEFAULT_CONFIG,
        hosts_path: str | Path = _DEFAULT_HOSTS,
        *,
        selected_hosts: Sequence[HostConfig] | None = None,
        selected_host_names: Sequence[str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config_path = str(config_path)
        self.hosts_path = str(hosts_path)

        self.config = _load_json(self.config_path)
        all_hosts = _load_hosts(self.hosts_path)

        if selected_hosts is not None:
            hosts = list(selected_hosts)
        elif selected_host_names is not None:
            selected = set(selected_host_names)
            hosts = [h for h in all_hosts if h.name in selected]
        else:
            hosts = all_hosts

        self.hosts: List[HostConfig] = hosts

        self.interval = int(self.config.get("check_interval_seconds", 30))
        self.stale_seconds = int(self.config.get("heartbeat_stale_seconds", 90))
        self.require_heartbeat = bool(self.config.get("require_heartbeat", False))
        self.alert_threshold = int(self.config.get("alert_after_failures", 3))
        self.critical_threshold = int(self.config.get("critical_alert_after_failures", 2))
        self.alert_retry_seconds = int(self.config.get("alert_retry_seconds", 60))

        # Debounce / hysteresis thresholds loaded from config
        self.debounce_thresholds = DebounceThresholds.from_config(self.config)

        self.failure_counts: Dict[str, int] = {h.name: 0 for h in self.hosts}
        self.previous_statuses: Dict[str, HostStatus] = {
            h.name: HostStatus.UNKNOWN for h in self.hosts
        }
        self.incident_statuses: Dict[str, HostStatus | None] = {
            h.name: None for h in self.hosts
        }
        self.alert_sent_by_incident: Dict[str, bool] = {h.name: False for h in self.hosts}
        self.next_alert_retry_epoch: Dict[str, float] = {h.name: 0.0 for h in self.hosts}

        # Per-host debounce state (one instance per host, persists across cycles)
        self.debounce_states: Dict[str, HostDebounceState] = {
            h.name: HostDebounceState() for h in self.hosts
        }

        # DIS monitoring config and per-host state.
        # dis_config is None when the section is absent from central_config.json
        # so older deployments continue to work without any config changes.
        self.dis_config: dict | None = self.config.get("dis_monitoring") or None
        self.dis_states: Dict[str, DisHostState] = {
            h.name: DisHostState() for h in self.hosts
        }

        # Tracks the calendar date of the last successful poll cycle so that a
        # day-boundary crossing can be detected and the previous day's data
        # archived automatically.
        self._last_polled_date: datetime.date | None = None

        self.logger = logger or logging.getLogger("central_monitor")
        self.logger.info(
            "Monitor engine initialized. Monitoring %d host(s). Interval: %ds. DIS monitoring: %s.",
            len(self.hosts),
            self.interval,
            "enabled" if (self.dis_config and self.dis_config.get("enabled", True)) else "disabled",
        )

    def poll_once(self) -> List[dict]:
        """Poll all selected hosts exactly once and return dashboard-ready result dictionaries."""
        results: List[dict] = []

        for host in self.hosts:
            try:
                result = _check_host(
                    host,
                    self.stale_seconds,
                    dis_config=self.dis_config,
                    dis_state=self.dis_states[host.name],
                )
                raw_status = evaluate_host_status(result)

                if self.require_heartbeat:
                    hb = result.get("heartbeat", {})
                    if not hb.get("exists") or not hb.get("fresh"):
                        raw_status = HostStatus.HEARTBEAT_STALE
                        self.logger.warning(
                            "host=%s require_heartbeat=True but heartbeat missing/stale; forcing HEARTBEAT_STALE",
                            host.name,
                        )

                # Apply debounce / hysteresis layer.
                # When require_heartbeat forces HEARTBEAT_STALE the raw_status
                # override is already authoritative — pass it through unchanged
                # so that callers that rely on the immediate failure signal are
                # not broken.  Counter updates still run so state stays fresh.
                db_state = self.debounce_states[host.name]
                if self.require_heartbeat and raw_status == HostStatus.HEARTBEAT_STALE:
                    # Still update internal counters; use forced status directly.
                    update_debounce_state(
                        host_name=host.name,
                        check_result=result,
                        state=db_state,
                        thresholds=self.debounce_thresholds,
                        raw_status=raw_status,
                        log=self.logger,
                    )
                    final_status = raw_status
                    db_state.current_debounced_status = final_status
                else:
                    final_status = update_debounce_state(
                        host_name=host.name,
                        check_result=result,
                        state=db_state,
                        thresholds=self.debounce_thresholds,
                        raw_status=raw_status,
                        log=self.logger,
                    )

                result["final_status"] = final_status
                result["raw_status"] = raw_status

                # Enrich result with debounce display metadata
                dt = self.debounce_thresholds
                result["debounce"] = {
                    "consecutive_p3d_failures": db_state.consecutive_p3d_failures,
                    "consecutive_p3d_successes": db_state.consecutive_p3d_successes,
                    "p3d_failure_threshold": dt.p3d_failure_threshold,
                    "p3d_recovery_threshold": dt.p3d_recovery_threshold,
                    "consecutive_heartbeat_failures": db_state.consecutive_heartbeat_failures,
                    "consecutive_heartbeat_successes": db_state.consecutive_heartbeat_successes,
                    "heartbeat_failure_threshold": dt.heartbeat_failure_threshold,
                    "heartbeat_recovery_threshold": dt.heartbeat_recovery_threshold,
                    "consecutive_ping_failures": db_state.consecutive_ping_failures,
                    "ping_failure_threshold": dt.ping_failure_threshold,
                    "consecutive_vnc_failures": db_state.consecutive_vnc_failures,
                    "vnc_failure_threshold": dt.vnc_failure_threshold,
                    "last_matched_process_name": db_state.last_matched_process_name or "unknown",
                    "last_config_path_used": db_state.last_config_path_used or "unknown",
                    "last_successful_heartbeat_time": (
                        db_state.last_successful_heartbeat_time.isoformat()
                        if db_state.last_successful_heartbeat_time else None
                    ),
                    "last_status_change_time": (
                        db_state.last_status_change_time.isoformat()
                        if db_state.last_status_change_time else None
                    ),
                }

                prev = self.previous_statuses[host.name]

                if final_status == HostStatus.HEALTHY:
                    self.failure_counts[host.name] = 0
                else:
                    self.failure_counts[host.name] += 1

                result["failure_count"] = self.failure_counts[host.name]

                threshold = _select_alert_threshold(
                    final_status,
                    alert_threshold=self.alert_threshold,
                    critical_threshold=self.critical_threshold,
                    is_active_hours=_is_within_active_hours(self.config),
                )
                transition = _update_incident_state(
                    final_status=final_status,
                    prev_status=prev,
                    failure_count=self.failure_counts[host.name],
                    threshold=threshold,
                    incident_status=self.incident_statuses[host.name],
                    alert_sent_for_incident=self.alert_sent_by_incident[host.name],
                )
                result["should_alert"] = transition["should_alert"]
                result["recovered"] = transition["recovered"]
                self.incident_statuses[host.name] = transition["incident_status"]
                if transition["is_new_incident"]:
                    self.next_alert_retry_epoch[host.name] = 0.0

                now_epoch = time.time()
                if result["should_alert"] and now_epoch < self.next_alert_retry_epoch[host.name]:
                    result["should_alert"] = False

                self.previous_statuses[host.name] = final_status
                results.append(result)

                hb_age = result["heartbeat"].get("age_seconds")
                self.logger.info(
                    "host=%-10s status=%-20s raw=%-20s failures=%d "
                    "ping=%s vnc=%s hb_fresh=%s hb_age=%s "
                    "p3d_miss=%d/%d hb_miss=%d/%d matched=%s",
                    host.name,
                    final_status,
                    raw_status,
                    self.failure_counts[host.name],
                    result["network"].get("ping_ok"),
                    result["network"].get("vnc_port_ok"),
                    result["heartbeat"].get("fresh"),
                    f"{hb_age:.0f}s" if hb_age is not None else "n/a",
                    db_state.consecutive_p3d_failures,
                    dt.p3d_failure_threshold,
                    db_state.consecutive_heartbeat_failures,
                    dt.heartbeat_failure_threshold,
                    db_state.last_matched_process_name or "unknown",
                )

                if result["should_alert"]:
                    detail = _build_alert_detail(result)
                    dispatched = send_alert(host.name, str(final_status), detail, self.config)
                    result["alert_dispatched"] = dispatched
                    if dispatched:
                        self.alert_sent_by_incident[host.name] = True
                        self.next_alert_retry_epoch[host.name] = 0.0
                    else:
                        self.next_alert_retry_epoch[host.name] = now_epoch + max(
                            5, self.alert_retry_seconds
                        )
                    self.logger.warning(
                        "ALERT: host=%s status=%s failure_count=%d dispatched=%s",
                        host.name,
                        final_status,
                        self.failure_counts[host.name],
                        dispatched,
                    )

                if result.get("recovered"):
                    if self.alert_sent_by_incident[host.name]:
                        send_recovery(host.name, str(prev), self.config)
                    self.alert_sent_by_incident[host.name] = False
                    self.logger.info("RECOVERY: host=%s returned to HEALTHY", host.name)

            except Exception as exc:
                self.logger.error("Unhandled error checking host %s: %s", host.name, exc, exc_info=True)

        try:
            append_poll_results(results)
        except Exception as exc:
            self.logger.warning("Failed to write heartbeat metrics to CSV: %s", exc)

        self._maybe_archive_previous_day()

        return results

    def _maybe_archive_previous_day(self) -> None:
        """Archive the previous day's data when the calendar date has changed.

        On each call the current local date is compared to ``_last_polled_date``.
        When a day boundary has been crossed the completed day's rows are written
        to ``analysis/archive/YYYY-MM-DD_heartbeat_metrics.csv`` and a full-day
        PNG graph image is saved to ``analysis/plots/daily/`` for each host.

        Both operations are wrapped in individual try/except blocks so a failure
        in one does not prevent the other from running.
        """
        today = date.today()
        if self._last_polled_date is not None and self._last_polled_date != today:
            prev = self._last_polled_date
            self.logger.info(
                "Day boundary crossed (%s → %s): archiving previous day's data.", prev, today
            )
            try:
                archived = archive_day(prev)
                if archived:
                    self.logger.info("Day archive written: %s", archived)
            except Exception as exc:
                self.logger.warning("Failed to archive day %s: %s", prev, exc)

            try:
                images = save_daily_graph_images(prev)
                for img in images:
                    self.logger.info("Daily graph image saved: %s", img)
            except Exception as exc:
                self.logger.warning("Failed to save daily graph images for %s: %s", prev, exc)

        self._last_polled_date = today
