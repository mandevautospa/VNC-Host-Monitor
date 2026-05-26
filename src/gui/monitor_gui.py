"""Tkinter GUI entry point for central host monitoring."""

from __future__ import annotations

import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import List

# Allow running the file directly from the repo root.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.central_monitor.monitor_engine import MonitorEngine, _load_hosts, _load_json
from src.common.logging_setup import setup_logger
from src.common.models import HostConfig
from src.gui.host_selector import show_host_selector

_REPO_ROOT = Path(__file__).parent.parent.parent
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "central_config.json"
_DEFAULT_HOSTS = _REPO_ROOT / "config" / "hosts.json"
_DEFAULT_LOG = _REPO_ROOT / "logs" / "central_monitor.log"


class MonitorGuiApp:
    """Thread-safe Tkinter monitor UI backed by MonitorEngine.poll_once()."""

    def __init__(self, root: tk.Tk, engine: MonitorEngine) -> None:
        self.root = root
        self.engine = engine

        self.root.title("P3D Host Monitor")
        self.root.geometry("1160x540")
        self.root.minsize(980, 420)

        self._queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None

        self._build_ui()
        self._seed_rows()
        self.root.after(150, self._process_queue)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="both", expand=True)

        cols = (
            "host",
            "ping",
            "vnc",
            "heartbeat",
            "p3d",
            "cpu",
            "ram",
            "disk",
            "status",
            "failure_count",
        )
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", height=16)

        headings = {
            "host": "Host",
            "ping": "Ping",
            "vnc": "VNC",
            "heartbeat": "Heartbeat",
            "p3d": "P3D",
            "cpu": "CPU",
            "ram": "RAM",
            "disk": "Disk Free",
            "status": "Status",
            "failure_count": "Failure Count",
        }
        widths = {
            "host": 140,
            "ping": 70,
            "vnc": 70,
            "heartbeat": 140,
            "p3d": 80,
            "cpu": 70,
            "ram": 70,
            "disk": 90,
            "status": 180,
            "failure_count": 110,
        }

        for col in cols:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="center")

        self.tree.column("host", anchor="w")
        self.tree.column("status", anchor="w")

        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")

        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        self.start_btn = ttk.Button(btn_frame, text="Start Monitoring", command=self.start_monitoring)
        self.stop_btn = ttk.Button(btn_frame, text="Stop Monitoring", command=self.stop_monitoring)
        self.refresh_btn = ttk.Button(btn_frame, text="Refresh Now", command=self.refresh_now)
        self.open_logs_btn = ttk.Button(btn_frame, text="Open Logs", command=self.open_logs)
        self.exit_btn = ttk.Button(btn_frame, text="Exit", command=self.on_exit)

        self.start_btn.pack(side="left", padx=4)
        self.stop_btn.pack(side="left", padx=4)
        self.refresh_btn.pack(side="left", padx=4)
        self.open_logs_btn.pack(side="left", padx=4)
        self.exit_btn.pack(side="right", padx=4)

        self.stop_btn.configure(state="disabled")

        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

    def _seed_rows(self) -> None:
        for host in self.engine.hosts:
            self.tree.insert(
                "",
                "end",
                iid=host.name,
                values=(host.name, "-", "-", "-", "-", "-", "-", "-", "UNKNOWN", "0"),
            )

    @staticmethod
    def _pct(value) -> str:
        return f"{value:.0f}%" if value is not None else "-"

    def _heartbeat_cell(self, hb: dict) -> str:
        hb_fresh = hb.get("fresh")
        hb_age = hb.get("age_seconds")
        hb_exists = hb.get("exists", False)
        if hb_fresh is True and hb_age is not None:
            return f"FRESH {hb_age:.0f}s"
        if hb_exists and hb_fresh is False:
            return f"STALE {hb_age:.0f}s" if hb_age is not None else "STALE"
        return "N/A"

    def _to_values(self, result: dict) -> tuple:
        net = result.get("network", {})
        hb = result.get("heartbeat", {})
        hr = result.get("host_reported", {})

        return (
            result.get("host", "?"),
            "OK" if net.get("ping_ok") else "FAIL",
            "OK" if net.get("vnc_port_ok") else "FAIL",
            self._heartbeat_cell(hb),
            "RUN" if hr.get("p3d_running") is True else ("DOWN" if hr.get("p3d_running") is False else "-"),
            self._pct(hr.get("cpu_percent")),
            self._pct(hr.get("ram_percent")),
            self._pct(hr.get("disk_free_percent")),
            str(result.get("final_status", "UNKNOWN")),
            str(result.get("failure_count", 0)),
        )

    def _apply_results(self, results: List[dict]) -> None:
        for result in results:
            host = result.get("host", "")
            if not host:
                continue
            if not self.tree.exists(host):
                self.tree.insert("", "end", iid=host, values=self._to_values(result))
                continue
            self.tree.item(host, values=self._to_values(result))

    def _process_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "results":
                    self._apply_results(payload)
                elif kind == "error":
                    messagebox.showerror("Monitoring Error", str(payload))
        except queue.Empty:
            pass

        self.root.after(150, self._process_queue)

    def _poll_once_background(self) -> None:
        try:
            results = self.engine.poll_once()
            self._queue.put(("results", results))
        except Exception as exc:
            self._queue.put(("error", exc))

    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            self._poll_once_background()
            self._stop_event.wait(self.engine.interval)

    def start_monitoring(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._worker_thread.start()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")

    def stop_monitoring(self) -> None:
        self._stop_event.set()
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")

    def refresh_now(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        threading.Thread(target=self._poll_once_background, daemon=True).start()

    def open_logs(self) -> None:
        log_path = Path(self.engine.config.get("log_path", _DEFAULT_LOG))
        if not log_path.exists():
            messagebox.showwarning("Log File", f"Log file not found:\n{log_path}")
            return

        try:
            os.startfile(str(log_path))
        except Exception as exc:
            messagebox.showerror("Open Logs", f"Unable to open log file:\n{exc}")

    def on_exit(self) -> None:
        self.stop_monitoring()
        self.root.destroy()


def _build_engine_from_args(args: list[str]) -> MonitorEngine:
    config_path = args[0] if len(args) > 0 else _DEFAULT_CONFIG
    hosts_path = args[1] if len(args) > 1 else _DEFAULT_HOSTS

    config = _load_json(config_path)
    all_hosts = _load_hosts(hosts_path)
    selected_hosts: List[HostConfig] | None = show_host_selector(all_hosts)

    if selected_hosts is None:
        raise RuntimeError("No hosts selected.")

    log_path = config.get("log_path", _DEFAULT_LOG)
    logger = setup_logger("central_monitor", log_path)

    return MonitorEngine(
        config_path=config_path,
        hosts_path=hosts_path,
        selected_hosts=selected_hosts,
        logger=logger,
    )


def main() -> None:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]

    try:
        engine = _build_engine_from_args(args)
    except RuntimeError:
        print("No hosts selected. Exiting.")
        return

    root = tk.Tk()
    app = MonitorGuiApp(root, engine)
    root.mainloop()


if __name__ == "__main__":
    main()
