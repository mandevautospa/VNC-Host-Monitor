"""
Timestamp helpers used across the project.
"""

import re
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def parse_iso_timestamp(ts: str) -> datetime:
    """
    Parse an ISO-8601 timestamp string into a timezone-aware datetime.
    Handles both trailing 'Z' and offset formats like '+00:00'.
    """
    # Replace trailing Z with +00:00 so fromisoformat handles it on Python < 3.11
    ts = re.sub(r"Z$", "+00:00", ts)
    return datetime.fromisoformat(ts)


def age_seconds(timestamp_iso: str) -> float:
    """Return how many seconds ago the given ISO timestamp was."""
    dt = parse_iso_timestamp(timestamp_iso)
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds()
