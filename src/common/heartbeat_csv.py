"""Shared CSV loading helpers for heartbeat/resource history.

Both the GUI live-trends graph and the analysis plotting scripts use this
module to load and filter ``analysis/heartbeat_metrics.csv``.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd


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


def load_heartbeat_history(
    csv_path: str | Path = DEFAULT_CSV_PATH,
    host: str | None = None,
    window_minutes: int | None = None,
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
        (already host-filtered) data.

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
    except Exception:
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

    if window_minutes is not None and not df.empty:
        cutoff = df["heartbeat_timestamp"].max() - timedelta(minutes=window_minutes)
        df = df[df["heartbeat_timestamp"] >= cutoff].copy().reset_index(drop=True)

    return df
