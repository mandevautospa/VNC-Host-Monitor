from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.dates as mdates
from matplotlib.figure import Figure


class LiveTrendsFrame(ttk.Frame):
    """
    Live CPU/RAM trend graph for one host heartbeat JSON file.

    This frame reads the latest heartbeat JSON every refresh interval,
    stores recent points in memory, and redraws a matplotlib line graph.
    """

    def __init__(
        self,
        parent,
        heartbeat_path: str | Path,
        host_name: str = "host-01",
        refresh_ms: int = 10_000,
        max_points: int = 180,
    ):
        super().__init__(parent)

        self.heartbeat_path = Path(heartbeat_path)
        self.host_name = host_name
        self.refresh_ms = refresh_ms

        # 180 points at 10 seconds = 30 minutes of visible data
        self.timestamps = deque(maxlen=max_points)
        self.cpu_values = deque(maxlen=max_points)
        self.ram_values = deque(maxlen=max_points)

        self._build_ui()
        self.after(1000, self.refresh_graph)

    def _build_ui(self):
        header = ttk.Frame(self)
        header.pack(fill="x", padx=10, pady=8)

        self.title_label = ttk.Label(
            header,
            text=f"Live Resource Trends — {self.host_name}",
            font=("Segoe UI", 13, "bold"),
        )
        self.title_label.pack(side="left")

        self.status_label = ttk.Label(header, text="Waiting for heartbeat...")
        self.status_label.pack(side="right")

        self.figure = Figure(figsize=(9, 4.8), dpi=100)
        self.ax = self.figure.add_subplot(111)

        self.ax.set_title(f"{self.host_name} CPU/RAM Usage")
        self.ax.set_xlabel("Time")
        self.ax.set_ylabel("Percent")
        self.ax.set_ylim(0, 100)
        self.ax.grid(True)

        self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.ax.xaxis.offsetText.set_visible(False)

        self.cpu_line, = self.ax.plot([], [], label="Host CPU %")
        self.ram_line, = self.ax.plot([], [], label="Host RAM %")

        self.ax.legend(loc="upper left")

        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def _read_heartbeat(self):
        if not self.heartbeat_path.exists():
            raise FileNotFoundError(f"Heartbeat not found: {self.heartbeat_path}")

        with self.heartbeat_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def _extract_metrics(self, heartbeat: dict):
        timestamp_text = heartbeat.get("timestamp")
        resources = heartbeat.get("resources", {})

        cpu = resources.get("cpu_percent")
        ram = resources.get("ram_percent")

        if timestamp_text:
            timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
            if timestamp.tzinfo is not None:
                timestamp = timestamp.astimezone().replace(tzinfo=None)
        else:
            timestamp = datetime.now()

        return timestamp, float(cpu), float(ram)

    def refresh_graph(self):
        try:
            heartbeat = self._read_heartbeat()
            timestamp, cpu, ram = self._extract_metrics(heartbeat)

            self.timestamps.append(timestamp)
            self.cpu_values.append(cpu)
            self.ram_values.append(ram)

            self._redraw()

            self.status_label.config(
                text=f"Last update: {timestamp.strftime('%H:%M:%S')} | CPU {cpu:.1f}% | RAM {ram:.1f}%"
            )

        except Exception as error:
            self.status_label.config(text=f"Trend error: {error}")

        self.after(self.refresh_ms, self.refresh_graph)

    def _redraw(self):
        if not self.timestamps:
            return

        self.cpu_line.set_data(self.timestamps, self.cpu_values)
        self.ram_line.set_data(self.timestamps, self.ram_values)

        if len(self.timestamps) == 1:
            center = self.timestamps[0]
            self.ax.set_xlim(center - timedelta(seconds=30), center + timedelta(seconds=30))
        else:
            self.ax.set_xlim(self.timestamps[0], self.timestamps[-1])

        self.ax.set_ylim(0, 100)

        for label in self.ax.get_xticklabels():
            label.set_rotation(30)
            label.set_horizontalalignment("right")

        self.figure.tight_layout()
        self.canvas.draw_idle()