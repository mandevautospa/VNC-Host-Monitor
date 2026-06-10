from __future__ import annotations

import tkinter as tk
import warnings
from datetime import date, timedelta
from pathlib import Path
from tkinter import ttk

import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
from matplotlib.figure import Figure

from src.common.heartbeat_csv import DEFAULT_CSV_PATH, load_heartbeat_history, load_day_history


# ---------------------------------------------------------------------------
# Configuration constants – change these to tune behaviour without editing
# graph logic.
# ---------------------------------------------------------------------------

#: Width of the rolling live-graph window (minutes).
LIVE_GRAPH_WINDOW_MINUTES: int = 30


_MIN_PLOT_ROWS = 2
_COLLECTING_MSG = "Collecting resource history..."
_INITIAL_REFRESH_DELAY_MS = 500


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _to_local_naive(ts_series: pd.Series) -> pd.Series:
    """Convert a Series of timestamps to local naive datetimes.

    Timezone-aware timestamps (e.g. UTC) are converted to the machine's local
    time and the timezone info is stripped so matplotlib formats them correctly
    using local-time labels.  Naive timestamps are returned unchanged.
    """
    if ts_series.empty or ts_series.dt.tz is None:
        return ts_series
    return ts_series.apply(
        lambda ts: ts.to_pydatetime().astimezone().replace(tzinfo=None)
    )


def _ts_to_local_str(ts: pd.Timestamp, fmt: str = "%H:%M:%S") -> str:
    """Format a single timestamp as a local-time string."""
    if ts.tzinfo is not None:
        ts = ts.to_pydatetime().astimezone().replace(tzinfo=None)
    return ts.strftime(fmt)


# ---------------------------------------------------------------------------
# Live rolling graph
# ---------------------------------------------------------------------------

