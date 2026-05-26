"""Tkinter startup dialog for selecting central and hosts config files."""

from __future__ import annotations

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional, Tuple


def get_app_root() -> Path:
    """Return the application root for source runs or the executable folder when packaged."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resolve_config_path(path_text: str) -> Path:
    """Resolve a config path relative to the app root unless it is already absolute."""
    path = Path(path_text.strip())
    if path.is_absolute():
        return path
    return get_app_root() / path


def default_config_paths() -> Tuple[str, str]:
    """Return the preferred startup config paths, falling back to dev files if needed."""
    app_root = get_app_root()
    prod_central = app_root / "config" / "central_config.json"
    prod_hosts = app_root / "config" / "hosts.json"
    dev_central = app_root / "config" / "central_config.dev.json"
    dev_hosts = app_root / "config" / "hosts.dev.json"

    central = prod_central if _is_usable_central_config(prod_central) else (
        dev_central if _is_usable_central_config(dev_central) else prod_central
    )
    hosts = prod_hosts if _is_usable_hosts_config(prod_hosts) else (
        dev_hosts if _is_usable_hosts_config(dev_hosts) else prod_hosts
    )

    return (str(_to_display_path(central, app_root)), str(_to_display_path(hosts, app_root)))


def _is_usable_central_config(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return isinstance(data, dict) and "check_interval_seconds" in data and "heartbeat_stale_seconds" in data
    except Exception:
        return False


def _is_usable_hosts_config(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return isinstance(data, dict) and isinstance(data.get("hosts"), list)
    except Exception:
        return False


def _to_display_path(path: Path, app_root: Path) -> Path:
    try:
        return path.relative_to(app_root)
    except ValueError:
        return path


def validate_config_selection(central_text: str, hosts_text: str) -> Tuple[Path, Path]:
    """Validate and resolve config file paths for the startup dialog."""
    central_raw = central_text.strip()
    hosts_raw = hosts_text.strip()

    if not central_raw:
        raise ValueError("Central config file path is required.")
    if not hosts_raw:
        raise ValueError("Hosts config file path is required.")

    central_path = resolve_config_path(central_raw)
    hosts_path = resolve_config_path(hosts_raw)

    if not central_path.exists():
        raise FileNotFoundError("Central config file not found.")
    if not hosts_path.exists():
        raise FileNotFoundError("Hosts config file not found.")

    try:
        with open(central_path, "r", encoding="utf-8") as fh:
            central_data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError("The selected central config is not valid JSON.") from exc

    try:
        with open(hosts_path, "r", encoding="utf-8") as fh:
            hosts_data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError("The selected hosts file is not valid JSON.") from exc

    if not isinstance(central_data, dict):
        raise ValueError("The central config must be a JSON object.")
    if "check_interval_seconds" not in central_data:
        raise ValueError("The central config must contain 'check_interval_seconds'.")
    if "heartbeat_stale_seconds" not in central_data:
        raise ValueError("The central config must contain 'heartbeat_stale_seconds'.")

    if not isinstance(hosts_data, dict):
        raise ValueError("The hosts config must be a JSON object.")
    if not isinstance(hosts_data.get("hosts"), list):
        raise ValueError("The hosts config must contain a top-level 'hosts' list.")

    return central_path.resolve(), hosts_path.resolve()


class ConfigSelectorDialog:
    """Modal dialog for choosing the config files used by the GUI."""

    def __init__(self, initial_central: str, initial_hosts: str) -> None:
        self.root = tk.Tk()
        self.root.title("P3D Host Monitor — Select Config Files")
        self.root.geometry("700x220")
        self.root.resizable(False, False)

        self.result: Optional[Tuple[str, str]] = None
        self.central_var = tk.StringVar(value=initial_central)
        self.hosts_var = tk.StringVar(value=initial_hosts)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)
        self._center_window()

    def _center_window(self) -> None:
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"+{x}+{y}")

    def _build_row(self, parent, label_text: str, variable: tk.StringVar, browse_command) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=12, pady=6)

        label = ttk.Label(row, text=label_text, width=20)
        label.pack(side="left")

        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        button = ttk.Button(row, text="Browse", command=browse_command, width=10)
        button.pack(side="right")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(outer, text="P3D Host Monitor — Select Config Files")
        title.pack(anchor="w", pady=(0, 10))

        self._build_row(
            outer,
            "Central config:",
            self.central_var,
            self._browse_central,
        )
        self._build_row(
            outer,
            "Hosts config:",
            self.hosts_var,
            self._browse_hosts,
        )

        button_row = ttk.Frame(outer)
        button_row.pack(fill="x", pady=(12, 0))

        continue_btn = ttk.Button(button_row, text="Continue", command=self._on_continue)
        exit_btn = ttk.Button(button_row, text="Exit", command=self._on_exit)
        continue_btn.pack(side="right", padx=(6, 0))
        exit_btn.pack(side="right")

    def _browse_central(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Central Config File",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if selected:
            self.central_var.set(selected)

    def _browse_hosts(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select Hosts Config File",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if selected:
            self.hosts_var.set(selected)

    def _on_continue(self) -> None:
        try:
            central_path, hosts_path = validate_config_selection(
                self.central_var.get(),
                self.hosts_var.get(),
            )
        except FileNotFoundError as exc:
            messagebox.showerror("Config Error", str(exc))
            return
        except ValueError as exc:
            messagebox.showerror("Config Error", str(exc))
            return

        self.result = (str(central_path), str(hosts_path))
        self.root.quit()

    def _on_exit(self) -> None:
        self.result = None
        self.root.quit()

    def show(self) -> Optional[Tuple[str, str]]:
        try:
            self.root.mainloop()
        finally:
            try:
                self.root.destroy()
            except Exception:
                pass
        return self.result


def show_config_selector(initial_central: str, initial_hosts: str) -> Optional[Tuple[str, str]]:
    """Display the config selection dialog and return resolved paths or None."""
    return ConfigSelectorDialog(initial_central, initial_hosts).show()
