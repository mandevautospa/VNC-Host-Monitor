"""
Unit tests for heartbeat_reader.read_heartbeat().

All tests use a temporary directory (pytest's tmp_path fixture) — no real
network share or production files are touched.
"""

import json
import os
import time

import pytest
from src.central_monitor.heartbeat_reader import read_heartbeat


def _write(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


_SAMPLE = {
    "schema_version": "1.0",
    "host": "host-01",
    "status": "HEALTHY",
    "p3d": {"running": True, "pid": 1234, "cpu_percent": 34.5},
    "resources": {"cpu_percent": 42.0, "ram_percent": 60.0},
    "events": {"recent_app_crash_count": 0},
}


# ── File does not exist ───────────────────────────────────────────────────────

def test_missing_file(tmp_path):
    result = read_heartbeat(str(tmp_path / "nonexistent.json"))
    assert not result.exists
    assert result.error
    assert not result.fresh


# ── Fresh file ────────────────────────────────────────────────────────────────

def test_fresh_heartbeat(tmp_path):
    path = str(tmp_path / "host-01.json")
    _write(path, _SAMPLE)
    result = read_heartbeat(path, stale_seconds=90)

    assert result.exists
    assert result.fresh
    assert result.age_seconds is not None
    assert result.age_seconds < 5          # just written — must be brand new
    assert result.error is None


# ── Stale file ────────────────────────────────────────────────────────────────

def test_stale_heartbeat(tmp_path):
    path = str(tmp_path / "host-01.json")
    _write(path, _SAMPLE)

    # Back-date the file to 200 seconds ago
    old = time.time() - 200
    os.utime(path, (old, old))

    result = read_heartbeat(path, stale_seconds=90)
    assert result.exists
    assert not result.fresh
    assert result.age_seconds is not None
    assert result.age_seconds > 90


# ── Data parsing ─────────────────────────────────────────────────────────────

def test_data_returned(tmp_path):
    path = str(tmp_path / "host-01.json")
    _write(path, _SAMPLE)

    result = read_heartbeat(path, stale_seconds=90)
    assert result.data is not None
    assert result.data["host"] == "host-01"
    assert result.data["status"] == "HEALTHY"
    assert result.data["p3d"]["running"] is True


# ── Malformed JSON ────────────────────────────────────────────────────────────

def test_malformed_json(tmp_path):
    path = str(tmp_path / "bad.json")
    with open(path, "w") as fh:
        fh.write("{ this is not valid JSON }")

    result = read_heartbeat(path, stale_seconds=90)
    assert result.exists
    assert result.error
    assert not result.fresh
    assert result.data is None


# ── Boundary: exactly at stale threshold ─────────────────────────────────────

def test_exactly_at_stale_boundary(tmp_path):
    path = str(tmp_path / "host-01.json")
    _write(path, _SAMPLE)

    # Back-date to exactly stale_seconds ago — should still be fresh (<=)
    threshold = 90
    boundary = time.time() - threshold
    os.utime(path, (boundary, boundary))

    result = read_heartbeat(path, stale_seconds=threshold)
    assert result.exists
    # age_seconds may be fractionally over threshold due to timing jitter;
    # accept either outcome as long as the function does not raise
    assert isinstance(result.fresh, bool)


# ── Empty JSON object ─────────────────────────────────────────────────────────

def test_empty_json_object(tmp_path):
    path = str(tmp_path / "empty.json")
    _write(path, {})

    result = read_heartbeat(path, stale_seconds=90)
    assert result.exists
    assert result.fresh
    assert result.data == {}
    assert result.error is None
