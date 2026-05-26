"""Central monitor CLI entry point backed by MonitorEngine."""

import os
import sys
import time
from pathlib import Path

# Allow running the file directly from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.common.logging_setup import setup_logger
from src.central_monitor import monitor_engine
from src.central_monitor.monitor_engine import MonitorEngine
from src.dashboard.console_dashboard import print_dashboard
from src.gui.host_selector import show_host_selector

_REPO_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "central_config.json"
_DEFAULT_HOSTS  = _REPO_ROOT / "config" / "hosts.json"
_DEFAULT_LOG    = _REPO_ROOT / "logs" / "central_monitor.log"


# Backward-compatible exports for tests importing helper functions from this module.
def _is_within_active_hours(config: dict, now=None) -> bool:
    return monitor_engine._is_within_active_hours(config, now=now)


def _select_alert_threshold(final_status, *, alert_threshold: int, critical_threshold: int, is_active_hours: bool) -> int:
    return monitor_engine._select_alert_threshold(
        final_status,
        alert_threshold=alert_threshold,
        critical_threshold=critical_threshold,
        is_active_hours=is_active_hours,
    )


def _update_incident_state(*, final_status, prev_status, failure_count: int, threshold: int, incident_status, alert_sent_for_incident: bool) -> dict:
    return monitor_engine._update_incident_state(
        final_status=final_status,
        prev_status=prev_status,
        failure_count=failure_count,
        threshold=threshold,
        incident_status=incident_status,
        alert_sent_for_incident=alert_sent_for_incident,
    )


def _build_alert_detail(result: dict) -> str:
    return monitor_engine._build_alert_detail(result)


def _load_json(path):
    return monitor_engine._load_json(path)


def _load_hosts(path):
    return monitor_engine._load_hosts(path)


def main() -> None:
    use_gui = "--gui" in sys.argv

    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    config_path = args[0] if len(args) > 0 else _DEFAULT_CONFIG
    hosts_path  = args[1] if len(args) > 1 else _DEFAULT_HOSTS

    config = _load_json(config_path)
    all_hosts = _load_hosts(hosts_path)

    if use_gui:
        selected_hosts = show_host_selector(all_hosts)
        if selected_hosts is None:
            print("No hosts selected. Exiting.")
            sys.exit(0)
        hosts = selected_hosts
    else:
        hosts = all_hosts

    log_path = config.get("log_path", _DEFAULT_LOG)
    logger = setup_logger("central_monitor", log_path)
    engine = MonitorEngine(config_path=config_path, hosts_path=hosts_path, selected_hosts=hosts, logger=logger)

    logger.info(
        "Central monitor started. Monitoring %d host(s). Interval: %ds.",
        len(engine.hosts),
        engine.interval,
    )

    while True:
        results = engine.poll_once()
        print_dashboard(results)
        time.sleep(engine.interval)


if __name__ == "__main__":
    main()
