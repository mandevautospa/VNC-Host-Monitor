"""Tests for config path resolution in monitor engine."""

from pathlib import Path

from src.central_monitor.monitor_engine import _resolve_input_path


def test_resolve_relative_path_to_repo_root():
    resolved = _resolve_input_path(Path("config") / "central_config.example.json")
    assert resolved.exists()
    assert resolved.name == "central_config.example.json"


def test_resolve_absolute_path_passthrough(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{}", encoding="utf-8")
    resolved = _resolve_input_path(f)
    assert resolved == f


def test_fallback_to_example_json_when_missing(tmp_path):
    base = tmp_path / "config"
    base.mkdir(parents=True, exist_ok=True)
    example = base / "central_config.example.json"
    example.write_text("{}", encoding="utf-8")

    requested = base / "central_config.json"
    resolved = _resolve_input_path(requested)
    assert resolved == example
