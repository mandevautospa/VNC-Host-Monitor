from __future__ import annotations

import warnings
from datetime import timedelta
from pathlib import Path
from tkinter import ttk

import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
from matplotlib.figure import Figure

from src.common.heartbeat_csv import DEFAULT_CSV_PATH, load_heartbeat_history


_MIN_PLOT_ROWS = 2
_COLLECTING_MSG = "Collecting resource history..."
_INITIAL_REFRESH_DELAY_MS = 500


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
        window_minutes: int = 30,
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
        self.ax.set_title(f"{self.host_name} CPU/RAM Usage")
        self.ax.set_xlabel("Time")
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
        timestamps = df["heartbeat_timestamp"].tolist()
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
                f"Last update: {ts_latest.strftime('%H:%M:%S')} | "
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