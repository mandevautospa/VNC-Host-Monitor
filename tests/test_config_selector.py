"""Tests for the startup config selector dialog helpers."""

from pathlib import Path

import pytest

from src.gui.config_selector import validate_config_selection


def _write_json(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_validate_config_selection_accepts_valid_files(tmp_path):
    central = tmp_path / "central_config.json"
    hosts = tmp_path / "hosts.json"
    _write_json(
        central,
        '{"check_interval_seconds": 10, "heartbeat_stale_seconds": 45, "alerts": {}, "active_hours": {"enabled": false}}',
    )
    _write_json(hosts, '{"hosts": [{"name": "host-01", "address": "127.0.0.1", "vnc_port": 5900, "heartbeat_path": "dev_health/host-01.json"}]}')

    central_path, hosts_path = validate_config_selection(str(central), str(hosts))
    assert central_path == central.resolve()
    assert hosts_path == hosts.resolve()


def test_validate_config_selection_rejects_missing_central(tmp_path):
    hosts = tmp_path / "hosts.json"
    _write_json(hosts, '{"hosts": []}')

    with pytest.raises(FileNotFoundError, match="Central config file not found"):
        validate_config_selection(str(tmp_path / "missing.json"), str(hosts))


def test_validate_config_selection_rejects_invalid_hosts_json(tmp_path):
    central = tmp_path / "central_config.json"
    hosts = tmp_path / "hosts.json"
    _write_json(
        central,
        '{"check_interval_seconds": 10, "heartbeat_stale_seconds": 45, "alerts": {}, "active_hours": {"enabled": false}}',
    )
    _write_json(hosts, "not-json")

    with pytest.raises(ValueError, match="hosts file is not valid JSON"):
        validate_config_selection(str(central), str(hosts))


def test_validate_config_selection_rejects_missing_hosts_list(tmp_path):
    central = tmp_path / "central_config.json"
    hosts = tmp_path / "hosts.json"
    _write_json(
        central,
        '{"check_interval_seconds": 10, "heartbeat_stale_seconds": 45, "alerts": {}, "active_hours": {"enabled": false}}',
    )
    _write_json(hosts, '{"not_hosts": []}')

    with pytest.raises(ValueError, match="top-level 'hosts' list"):
        validate_config_selection(str(central), str(hosts))