class LiveTrendsFrame(ttk.Frame):
    """
    Live CPU/RAM trend graph for one host, backed by the shared heartbeat
    metrics CSV (``analysis/heartbeat_metrics.csv``).

    The frame re-reads the CSV every *refresh_ms* milliseconds and
    displays a rolling *window_minutes*-minute window of the latest samples.
    When fewer than two samples are available the graph is hidden and a
    friendly placeholder message is shown instead.
    """

    def __init__(
        self,
        parent,
        host_name: str = "host-01",
        csv_path: str | Path = DEFAULT_CSV_PATH,
        refresh_ms: int = 5_000,
        window_minutes: int = LIVE_GRAPH_WINDOW_MINUTES,
        # Deprecated – accepted so existing call-sites do not raise TypeError.
        heartbeat_path: str | Path | None = None,
        max_points: int = 180,
    ):
        super().__init__(parent)

        if heartbeat_path is not None:
            warnings.warn(
                "heartbeat_path is deprecated and has no effect; "
                "LiveTrendsFrame now reads from the heartbeat metrics CSV.",
                DeprecationWarning,
                stacklevel=2,
            )

        self.host_name = host_name
        self.csv_path = Path(csv_path)
        self.refresh_ms = refresh_ms
        self.window_minutes = window_minutes

        self._build_ui()
        self.after(_INITIAL_REFRESH_DELAY_MS, self.refresh_graph)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        header = ttk.Frame(self)
        header.pack(fill="x", padx=10, pady=8)

        self.title_label = ttk.Label(
            header,
            text=f"Live Resource Trends — {self.host_name}",
            font=("Segoe UI", 13, "bold"),
        )
        self.title_label.pack(side="left")

        self.daily_btn = ttk.Button(
            header,
            text="View Full-Day Graph",
            command=self._open_daily_graph,
        )
        self.daily_btn.pack(side="right", padx=(8, 0))

        self.status_label = ttk.Label(header, text=_COLLECTING_MSG)
        self.status_label.pack(side="right")

        self.figure = Figure(figsize=(9, 4.8), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self._setup_axes()

        # Markers ensure a visible point even when only one sample exists.
        (self.cpu_line,) = self.ax.plot([], [], label="Host CPU %", marker="o", markersize=3)
        (self.ram_line,) = self.ax.plot([], [], label="Host RAM %", marker="o", markersize=3)
        self.ax.legend(loc="upper left")

        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def _setup_axes(self) -> None:
        self.ax.set_title(f"{self.host_name} CPU/RAM Usage (last {self.window_minutes} min)")
        self.ax.set_xlabel("Time (local)")
        self.ax.set_ylabel("Percent")
        self.ax.set_ylim(0, 100)
        self.ax.grid(True)
        self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.ax.xaxis.offsetText.set_visible(False)

    # ------------------------------------------------------------------
    # Data refresh
    # ------------------------------------------------------------------

    def refresh_graph(self) -> None:
        try:
            df = load_heartbeat_history(
                csv_path=self.csv_path,
                host=self.host_name,
                window_minutes=self.window_minutes,
            )

            if df.empty or len(df) < _MIN_PLOT_ROWS:
                self.status_label.config(text=_COLLECTING_MSG)
                self.cpu_line.set_data([], [])
                self.ram_line.set_data([], [])
                self.canvas.draw_idle()
            else:
                self._redraw(df)

        except Exception as error:
            self.status_label.config(text=f"Trend error: {error}")

        self.after(self.refresh_ms, self.refresh_graph)

    def _redraw(self, df: pd.DataFrame) -> None:
        # Convert to local naive so matplotlib x-axis shows local time.
        local_ts = _to_local_naive(df["heartbeat_timestamp"])
        timestamps = local_ts.tolist()
        cpu_values = df["host_cpu_percent"].tolist()
        ram_values = df["host_ram_percent"].tolist()

        self.cpu_line.set_data(timestamps, cpu_values)
        self.ram_line.set_data(timestamps, ram_values)
        self._fit_xlim(timestamps)

        latest = df.iloc[-1]
        cpu_latest = latest["host_cpu_percent"]
        ram_latest = latest["host_ram_percent"]
        ts_latest = latest["heartbeat_timestamp"]

        cpu_text = f"{cpu_latest:.1f}%" if pd.notna(cpu_latest) else "-"
        ram_text = f"{ram_latest:.1f}%" if pd.notna(ram_latest) else "-"
        self.status_label.config(
            text=(
                f"Last update: {_ts_to_local_str(ts_latest)} | "
                f"CPU {cpu_text} | RAM {ram_text}"
            )
        )

        for label in self.ax.get_xticklabels():
            label.set_rotation(30)
            label.set_horizontalalignment("right")

        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _fit_xlim(self, timestamps: list) -> None:
        if len(timestamps) == 1:
            center = timestamps[0]
            self.ax.set_xlim(
                center - timedelta(seconds=30), center + timedelta(seconds=30)
            )
        else:
            start, end = timestamps[0], timestamps[-1]
            if start == end:
                self.ax.set_xlim(
                    start - timedelta(seconds=30), end + timedelta(seconds=30)
                )
            else:
                self.ax.set_xlim(start, end)
        self.ax.set_ylim(0, 100)

    # ------------------------------------------------------------------
    # Full-day graph popup
    # ------------------------------------------------------------------

    def _open_daily_graph(self) -> None:
        DailyGraphWindow(self, host_name=self.host_name, csv_path=self.csv_path)


# ---------------------------------------------------------------------------
# Full-day historical graph popup
# ---------------------------------------------------------------------------

class DailyGraphWindow:
    """Read-only popup showing one host's full-day CPU/RAM history.

    Opens as a ``tk.Toplevel`` with navigation buttons to browse any
    calendar date.  Data for past days is loaded from the per-day archive
    CSVs in ``analysis/archive/`` (written automatically at midnight by
    ``MonitorEngine``); today's data is read directly from the live
    ``analysis/heartbeat_metrics.csv``.

    The plot mirrors the style of ``analysis/plot_heartbeat_trends.py`` so
    every collected sample is visible – no rolling window is applied.
    """

    def __init__(self, parent, host_name: str, csv_path: Path) -> None:
        self.host_name = host_name
        self.csv_path = csv_path
        self.selected_date = date.today()

        self.top = tk.Toplevel(parent)
        self.top.title(f"Full-Day Graph — {host_name}")
        self.top.geometry("1100x580")
        self.top.resizable(True, True)

        self._canvas: FigureCanvasTkAgg | None = None
        self._build_ui()
        self._load_for_date(self.selected_date)

    def _build_ui(self) -> None:
        # ── Header bar ────────────────────────────────────────────────────
        header = ttk.Frame(self.top)
        header.pack(fill="x", padx=10, pady=8)

        ttk.Label(
            header,
            text=f"Full-Day Resource Trends — {self.host_name}",
            font=("Segoe UI", 13, "bold"),
        ).pack(side="left")

        # Navigation: prev / date label / next
        nav_frame = ttk.Frame(header)
        nav_frame.pack(side="left", padx=(16, 0))

        ttk.Button(nav_frame, text="◀ Prev", width=7, command=self._prev_day).pack(
            side="left"
        )
        self.date_label = ttk.Label(
            nav_frame, text="", font=("Segoe UI", 11), width=12, anchor="center"
        )
        self.date_label.pack(side="left", padx=6)
        self.next_btn = ttk.Button(
            nav_frame, text="Next ▶", width=7, command=self._next_day
        )
        self.next_btn.pack(side="left")

        self.sample_label = ttk.Label(header, text="")
        self.sample_label.pack(side="right")

        # ── Graph area ────────────────────────────────────────────────────
        self.graph_frame = ttk.Frame(self.top)
        self.graph_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.no_data_label = ttk.Label(
            self.graph_frame,
            text="",
            font=("Segoe UI", 11),
        )

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _prev_day(self) -> None:
        self.selected_date -= timedelta(days=1)
        self._load_for_date(self.selected_date)

    def _next_day(self) -> None:
        candidate = self.selected_date + timedelta(days=1)
        if candidate <= date.today():
            self.selected_date = candidate
            self._load_for_date(self.selected_date)

    # ------------------------------------------------------------------
    # Data loading / rendering
    # ------------------------------------------------------------------

    def _load_for_date(self, target_date: date) -> None:
        """Replace the graph content with data for *target_date*."""
        date_str = target_date.isoformat()
        self.date_label.config(text=date_str)

        # Disable next button when already on today.
        if target_date >= date.today():
            self.next_btn.configure(state="disabled")
        else:
            self.next_btn.configure(state="normal")

        # Tear down the previous canvas (if any).
        if self._canvas is not None:
            self._canvas.get_tk_widget().destroy()
            self._canvas = None
        self.no_data_label.pack_forget()

        try:
            df = load_day_history(target_date, host=self.host_name, csv_path=self.csv_path)
        except Exception as exc:
            self.no_data_label.config(text=f"Error loading data for {date_str}: {exc}")
            self.no_data_label.pack(expand=True)
            self.sample_label.config(text="error")
            return

        if df.empty or len(df) < _MIN_PLOT_ROWS:
            self.no_data_label.config(
                text=f"No data available for {date_str}."
            )
            self.no_data_label.pack(expand=True)
            self.sample_label.config(text="0 samples")
            return

        self.sample_label.config(text=f"{len(df)} samples")

        local_ts = _to_local_naive(df["heartbeat_timestamp"])

        fig = Figure(figsize=(12, 5.5), dpi=100)
        ax = fig.add_subplot(111)

        ax.plot(local_ts, df["host_cpu_percent"], label="Host CPU %", linewidth=0.9)
        ax.plot(local_ts, df["host_ram_percent"], label="Host RAM %", linewidth=0.9)

        ax.set_title(f"Host CPU and RAM usage — {self.host_name}  ({date_str})")
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

        self._canvas = FigureCanvasTkAgg(fig, master=self.graph_frame)
        self._canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas.draw()
