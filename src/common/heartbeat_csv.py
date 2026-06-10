"""Shared CSV helpers for heartbeat/resource history.

Both the GUI live-trends graph and the analysis plotting scripts use this
module to load and filter ``analysis/heartbeat_metrics.csv``.

``append_poll_results`` is called by ``MonitorEngine.poll_once()`` after each
polling cycle so that the CSV is populated continuously during live monitoring.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

_logger = logging.getLogger(__name__)


# Absolute path resolved from this file's location so callers don't need
# to worry about the working directory.
DEFAULT_CSV_PATH: Path = (
    Path(__file__).resolve().parents[2] / "analysis" / "heartbeat_metrics.csv"
)

_NUMERIC_COLUMNS = [
    "host_cpu_percent",
    "host_ram_percent",
    "disk_free_percent",
    "disk_free_gb",
    "p3d_cpu_percent",
    "p3d_memory_mb",
    "p3d_memory_percent",
]


def _ts_local_date(ts: pd.Timestamp) -> datetime.date | None:
    """Return the local calendar date for a pandas Timestamp.

    Handles both timezone-aware (converts to local) and naive (treated as
    local) timestamps.
    """
    if pd.isna(ts):
        return None
    if ts.tzinfo is not None:
        return ts.to_pydatetime().astimezone().replace(tzinfo=None).date()
    return ts.date()


def load_heartbeat_history(
    csv_path: str | Path = DEFAULT_CSV_PATH,
    host: str | None = None,
    window_minutes: int | None = None,
    date: str | None = None,
) -> pd.DataFrame:
    """Load heartbeat/resource history from *csv_path*.

    Parameters
    ----------
    csv_path:
        Path to the heartbeat metrics CSV.
        Defaults to ``analysis/heartbeat_metrics.csv`` at the project root.
    host:
        If given, keep only rows where the ``host`` column equals this value.
    window_minutes:
        If given, keep only rows whose ``heartbeat_timestamp`` falls within
        the last *window_minutes* minutes relative to the newest row in the
        (already host-filtered) data.  Mutually exclusive with *date* — if
        both are provided *window_minutes* is applied after *date*.
    date:
        If given, keep only rows whose ``heartbeat_timestamp`` falls on this
        local calendar date.  Pass ``"today"`` to use today's date, or an
        ISO date string (``"YYYY-MM-DD"``).

    Returns
    -------
    pandas.DataFrame
        Sorted by ``heartbeat_timestamp`` ascending, with numeric columns
        coerced to float.  Returns an empty DataFrame when the file is
        missing or contains no usable rows.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(csv_path)
    except (pd.errors.ParserError, pd.errors.EmptyDataError, OSError):
        return pd.DataFrame()

    if df.empty:
        return df

    df["heartbeat_timestamp"] = pd.to_datetime(
        df["heartbeat_timestamp"], errors="coerce"
    )
    for col in _NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["heartbeat_timestamp"])
    df = df.sort_values("heartbeat_timestamp").reset_index(drop=True)

    if host is not None:
        df = df[df["host"] == host].copy().reset_index(drop=True)

    if date is not None:
        if date == "today":
            filter_date = datetime.now().date()
        else:
            filter_date = datetime.fromisoformat(date).date()

        local_dates = df["heartbeat_timestamp"].apply(_ts_local_date)
        df = df[local_dates == filter_date].copy().reset_index(drop=True)

    if window_minutes is not None and not df.empty:
        cutoff = df["heartbeat_timestamp"].max() - timedelta(minutes=window_minutes)
        df = df[df["heartbeat_timestamp"] >= cutoff].copy().reset_index(drop=True)

    return df


# ---------------------------------------------------------------------------
# CSV column order — must match analysis/collect_heartbeat_metrics.py
# ---------------------------------------------------------------------------

