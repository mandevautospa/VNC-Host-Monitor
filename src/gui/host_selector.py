"""
Host selector GUI — startup interface for technician to choose which hosts to monitor.

Usage:
    selected_hosts = show_host_selector(all_hosts)
    if selected_hosts is None:
        print("User exited")
        sys.exit(0)
"""

import logging
import tkinter as tk
from tkinter import ttk
from typing import List, Optional

from src.common.models import HostConfig

logger = logging.getLogger(__name__)


def show_host_selector(hosts: List[HostConfig]) -> Optional[List[HostConfig]]:
    """
    Display a simple GUI for host selection.
    
    Args:
        hosts: List of HostConfig objects to display
        
    Returns:
        List of selected HostConfig objects, or None if user exited
    """
    # Handle empty host list
    if not hosts:
        logger.warning("show_host_selector called with empty host list")
        return []
    
    logger.info(f"Opening host selector with {len(hosts)} hosts")
    
    try:
        root = tk.Tk()
    except Exception as e:
        logger.error(f"Failed to initialize Tkinter: {e}")
        return None
    
    try:
        root.title("P3D Host Monitor — Select Active Hosts")
        root.geometry("400x450")
        root.resizable(False, False)
    except Exception as e:
        logger.error(f"Failed to configure root window: {e}")
        root.destroy()
        return None
    
    # Center on screen
    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    x = (root.winfo_screenwidth() // 2) - (w // 2)
    y = (root.winfo_screenheight() // 2) - (h // 2)
    root.geometry(f"+{x}+{y}")
    
    selected = None
    
    # Title label
    title = ttk.Label(
        root,
        text="Select hosts to monitor today:"
    )
    title.pack(pady=10, padx=10, anchor="w")
    
    # Frame for checkboxes with scrollbar
    canvas_frame = ttk.Frame(root)
    canvas_frame.pack(pady=5, padx=10, fill="both", expand=True)
    
    canvas = tk.Canvas(canvas_frame, bg="white", highlightthickness=0)
    scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
    scrollable = ttk.Frame(canvas, padding=5)
    
    scrollable.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas.create_window((0, 0), window=scrollable, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    
    # Checkboxes for each host
    check_vars = {}
    for host in hosts:
        var = tk.BooleanVar(value=True)  # Default: select all hosts
        check_vars[host.name] = var
        
        cb = ttk.Checkbutton(
            scrollable,
            text=host.name,
            variable=var
        )
        cb.pack(anchor="w", pady=3)
    
    # Button frame
    button_frame = ttk.Frame(root)
    button_frame.pack(pady=10, padx=10, fill="x")
    
    def on_start():
        nonlocal selected
        selected = [
            host for host in hosts
            if check_vars[host.name].get()
        ]
        root.quit()
    
    def on_exit():
        nonlocal selected
        selected = None
        root.quit()
    
    def on_window_close():
        nonlocal selected
        selected = None
        root.quit()
    
    start_btn = ttk.Button(
        button_frame,
        text="Start Monitoring",
        command=on_start,
        width=18
    )
    start_btn.pack(side="left", padx=2)
    
    exit_btn = ttk.Button(
        button_frame,
        text="Exit",
        command=on_exit,
        width=8
    )
    exit_btn.pack(side="right", padx=2)
    
    # Handle window close button (X)
    root.protocol("WM_DELETE_WINDOW", on_window_close)
    
    try:
        root.mainloop()
    except Exception as e:
        logger.error(f"GUI error during mainloop: {e}")
        selected = None
    finally:
        try:
            root.destroy()
        except Exception as e:
            logger.error(f"Error destroying window: {e}")
    
    if selected is None:
        logger.info("User closed host selector without selecting hosts")
    else:
        logger.info(f"User selected {len(selected)} hosts: {[h.name for h in selected]}")
    
    return selected
