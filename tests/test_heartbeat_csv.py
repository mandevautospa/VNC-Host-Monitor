"""Tests for src.common.heartbeat_csv."""

import csv
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.common.heartbeat_csv import (
    _CSV_FIELDNAMES,
    _csv_needs_migration,
    _migrate_csv,
    append_poll_results,
    archive_day,
    load_day_history,
    load_heartbeat_history,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIELDNAMES = [
    "collected_at",
    "heartbeat_timestamp",
    "host",
    "host_cpu_percent",
    "host_ram_percent",
    "host_gpu_percent",
    "host_vram_percent",
    "host_vram_used_mb",
    "host_vram_total_mb",
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
        "host_gpu_percent": 15.0,
        "host_vram_percent": 25.0,
        "host_vram_used_mb": 1024.0,
        "host_vram_total_mb": 4096.0,
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
                "gpu_percent": 18.0,
                "vram_percent": 30.0,
                "vram_used_mb": 1200.0,
                "vram_total_mb": 4000.0,
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
    assert df.iloc[0]["host_gpu_percent"] == 18.0
    assert df.iloc[0]["host_vram_percent"] == 30.0


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


# ---------------------------------------------------------------------------
# archive_day
# ---------------------------------------------------------------------------

def test_archive_day_creates_file(tmp_path):
    """archive_day writes a CSV containing only the rows for the target date."""
    day_a = datetime(2024, 4, 10, 9, 0, 0)
    day_b = datetime(2024, 4, 11, 9, 0, 0)
    csv_file = _write_csv(tmp_path, [
        _row("host-01", day_a, 20.0, 40.0),
        _row("host-01", day_b, 30.0, 60.0),
    ])
    archive_dir = tmp_path / "archive"

    result = archive_day(day_a.date(), csv_path=csv_file, archive_dir=archive_dir)

    assert result is not None
    assert result.exists()
    assert result.name == "2024-04-10_heartbeat_metrics.csv"

    archived_df = load_heartbeat_history(csv_path=result)
    assert len(archived_df) == 1
    assert archived_df.iloc[0]["host_cpu_percent"] == 20.0


def test_archive_day_returns_none_when_no_rows(tmp_path):
    """archive_day returns None when no rows match the target date."""
    day_a = datetime(2024, 4, 10, 9, 0, 0)
    csv_file = _write_csv(tmp_path, [_row("host-01", day_a, 20.0, 40.0)])
    archive_dir = tmp_path / "archive"

    result = archive_day(datetime(2024, 1, 1).date(), csv_path=csv_file, archive_dir=archive_dir)

    assert result is None
    assert not archive_dir.exists()


def test_archive_day_creates_archive_dir(tmp_path):
    """archive_day creates the archive directory if it does not exist."""
    day = datetime(2024, 5, 1, 8, 0, 0)
    csv_file = _write_csv(tmp_path, [_row("host-01", day, 50.0, 70.0)])
    archive_dir = tmp_path / "nested" / "archive"

    archive_day(day.date(), csv_path=csv_file, archive_dir=archive_dir)

    assert archive_dir.is_dir()


# ---------------------------------------------------------------------------
# load_day_history
# ---------------------------------------------------------------------------

def test_load_day_history_prefers_archive(tmp_path):
    """load_day_history reads from the archive CSV when it exists."""
    target = datetime(2024, 6, 1, 10, 0, 0)
    csv_file = _write_csv(tmp_path, [_row("host-01", target, 99.0, 88.0)])
    archive_dir = tmp_path / "archive"

    # Create the archive with different values to confirm the archive is preferred.
    archive_dir.mkdir()
    archive_file = archive_dir / "2024-06-01_heartbeat_metrics.csv"
    archive_file.write_text(csv_file.read_text())  # same data

    # Modify main CSV to have different CPU value – archive should still win.
    csv_file.write_text(
        csv_file.read_text().replace("99.0", "1.0")
    )

    df = load_day_history(target.date(), host="host-01", csv_path=csv_file, archive_dir=archive_dir)
    assert len(df) == 1
    assert df.iloc[0]["host_cpu_percent"] == 99.0


def test_load_day_history_falls_back_to_main_csv(tmp_path):
    """load_day_history falls back to the main CSV when no archive file exists."""
    target = datetime(2024, 7, 15, 12, 0, 0)
    csv_file = _write_csv(tmp_path, [_row("host-01", target, 42.0, 55.0)])
    archive_dir = tmp_path / "archive"  # does not exist

    df = load_day_history(target.date(), host="host-01", csv_path=csv_file, archive_dir=archive_dir)
    assert len(df) == 1
    assert df.iloc[0]["host_cpu_percent"] == 42.0


def test_load_day_history_returns_empty_when_no_data(tmp_path):
    """load_day_history returns an empty DataFrame when neither source has data."""
    target = datetime(2024, 8, 1, 10, 0, 0)
    csv_file = _write_csv(tmp_path, [_row("host-01", target, 10.0, 20.0)])
    archive_dir = tmp_path / "archive"

    # Request a different date that has no data.
    df = load_day_history(datetime(2024, 1, 1).date(), csv_path=csv_file, archive_dir=archive_dir)
    assert df.empty


# ---------------------------------------------------------------------------
# Legacy CSV migration
# ---------------------------------------------------------------------------

# The legacy fieldnames list mirrors what collect_heartbeat_metrics.py wrote
# before the DIS monitoring columns were added.
_LEGACY_FIELDNAMES = [
    "collected_at",
    "heartbeat_timestamp",
    "heartbeat_file",
    "schema_version",
    "host",
    "watchdog_version",
    "status",
    "host_cpu_percent",
    "host_ram_percent",
    "host_gpu_percent",
    "host_vram_percent",
    "host_vram_used_mb",
    "host_vram_total_mb",
    "disk_free_percent",
    "disk_free_gb",
    "p3d_running",
    "p3d_pid",
    "p3d_cpu_percent",
    "p3d_memory_mb",
    "p3d_memory_percent",
    "p3d_hang_suspected",
    "tightvnc_service_running",
    "recent_app_crash_count",
    "recent_app_hang_count",
    "recent_display_error_count",
    "error_count",
]


def _write_legacy_csv(tmp_path: Path, rows: list[dict]) -> Path:
    """Write a CSV using the old 26-column schema (no DIS columns)."""
    csv_file = tmp_path / "heartbeat_metrics.csv"
    with csv_file.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_LEGACY_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return csv_file


def test_csv_needs_migration_detects_legacy_csv(tmp_path):
    """_csv_needs_migration returns True for a 26-column legacy CSV."""
    now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    csv_file = _write_legacy_csv(tmp_path, [_row("host-01", now, 20.0, 40.0)])
    assert _csv_needs_migration(csv_file) is True


def test_csv_needs_migration_false_for_current_schema(tmp_path):
    """_csv_needs_migration returns False when the header already matches."""
    csv_file = tmp_path / "metrics.csv"
    ts = "2024-01-01T12:00:00+00:00"
    # Use append_poll_results to create a CSV with the full current schema.
    append_poll_results([_make_poll_result("host-01", ts)], csv_path=csv_file)
    assert _csv_needs_migration(csv_file) is False


def test_csv_needs_migration_false_for_missing_file(tmp_path):
    """_csv_needs_migration returns False when the file does not exist."""
    assert _csv_needs_migration(tmp_path / "nonexistent.csv") is False


def test_migrate_csv_rewrites_header(tmp_path):
    """_migrate_csv rewrites the CSV with the full _CSV_FIELDNAMES header."""
    now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    csv_file = _write_legacy_csv(tmp_path, [_row("host-01", now, 33.0, 66.0)])

    _migrate_csv(csv_file)

    with csv_file.open("r", newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == _CSV_FIELDNAMES


def test_migrate_csv_preserves_existing_rows(tmp_path):
    """_migrate_csv keeps all old rows intact after migration."""
    now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = [
        _row("host-01", now, 11.0, 22.0),
        _row("host-02", now + timedelta(minutes=1), 33.0, 44.0),
    ]
    csv_file = _write_legacy_csv(tmp_path, rows)

    _migrate_csv(csv_file)

    df = load_heartbeat_history(csv_path=csv_file)
    assert len(df) == 2
    assert set(df["host"].tolist()) == {"host-01", "host-02"}
    assert df[df["host"] == "host-01"].iloc[0]["host_cpu_percent"] == 11.0


def test_migrate_csv_creates_legacy_backup(tmp_path):
    """_migrate_csv saves the original file as heartbeat_metrics_legacy.csv."""
    now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    csv_file = _write_legacy_csv(tmp_path, [_row("host-01", now, 20.0, 40.0)])

    _migrate_csv(csv_file)

    legacy_file = tmp_path / "heartbeat_metrics_legacy.csv"
    assert legacy_file.exists()
    # Legacy backup has the old 26-column header.
    with legacy_file.open("r", newline="", encoding="utf-8") as fh:
        header = next(csv.reader(fh))
    assert header == _LEGACY_FIELDNAMES


def test_migrate_csv_new_columns_are_empty_for_old_rows(tmp_path):
    """Old rows receive empty strings for DIS columns added after migration."""
    now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    csv_file = _write_legacy_csv(tmp_path, [_row("host-01", now, 10.0, 20.0)])

    _migrate_csv(csv_file)

    with csv_file.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        data_row = next(reader)
    assert data_row["dis_status"] == ""
    assert data_row["dis_packets_per_sec"] == ""
    assert data_row["dis_error"] == ""


def test_append_poll_results_migrates_legacy_csv(tmp_path):
    """append_poll_results migrates a legacy CSV before appending new rows."""
    # Use UTC-aware legacy timestamp to match real heartbeat file format.
    now = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    csv_file = _write_legacy_csv(tmp_path, [_row("host-01", now, 12.0, 24.0)])

    ts_new = "2024-06-01T11:00:00+00:00"
    result = _make_poll_result("host-01", ts_new, cpu=50.0, ram=60.0)

    written = append_poll_results([result], csv_path=csv_file)

    assert written == 1
    df = load_heartbeat_history(csv_path=csv_file)
    # Both the migrated legacy row and the new row must be present.
    assert len(df) == 2
    assert df.iloc[0]["host_cpu_percent"] == 12.0
    assert df.iloc[1]["host_cpu_percent"] == 50.0


def test_append_poll_results_legacy_backup_created_on_migration(tmp_path):
    """append_poll_results leaves a legacy backup when it migrates the CSV."""
    now = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    csv_file = _write_legacy_csv(tmp_path, [_row("host-01", now, 9.0, 18.0)])

    ts_new = "2024-06-01T11:00:00+00:00"
    append_poll_results([_make_poll_result("host-01", ts_new)], csv_path=csv_file)

    legacy_file = tmp_path / "heartbeat_metrics_legacy.csv"
    assert legacy_file.exists()


def test_append_poll_results_no_migration_for_current_schema(tmp_path):
    """append_poll_results does not create a legacy backup for up-to-date CSVs."""
    csv_file = tmp_path / "heartbeat_metrics.csv"
    ts = "2024-06-01T12:00:00+00:00"
    append_poll_results([_make_poll_result("host-01", ts)], csv_path=csv_file)

    legacy_file = tmp_path / "heartbeat_metrics_legacy.csv"
    assert not legacy_file.exists()
