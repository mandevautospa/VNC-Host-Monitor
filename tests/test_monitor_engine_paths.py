"""Tests for config path resolution in monitor engine."""

import pytest
from pathlib import Path

from src.central_monitor.monitor_engine import _resolve_input_path


def test_resolve_relative_path_to_repo_root():
    resolved = _resolve_input_path(Path("config") / "central_config.dev.json")
    assert resolved.exists()
    assert resolved.name == "central_config.dev.json"


def test_resolve_absolute_path_passthrough(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{}", encoding="utf-8")
    resolved = _resolve_input_path(f)
    assert resolved == f


def test_fallback_to_example_json_when_missing(tmp_path):
    requested = tmp_path / "config" / "central_config.json"
    resolved = _resolve_input_path(requested)
    assert resolved == requested
    with pytest.raises(FileNotFoundError):
        requested.open("r", encoding="utf-8")