_CSV_FIELDNAMES = [
    "collected_at",
    "heartbeat_timestamp",
    "heartbeat_file",
    "schema_version",
    "host",
    "watchdog_version",
    "status",
    "host_cpu_percent",
    "host_ram_percent",
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


def _nested(data: dict, *keys: str, default: str = "") -> object:
    """Safely traverse nested dicts, returning *default* on any missing key."""
    current: object = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return current if current is not None else default


def _row_from_poll_result(result: dict) -> dict | None:
    """Convert one ``MonitorEngine.poll_once()`` result into a CSV row dict.

    Returns ``None`` when the result contains no usable heartbeat data
    (e.g. host unreachable, heartbeat file missing, or no timestamp).
    """
    hb = result.get("heartbeat", {})
    data = hb.get("data")
    if not data or not isinstance(data, dict):
        return None

    heartbeat_timestamp = data.get("timestamp", "")
    if not heartbeat_timestamp:
        return None

    errors = data.get("errors", [])
    error_count = len(errors) if isinstance(errors, list) else ""

    return {
        "collected_at": result.get("timestamp", ""),
        "heartbeat_timestamp": heartbeat_timestamp,
        "heartbeat_file": hb.get("path", ""),
        "schema_version": data.get("schema_version", ""),
        "host": data.get("host", result.get("host", "")),
        "watchdog_version": data.get("watchdog_version", ""),
        "status": data.get("status", ""),
        "host_cpu_percent": _nested(data, "resources", "cpu_percent"),
        "host_ram_percent": _nested(data, "resources", "ram_percent"),
        "disk_free_percent": _nested(data, "resources", "disk_free_percent"),
        "disk_free_gb": _nested(data, "resources", "disk_free_gb"),
        "p3d_running": _nested(data, "p3d", "running"),
        "p3d_pid": _nested(data, "p3d", "pid"),
        "p3d_cpu_percent": _nested(data, "p3d", "cpu_percent"),
        "p3d_memory_mb": _nested(data, "p3d", "memory_mb"),
        "p3d_memory_percent": _nested(data, "p3d", "memory_percent"),
        "p3d_hang_suspected": _nested(data, "p3d", "hang_suspected"),
        "tightvnc_service_running": _nested(data, "tightvnc", "service_running"),
        "recent_app_crash_count": _nested(data, "events", "recent_app_crash_count"),
        "recent_app_hang_count": _nested(data, "events", "recent_app_hang_count"),
        "recent_display_error_count": _nested(data, "events", "recent_display_error_count"),
        "error_count": error_count,
    }


def archive_day(
    target_date: datetime.date,
    csv_path: str | Path = DEFAULT_CSV_PATH,
    archive_dir: str | Path | None = None,
) -> Path | None:
    """Save all rows for *target_date* to a separate per-day archive CSV.

    The archive directory defaults to an ``archive/`` sub-folder next to the
    main CSV (i.e. ``analysis/archive/``).  The file is named
    ``YYYY-MM-DD_heartbeat_metrics.csv``.

    Parameters
    ----------
    target_date:
        The calendar date whose rows should be archived.
    csv_path:
        Source CSV file.  Defaults to ``analysis/heartbeat_metrics.csv``.
    archive_dir:
        Destination directory for archive files.  Created automatically if it
        does not exist.

    Returns
    -------
    pathlib.Path or None
        The path of the written archive file, or ``None`` when no rows
        matched *target_date*.
    """
    csv_path = Path(csv_path)
    if archive_dir is None:
        archive_dir = csv_path.parent / "archive"
    archive_dir = Path(archive_dir)

    df = load_heartbeat_history(csv_path=csv_path, date=target_date.isoformat())
    if df.empty:
        _logger.debug("archive_day: no rows for %s in %s; skipping.", target_date, csv_path)
        return None

    archive_dir.mkdir(parents=True, exist_ok=True)
    out_path = archive_dir / f"{target_date.isoformat()}_heartbeat_metrics.csv"
    df.to_csv(out_path, index=False)
    _logger.info("Archived %d rows for %s → %s", len(df), target_date, out_path)
    return out_path


def load_day_history(
    target_date: datetime.date,
    host: str | None = None,
    csv_path: str | Path = DEFAULT_CSV_PATH,
    archive_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Load heartbeat history for a single calendar date.

    Checks the daily archive file first so that past days remain accessible
    even after the main CSV has been cleared or rotated.  Falls back to
    filtering the main CSV by date when no archive file exists.

    Parameters
    ----------
    target_date:
        The calendar date to load.
    host:
        If given, keep only rows for this host.
    csv_path:
        Main heartbeat metrics CSV.
    archive_dir:
        Directory containing per-day archive CSVs.  Defaults to the
        ``archive/`` sub-folder next to *csv_path*.

    Returns
    -------
    pandas.DataFrame
        Sorted by ``heartbeat_timestamp`` ascending.  Empty when no data
        is found for the requested date.
    """
    csv_path = Path(csv_path)
    if archive_dir is None:
        archive_dir = csv_path.parent / "archive"
    archive_path = Path(archive_dir) / f"{target_date.isoformat()}_heartbeat_metrics.csv"

    if archive_path.exists():
        return load_heartbeat_history(csv_path=archive_path, host=host)

    return load_heartbeat_history(csv_path=csv_path, host=host, date=target_date.isoformat())


def append_poll_results(
    results: list,
    csv_path: str | Path = DEFAULT_CSV_PATH,
) -> int:
    """Append new heartbeat metric rows from ``MonitorEngine.poll_once()`` results.

    Called automatically by ``MonitorEngine.poll_once()`` after each polling
    cycle so that ``analysis/heartbeat_metrics.csv`` is kept up to date during
    live monitoring and the ``LiveTrendsFrame`` graph has data to display.

    Deduplicates by ``(host, heartbeat_timestamp)`` so repeated polls against
    the same heartbeat file never produce duplicate rows.

    Parameters
    ----------
    results:
        The list of result dicts returned by ``MonitorEngine.poll_once()``.
    csv_path:
        Destination CSV file.  Defaults to ``analysis/heartbeat_metrics.csv``
        at the project root.

    Returns
    -------
    int
        Number of new rows written (0 when all rows were already present or
        no heartbeat data was available).
    """
    csv_path = Path(csv_path)

    candidate_rows = [r for result in results if (r := _row_from_poll_result(result)) is not None]
    if not candidate_rows:
        return 0

    csv_path.parent.mkdir(parents=True, exist_ok=True)

    existing_keys: set[tuple[str, str]] = set()
    if csv_path.exists():
        try:
            with csv_path.open("r", newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    existing_keys.add((row.get("host", ""), row.get("heartbeat_timestamp", "")))
        except (OSError, csv.Error) as exc:
            _logger.warning("Could not read existing CSV keys from %s: %s", csv_path, exc)

    new_rows: list[dict] = []
    for row in candidate_rows:
        key = (str(row["host"]), str(row["heartbeat_timestamp"]))
        if key not in existing_keys:
            new_rows.append(row)
            existing_keys.add(key)

    if not new_rows:
        return 0

    file_exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDNAMES)
        if not file_exists:
            writer.writeheader()
        writer.writerows(new_rows)

    return len(new_rows)
