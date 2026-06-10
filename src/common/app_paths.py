"""Application-root path resolution for both source and PyInstaller frozen builds.

When the application is packaged with PyInstaller into a single-file executable,
``__file__`` inside frozen modules resolves to the temporary extraction directory
(e.g. ``_MEIxxxxxx/``), which is recreated fresh on every launch.  Any files
written there are lost when the process exits.

Use :func:`get_app_root` instead of ``Path(__file__).parents[...]`` whenever you
need a stable, persistent location for data files such as the heartbeat metrics CSV.
"""

from __future__ import annotations

import sys
from pathlib import Path


def get_app_root() -> Path:
    """Return the application root directory.

    * **Frozen** (PyInstaller): returns the directory containing the ``.exe``
      so that data files written next to the executable persist across restarts.
    * **Source**: returns the repository root (two levels above ``src/common``).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]
