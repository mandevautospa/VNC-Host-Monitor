"""Tests for src.common.heartbeat_csv.load_heartbeat_history."""

import csv
import io
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from src.common.heartbeat_csv import load_heartbeat_history


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIELDNAMES = [
    "collected_at",
    "heartbeat_timestamp",
    "host",
    "host_cpu_percent",
    "host_ram_percent",
    "disk_free_percent",
    "disk_free_gb",
    "p3d_cpu_percent",
    "p3d_memory_mb",
    "p3d_memory_percent",
]


def _write_csv(tmp_path: Path, rows: list[dict]) -> Path:
    csv_file = tmp_path / "heartbeat_metrics.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return csv_file


def _row(host: str, ts: datetime, cpu: float, ram: float) -> dict:
    return {
        "collected_at": ts.isoformat(),
        "heartbeat_timestamp": ts.isoformat(),
        "host": host,
        "host_cpu_percent": cpu,
        "host_ram_percent": ram,
        "disk_free_percent": 50.0,
        "disk_free_gb": 100.0,
        "p3d_cpu_percent": 5.0,
        "p3d_memory_mb": 200.0,
        "p3d_memory_percent": 10.0,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_missing_csv_returns_empty_dataframe(tmp_path):
    result = load_heartbeat_history(csv_path=tmp_path / "nonexistent.csv")
    assert isinstance(result, pd.DataFrame)
    assert result.empty


def test_loads_all_rows_when_no_filters(tmp_path):
    now = datetime(2024, 1, 1, 12, 0, 0)
    rows = [
        _row("host-01", now, 20.0, 40.0),
        _row("host-02", now + timedelta(minutes=1), 30.0, 50.0),
    ]
    csv_file = _write_csv(tmp_path, rows)
    df = load_heartbeat_history(csv_path=csv_file)
    assert len(df) == 2


def test_filters_by_host(tmp_path):
    now = datetime(2024, 1, 1, 12, 0, 0)
    rows = [
        _row("host-01", now, 20.0, 40.0),
        _row("host-02", now + timedelta(minutes=1), 30.0, 50.0),
        _row("host-01", now + timedelta(minutes=2), 25.0, 45.0),
    ]
    csv_file = _write_csv(tmp_path, rows)
    df = load_heartbeat_history(csv_path=csv_file, host="host-01")
    assert len(df) == 2
    assert (df["host"] == "host-01").all()


def test_sorts_by_timestamp_ascending(tmp_path):
    now = datetime(2024, 1, 1, 12, 0, 0)
    rows = [
        _row("host-01", now + timedelta(minutes=2), 30.0, 50.0),
        _row("host-01", now, 20.0, 40.0),
        _row("host-01", now + timedelta(minutes=1), 25.0, 45.0),
    ]
    csv_file = _write_csv(tmp_path, rows)
    df = load_heartbeat_history(csv_path=csv_file, host="host-01")
    timestamps = df["heartbeat_timestamp"].tolist()
    assert timestamps == sorted(timestamps)


def test_window_minutes_filters_old_rows(tmp_path):
    now = datetime(2024, 1, 1, 12, 0, 0)
    rows = [
        _row("host-01", now - timedelta(hours=2), 10.0, 20.0),  # outside window
        _row("host-01", now - timedelta(minutes=20), 15.0, 25.0),  # inside window
        _row("host-01", now, 20.0, 30.0),  # newest (defines window anchor)
    ]
    csv_file = _write_csv(tmp_path, rows)
    df = load_heartbeat_history(csv_path=csv_file, host="host-01", window_minutes=30)
    assert len(df) == 2
    assert all(df["heartbeat_timestamp"] >= now - timedelta(minutes=30))


def test_numeric_columns_coerced(tmp_path):
    now = datetime(2024, 1, 1, 12, 0, 0)
    row = _row("host-01", now, 55.5, 70.2)
    row["host_cpu_percent"] = "55.5"  # stored as string in CSV
    row["host_ram_percent"] = "bad_value"  # coerce to NaN
    csv_file = _write_csv(tmp_path, [row])
    df = load_heartbeat_history(csv_path=csv_file)
    assert df["host_cpu_percent"].dtype == float
    assert pd.notna(df.iloc[0]["host_cpu_percent"])
    assert pd.isna(df.iloc[0]["host_ram_percent"])


def test_invalid_timestamps_dropped(tmp_path):
    now = datetime(2024, 1, 1, 12, 0, 0)
    rows = [
        _row("host-01", now, 20.0, 40.0),
    ]
    # Add a row with an invalid timestamp manually
    csv_file = tmp_path / "heartbeat_metrics.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        fh.write("bad_date,not-a-timestamp,host-01,10.0,20.0,,,,,\n")
    df = load_heartbeat_history(csv_path=csv_file)
    assert len(df) == 1


def test_empty_csv_returns_empty_dataframe(tmp_path):
    csv_file = tmp_path / "heartbeat_metrics.csv"
    csv_file.write_text("")
    df = load_heartbeat_history(csv_path=csv_file)
    assert df.empty


def test_unknown_host_returns_empty_dataframe(tmp_path):
    now = datetime(2024, 1, 1, 12, 0, 0)
    csv_file = _write_csv(tmp_path, [_row("host-01", now, 20.0, 40.0)])
    df = load_heartbeat_history(csv_path=csv_file, host="host-99")
    assert df.empty
