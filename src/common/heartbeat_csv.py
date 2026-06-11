"""Shared CSV helpers for heartbeat/resource history.

Both the GUI live-trends graph and the analysis plotting scripts use this
module to load and filter ``analysis/heartbeat_metrics.csv``.

``append_poll_results`` is called by ``MonitorEngine.poll_once()`` after each
polling cycle so that the CSV is populated continuously during live monitoring.
"""

from __future__ import annotations

import csv
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.common.app_paths import get_app_root

_logger = logging.getLogger(__name__)


# Resolved via get_app_root() so the path remains stable whether the application
# is run from source or packaged as a PyInstaller frozen executable.  When frozen,
# Path(__file__) points to a temporary extraction directory that is recreated on
# every launch; get_app_root() returns the directory containing the .exe instead.
DEFAULT_CSV_PATH: Path = get_app_root() / "analysis" / "heartbeat_metrics.csv"

_NUMERIC_COLUMNS = [
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
        else:
            df[col] = pd.NA

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
    # DIS/session-layer monitoring fields (added in DIS monitoring rollout)
    "dis_status",
    "dis_packets_per_sec",
    "dis_bytes_per_sec",
    "dis_monitoring_mode",
    "dis_error",
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
        "host_gpu_percent": _nested(data, "resources", "gpu_percent"),
        "host_vram_percent": _nested(data, "resources", "vram_percent"),
        "host_vram_used_mb": _nested(data, "resources", "vram_used_mb"),
        "host_vram_total_mb": _nested(data, "resources", "vram_total_mb"),
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
        # DIS fields — present only when DIS monitoring is active; empty otherwise.
        "dis_status": result.get("dis", {}).get("dis_status", ""),
        "dis_packets_per_sec": result.get("dis", {}).get("dis_packets_per_sec", ""),
        "dis_bytes_per_sec": result.get("dis", {}).get("dis_bytes_per_sec", ""),
        "dis_monitoring_mode": result.get("dis", {}).get("dis_monitoring_mode", ""),
        "dis_error": result.get("dis", {}).get("dis_error", ""),
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


def _csv_needs_migration(csv_path: Path) -> bool:
    """Return True when *csv_path* exists and its header is missing columns.

    Compares the first row of the CSV against ``_CSV_FIELDNAMES``.  Returns
    ``False`` for missing, empty, or unreadable files.
    """
    if not csv_path.exists():
        return False
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            header = next(csv.reader(fh), None)
            if not header:
                return False
            return bool(set(_CSV_FIELDNAMES) - set(header))
    except (OSError, csv.Error):
        return False


def _migrate_csv(csv_path: Path) -> None:
    """Rewrite *csv_path* to the current ``_CSV_FIELDNAMES`` schema.

    1. Saves the original file as ``<stem>_legacy<suffix>`` so that the
       raw pre-migration data is never lost.  Existing per-day archive files
       (``analysis/archive/YYYY-MM-DD_heartbeat_metrics.csv``) continue to
       serve the "View Full Day" and "History" views untouched.
    2. Rewrites the main CSV with the full ``_CSV_FIELDNAMES`` header; rows
       that predate the schema addition receive empty strings for the new
       columns so ``load_heartbeat_history`` (which uses ``pd.read_csv``)
       can parse the file without column-count mismatches.

    All operations are wrapped in error handling so a failure here never
    prevents new data from being appended.
    """
    # Read existing rows before touching the file.
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as fh:
            existing_rows: list[dict] = list(csv.DictReader(fh))
    except (OSError, csv.Error) as exc:
        _logger.warning(
            "Could not read %s for schema migration: %s; skipping.", csv_path, exc
        )
        return

    # Persist the original file as a legacy backup.
    legacy_path = csv_path.with_name(csv_path.stem + "_legacy" + csv_path.suffix)
    try:
        shutil.copy2(csv_path, legacy_path)
        _logger.info("Legacy CSV backup preserved: %s", legacy_path)
    except OSError as exc:
        _logger.warning("Could not write legacy backup to %s: %s", legacy_path, exc)

    # Rewrite main CSV with the full schema; pad missing fields with "".
    try:
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=_CSV_FIELDNAMES, extrasaction="ignore"
            )
            writer.writeheader()
            for row in existing_rows:
                for col in _CSV_FIELDNAMES:
                    row.setdefault(col, "")
                writer.writerow(row)
        _logger.info(
            "Migrated %s to current schema (%d existing row(s) preserved).",
            csv_path,
            len(existing_rows),
        )
    except (OSError, csv.Error) as exc:
        _logger.error(
            "Failed to rewrite %s during migration: %s. Attempting restore from backup.",
            csv_path,
            exc,
        )
        try:
            shutil.copy2(legacy_path, csv_path)
        except OSError as restore_exc:
            _logger.error("Restore also failed: %s", restore_exc)


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

    # Migrate the file when its header predates the current schema (e.g. a CSV
    # created by the legacy collect_heartbeat_metrics.py script that did not
    # include the DIS monitoring columns).  This ensures pd.read_csv never
    # encounters a column-count mismatch that would make the entire file
    # unreadable.  A backup copy is preserved as heartbeat_metrics_legacy.csv.
    if _csv_needs_migration(csv_path):
        _logger.warning(
            "CSV at %s has an outdated schema; migrating to current format.", csv_path
        )
        _migrate_csv(csv_path)

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
