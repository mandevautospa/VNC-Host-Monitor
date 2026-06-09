"""Tests for src.common.heartbeat_csv."""

import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.common.heartbeat_csv import append_poll_results, load_heartbeat_history


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


# ---------------------------------------------------------------------------
# append_poll_results
# ---------------------------------------------------------------------------

def _make_poll_result(
    host: str,
    ts: str,
    cpu: float = 25.0,
    ram: float = 50.0,
    *,
    include_data: bool = True,
) -> dict:
    """Build a minimal MonitorEngine.poll_once() result dict for testing."""
    data = (
        {
            "timestamp": ts,
            "host": host,
            "schema_version": "1.0",
            "watchdog_version": "0.1.0",
            "status": "HEALTHY",
            "resources": {
                "cpu_percent": cpu,
                "ram_percent": ram,
                "disk_free_percent": 60.0,
                "disk_free_gb": 120.0,
            },
            "p3d": {
                "running": True,
                "pid": 1234,
                "cpu_percent": 5.0,
                "memory_mb": 300.0,
                "memory_percent": 8.0,
                "hang_suspected": False,
            },
            "tightvnc": {"service_running": True},
            "events": {
                "recent_app_crash_count": 0,
                "recent_app_hang_count": 0,
                "recent_display_error_count": 0,
            },
            "errors": [],
        }
        if include_data
        else None
    )
    return {
        "host": host,
        "timestamp": ts,
        "heartbeat": {
            "exists": include_data,
            "fresh": include_data,
            "path": rf"\\share\{host}.json",
            "data": data,
        },
        "host_reported": {},
        "network": {},
        "final_status": "HEALTHY",
        "failure_count": 0,
        "should_alert": False,
    }


def test_append_poll_results_creates_csv(tmp_path):
    csv_file = tmp_path / "metrics.csv"
    ts = "2024-06-01T12:00:00+00:00"
    result = _make_poll_result("host-01", ts, cpu=30.0, ram=55.0)

    written = append_poll_results([result], csv_path=csv_file)

    assert written == 1
    assert csv_file.exists()
    df = load_heartbeat_history(csv_path=csv_file)
    assert len(df) == 1
    assert df.iloc[0]["host_cpu_percent"] == 30.0
    assert df.iloc[0]["host_ram_percent"] == 55.0


def test_append_poll_results_deduplicates(tmp_path):
    csv_file = tmp_path / "metrics.csv"
    ts = "2024-06-01T12:00:00+00:00"
    result = _make_poll_result("host-01", ts)

    first = append_poll_results([result], csv_path=csv_file)
    second = append_poll_results([result], csv_path=csv_file)

    assert first == 1
    assert second == 0
    df = load_heartbeat_history(csv_path=csv_file)
    assert len(df) == 1


def test_append_poll_results_multiple_hosts(tmp_path):
    csv_file = tmp_path / "metrics.csv"
    ts = "2024-06-01T12:00:00+00:00"
    results = [
        _make_poll_result("host-01", ts, cpu=20.0, ram=40.0),
        _make_poll_result("host-02", ts, cpu=35.0, ram=60.0),
    ]

    written = append_poll_results(results, csv_path=csv_file)

    assert written == 2
    df = load_heartbeat_history(csv_path=csv_file)
    assert len(df) == 2
    assert set(df["host"].tolist()) == {"host-01", "host-02"}


def test_append_poll_results_skips_missing_data(tmp_path):
    csv_file = tmp_path / "metrics.csv"
    ts = "2024-06-01T12:00:00+00:00"
    result_no_data = _make_poll_result("host-01", ts, include_data=False)

    written = append_poll_results([result_no_data], csv_path=csv_file)

    assert written == 0
    assert not csv_file.exists()


def test_append_poll_results_appends_new_timestamps(tmp_path):
    csv_file = tmp_path / "metrics.csv"
    ts1 = "2024-06-01T12:00:00+00:00"
    ts2 = "2024-06-01T12:05:00+00:00"

    append_poll_results([_make_poll_result("host-01", ts1, cpu=10.0, ram=20.0)], csv_path=csv_file)
    written = append_poll_results([_make_poll_result("host-01", ts2, cpu=15.0, ram=25.0)], csv_path=csv_file)

    assert written == 1
    df = load_heartbeat_history(csv_path=csv_file, host="host-01")
    assert len(df) == 2
    assert df.iloc[0]["host_cpu_percent"] == 10.0
    assert df.iloc[1]["host_cpu_percent"] == 15.0


# ---------------------------------------------------------------------------
# date filter
# ---------------------------------------------------------------------------

def test_date_filter_iso_string(tmp_path):
    """Rows from a different calendar day (naive timestamps) are excluded."""
    day_a = datetime(2024, 3, 15, 10, 0, 0)
    day_b = datetime(2024, 3, 16, 10, 0, 0)
    rows = [
        _row("host-01", day_a, 10.0, 20.0),
        _row("host-01", day_b, 30.0, 40.0),
    ]
    csv_file = _write_csv(tmp_path, rows)

    df = load_heartbeat_history(csv_path=csv_file, host="host-01", date="2024-03-15")

    assert len(df) == 1
    assert df.iloc[0]["host_cpu_percent"] == 10.0


def test_date_filter_today(tmp_path):
    """``date='today'`` keeps rows with today's local date."""
    today = datetime.now()
    yesterday = today - timedelta(days=1)
    rows = [
        _row("host-01", yesterday, 5.0, 10.0),
        _row("host-01", today, 55.0, 60.0),
    ]
    csv_file = _write_csv(tmp_path, rows)

    df = load_heartbeat_history(csv_path=csv_file, host="host-01", date="today")

    assert len(df) == 1
    assert df.iloc[0]["host_cpu_percent"] == 55.0


def test_date_filter_no_match_returns_empty(tmp_path):
    """date filter returns empty DataFrame when no rows match."""
    now = datetime(2024, 5, 1, 12, 0, 0)
    csv_file = _write_csv(tmp_path, [_row("host-01", now, 10.0, 20.0)])

    df = load_heartbeat_history(csv_path=csv_file, host="host-01", date="2024-01-01")

    assert df.empty


def test_date_filter_utc_aware_timestamps(tmp_path):
    """UTC-aware timestamps are converted to local time before date comparison."""
    # Use a UTC timestamp; local date might differ depending on timezone offset.
    utc_ts = "2024-06-10T23:30:00+00:00"
    local_dt = datetime.fromisoformat(utc_ts).astimezone().replace(tzinfo=None)
    local_date_str = local_dt.date().isoformat()

    csv_file = tmp_path / "heartbeat_metrics.csv"
    # Write one UTC-aware row
    with csv_file.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerow({
            "collected_at": utc_ts,
            "heartbeat_timestamp": utc_ts,
            "host": "host-01",
            "host_cpu_percent": 42.0,
            "host_ram_percent": 55.0,
            "disk_free_percent": 50.0,
            "disk_free_gb": 100.0,
            "p3d_cpu_percent": 5.0,
            "p3d_memory_mb": 200.0,
            "p3d_memory_percent": 10.0,
        })

    # Filtering by the local-time date should find the row.
    df = load_heartbeat_history(csv_path=csv_file, host="host-01", date=local_date_str)
    assert len(df) == 1
    assert df.iloc[0]["host_cpu_percent"] == 42.0

