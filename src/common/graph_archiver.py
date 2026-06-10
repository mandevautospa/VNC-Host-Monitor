"""Save daily CPU/RAM graph images to disk without requiring a GUI display.

Called automatically by ``MonitorEngine`` on each day rollover so that
one PNG per host is persisted to ``analysis/plots/daily/`` even if the
main heartbeat metrics CSV is later cleared or rotated.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import matplotlib.dates as mdates
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from src.common.heartbeat_csv import DEFAULT_CSV_PATH, load_day_history

_logger = logging.getLogger(__name__)

DEFAULT_DAILY_PLOT_DIR: Path = DEFAULT_CSV_PATH.parent / "plots" / "daily"


def save_daily_graph_images(
    target_date: date,
    csv_path: str | Path = DEFAULT_CSV_PATH,
    output_dir: str | Path = DEFAULT_DAILY_PLOT_DIR,
    archive_dir: str | Path | None = None,
) -> list[Path]:
    """Save one PNG graph per host for *target_date*.

    Uses ``load_day_history`` so it checks per-day archive CSVs before
    falling back to the main CSV.  The output PNGs are written to
    ``output_dir`` and named ``YYYY-MM-DD_<host>_cpu_ram.png``.

    Rendering is entirely non-interactive (``FigureCanvasAgg``) so this
    function is safe to call from background threads and environments
    without a display.

    Parameters
    ----------
    target_date:
        The calendar date whose graph should be saved.
    csv_path:
        Main heartbeat metrics CSV.  Defaults to
        ``analysis/heartbeat_metrics.csv``.
    output_dir:
        Directory for output PNG files.  Created automatically if absent.
        Defaults to ``analysis/plots/daily/``.
    archive_dir:
        Per-day archive directory passed through to ``load_day_history``.
        Defaults to the ``archive/`` sub-folder next to *csv_path*.

    Returns
    -------
    list[pathlib.Path]
        Paths of the PNG files that were saved (one per host with at least
        two data-points for *target_date*).
    """
    csv_path = Path(csv_path)
    output_dir = Path(output_dir)

    # Resolve archive_dir default so load_day_history receives a concrete path.
    if archive_dir is None:
        archive_dir = csv_path.parent / "archive"
    archive_dir = Path(archive_dir)

    # Load data for all hosts on this date.
    from src.common.heartbeat_csv import load_heartbeat_history  # local import avoids circularity

    archive_path = archive_dir / f"{target_date.isoformat()}_heartbeat_metrics.csv"
    if archive_path.exists():
        all_df = load_heartbeat_history(csv_path=archive_path)
    else:
        all_df = load_heartbeat_history(csv_path=csv_path, date=target_date.isoformat())

    if all_df.empty:
        _logger.info("save_daily_graph_images: no data for %s; skipping.", target_date)
        return []

    output_dir.mkdir(parents=True, exist_ok=True)
    date_str = target_date.isoformat()
    hosts = sorted(all_df["host"].dropna().unique())
    saved: list[Path] = []

    for host in hosts:
        host_df = all_df[all_df["host"] == host].copy()
        if len(host_df) < 2:
            _logger.debug(
                "save_daily_graph_images: only %d row(s) for %s on %s; skipping.",
                len(host_df),
                host,
                date_str,
            )
            continue

        ts_series = host_df["heartbeat_timestamp"]
        if ts_series.dt.tz is not None:
            ts_series = ts_series.apply(
                lambda t: t.to_pydatetime().astimezone().replace(tzinfo=None)
            )

        fig = Figure(figsize=(12, 5.5), dpi=100)
        ax = fig.add_subplot(111)

        ax.plot(ts_series, host_df["host_cpu_percent"], label="Host CPU %", linewidth=0.9)
        ax.plot(ts_series, host_df["host_ram_percent"], label="Host RAM %", linewidth=0.9)

        ax.set_title(f"Host CPU and RAM usage — {host}  ({date_str})")
        ax.set_xlabel("Time (local)")
        ax.set_ylabel("Percent")
        ax.set_ylim(0, 100)
        ax.legend(loc="upper left")
        ax.grid(True)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.offsetText.set_visible(False)

        for lbl in ax.get_xticklabels():
            lbl.set_rotation(45)
            lbl.set_horizontalalignment("right")

        fig.tight_layout()

        FigureCanvasAgg(fig).draw()

        out_path = output_dir / f"{date_str}_{host}_cpu_ram.png"
        fig.savefig(out_path)
        _logger.info("Saved daily graph image: %s", out_path)
        saved.append(out_path)

    return saved
