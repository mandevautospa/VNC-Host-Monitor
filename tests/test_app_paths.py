"""Tests for src.common.app_paths.get_app_root()."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from src.common.app_paths import get_app_root


# ---------------------------------------------------------------------------
# Source-mode (not frozen)
# ---------------------------------------------------------------------------

def test_get_app_root_source_mode_returns_repo_root():
    """In source mode (sys.frozen not set) get_app_root() returns the repo root."""
    with mock.patch.object(sys, "frozen", False, create=True):
        root = get_app_root()

    # The repo root must contain src/ and config/ directories.
    assert (root / "src").is_dir(), f"Expected src/ under {root}"
    assert (root / "config").is_dir(), f"Expected config/ under {root}"


def test_get_app_root_source_mode_not_inside_temp():
    """In source mode the returned path must not be a system temp directory."""
    import tempfile

    with mock.patch.object(sys, "frozen", False, create=True):
        root = get_app_root()

    temp_root = Path(tempfile.gettempdir()).resolve()
    assert not str(root).startswith(str(temp_root)), (
        f"get_app_root() returned a temp path: {root}"
    )


# ---------------------------------------------------------------------------
# Frozen mode (PyInstaller)
# ---------------------------------------------------------------------------

def test_get_app_root_frozen_mode_uses_executable_parent(tmp_path):
    """In frozen mode get_app_root() must return the directory of sys.executable."""
    fake_exe = tmp_path / "P3DMonitorGUI.exe"
    fake_exe.write_text("")  # create the file so .resolve() works

    with (
        mock.patch.object(sys, "frozen", True, create=True),
        mock.patch.object(sys, "executable", str(fake_exe)),
    ):
        root = get_app_root()

    assert root == tmp_path.resolve()


def test_get_app_root_frozen_mode_does_not_use_file_path(tmp_path):
    """In frozen mode the result must NOT be derived from __file__ (temp dir)."""
    fake_exe = tmp_path / "dist" / "P3DMonitorGUI.exe"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_text("")

    with (
        mock.patch.object(sys, "frozen", True, create=True),
        mock.patch.object(sys, "executable", str(fake_exe)),
    ):
        root = get_app_root()

    # The result must equal the exe directory, not anything derived from __file__.
    assert root == fake_exe.parent.resolve()


# ---------------------------------------------------------------------------
# DEFAULT_CSV_PATH derives from get_app_root()
# ---------------------------------------------------------------------------

def test_default_csv_path_under_app_root():
    """DEFAULT_CSV_PATH must sit inside get_app_root() / analysis/."""
    from src.common.heartbeat_csv import DEFAULT_CSV_PATH

    root = get_app_root()
    expected = root / "analysis" / "heartbeat_metrics.csv"
    assert DEFAULT_CSV_PATH == expected


def test_default_csv_path_not_in_temp_dir():
    """DEFAULT_CSV_PATH must not point into a system temp directory."""
    import tempfile
    from src.common.heartbeat_csv import DEFAULT_CSV_PATH

    temp_root = Path(tempfile.gettempdir()).resolve()
    assert not str(DEFAULT_CSV_PATH).startswith(str(temp_root)), (
        f"DEFAULT_CSV_PATH resolves to a temp path: {DEFAULT_CSV_PATH}"
    )
