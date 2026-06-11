"""Unit tests for MonitorEngine with mocked host checks and alert transport."""

import json
from pathlib import Path

from src.common.models import HeartbeatResult, HostStatus, PingResult, VncResult
from src.central_monitor.monitor_engine import MonitorEngine


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_config(tmp_path: Path, *, require_heartbeat: bool = False, alert_after_failures: int = 2) -> Path:
    config_path = tmp_path / "config" / "central_config.json"
    _write_json(
        config_path,
        {
            "check_interval_seconds": 1,
            "heartbeat_stale_seconds": 90,
            "require_heartbeat": require_heartbeat,
            "alert_after_failures": alert_after_failures,
            "critical_alert_after_failures": 1,
            "alert_retry_seconds": 1,
            "alerts": {"email_enabled": True},
            "log_path": str(tmp_path / "logs" / "central_monitor.log"),
        },
    )
    return config_path


def _make_hosts(tmp_path: Path) -> Path:
    hosts_path = tmp_path / "config" / "hosts.json"
    _write_json(
        hosts_path,
        {
            "hosts": [
                {
                    "name": "host-01",
                    "address": "10.1.1.1",
                    "vnc_port": 5900,
                    "heartbeat_path": r"\\share\host-01.json",
                }
            ]
        },
    )
    return hosts_path


def test_poll_once_returns_dashboard_result_shape(tmp_path, monkeypatch):
    config_path = _make_config(tmp_path)
    hosts_path = _make_hosts(tmp_path)

    monkeypatch.setattr(
        "src.central_monitor.monitor_engine.ping_host",
        lambda *_: PingResult(ping_ok=True, ping_latency_ms=11.5),
    )
    monkeypatch.setattr(
        "src.central_monitor.monitor_engine.check_vnc",
        lambda *_: VncResult(vnc_port_ok=True, vnc_banner_ok=True, vnc_banner_text="RFB 003.008"),
    )
    monkeypatch.setattr(
        "src.central_monitor.monitor_engine.read_heartbeat",
        lambda *_: HeartbeatResult(
            exists=True,
            fresh=True,
            age_seconds=20,
            path=r"\\share\host-01.json",
            data={
                "status": "HEALTHY",
                "p3d": {"running": True, "hang_suspected": False},
                "resources": {"cpu_percent": 25, "ram_percent": 45, "disk_free_percent": 40},
                "events": {"recent_app_crash_count": 0, "recent_app_hang_count": 0},
            },
        ),
    )
    monkeypatch.setattr("src.central_monitor.monitor_engine.send_alert", lambda *_: True)
    monkeypatch.setattr("src.central_monitor.monitor_engine.send_recovery", lambda *_: True)

    engine = MonitorEngine(config_path=config_path, hosts_path=hosts_path)
    results = engine.poll_once()

    assert len(results) == 1
    result = results[0]
    assert result["host"] == "host-01"
    assert "network" in result
    assert "heartbeat" in result
    assert "host_reported" in result
    assert "gpu_percent" in result["host_reported"]
    assert "vram_percent" in result["host_reported"]
    assert result["final_status"] == HostStatus.HEALTHY
    assert result["failure_count"] == 0
    assert result["should_alert"] is False


def test_engine_incident_alert_then_recovery(tmp_path, monkeypatch):
    config_path = _make_config(tmp_path, require_heartbeat=True, alert_after_failures=2)
    hosts_path = _make_hosts(tmp_path)

    monkeypatch.setattr(
        "src.central_monitor.monitor_engine.ping_host",
        lambda *_: PingResult(ping_ok=True, ping_latency_ms=9.2),
    )
    monkeypatch.setattr(
        "src.central_monitor.monitor_engine.check_vnc",
        lambda *_: VncResult(vnc_port_ok=True, vnc_banner_ok=True, vnc_banner_text="RFB 003.008"),
    )

    send_alert_calls = []
    send_recovery_calls = []

    monkeypatch.setattr(
        "src.central_monitor.monitor_engine.send_alert",
        lambda host, status, detail, config: send_alert_calls.append((host, status)) or True,
    )
    monkeypatch.setattr(
        "src.central_monitor.monitor_engine.send_recovery",
        lambda host, previous_status, config: send_recovery_calls.append((host, previous_status)) or True,
    )

    hb_state = {"stale": True}

    def fake_read_heartbeat(*_):
        if hb_state["stale"]:
            return HeartbeatResult(
                exists=True,
                fresh=False,
                age_seconds=180,
                path=r"\\share\host-01.json",
                data={
                    "status": "HEALTHY",
                    "p3d": {"running": True, "hang_suspected": False},
                    "resources": {"cpu_percent": 25, "ram_percent": 45, "disk_free_percent": 40},
                    "events": {"recent_app_crash_count": 0, "recent_app_hang_count": 0},
                },
            )
        return HeartbeatResult(
            exists=True,
            fresh=True,
            age_seconds=10,
            path=r"\\share\host-01.json",
            data={
                "status": "HEALTHY",
                "p3d": {"running": True, "hang_suspected": False},
                "resources": {"cpu_percent": 25, "ram_percent": 45, "disk_free_percent": 40},
                "events": {"recent_app_crash_count": 0, "recent_app_hang_count": 0},
            },
        )

    monkeypatch.setattr("src.central_monitor.monitor_engine.read_heartbeat", fake_read_heartbeat)

    engine = MonitorEngine(config_path=config_path, hosts_path=hosts_path)

    first = engine.poll_once()[0]
    second = engine.poll_once()[0]

    assert first["final_status"] == HostStatus.HEARTBEAT_STALE
    assert second["final_status"] == HostStatus.HEARTBEAT_STALE
    assert first["failure_count"] == 1
    assert second["failure_count"] == 2
    assert len(send_alert_calls) == 1

    # Switch to fresh heartbeat — debounce requires recovery_threshold (default 2)
    # consecutive successes before returning to HEALTHY.
    hb_state["stale"] = False
    first_recovery = engine.poll_once()[0]
    assert first_recovery["final_status"] == HostStatus.RECOVERING

    second_recovery = engine.poll_once()[0]
    assert second_recovery["final_status"] == HostStatus.HEALTHY
    assert second_recovery["recovered"] is True
    assert len(send_recovery_calls) == 1
