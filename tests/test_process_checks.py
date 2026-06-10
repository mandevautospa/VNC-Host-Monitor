"""Tests for process_checks.check_p3d_process()."""

from unittest.mock import MagicMock, patch

import psutil
import pytest

from src.host_agent.process_checks import check_p3d_process


def _make_proc(name: str, pid: int = 1234) -> MagicMock:
    proc = MagicMock()
    proc.info = {"name": name, "pid": pid}
    return proc


def test_process_found_returns_running():
    proc = _make_proc("Prepar3D.exe")
    proc.cpu_percent.return_value = 15.0
    mem = MagicMock()
    mem.rss = 150 * 1024 * 1024
    proc.memory_info.return_value = mem
    proc.memory_percent.return_value = 20.0

    with patch("psutil.process_iter", return_value=[proc]):
        result = check_p3d_process("Prepar3D.exe")

    assert result.running is True
    assert result.pid == 1234
    assert result.cpu_percent == 15.0
    assert result.memory_mb == 150.0
    assert result.error is None


def test_process_not_found_returns_not_running():
    proc = _make_proc("SomeOtherApp.exe")

    with patch("psutil.process_iter", return_value=[proc]):
        result = check_p3d_process("Prepar3D.exe")

    assert result.running is False
    assert result.pid is None


def test_access_denied_on_stats_still_reports_running():
    """AccessDenied while reading CPU/memory stats must not suppress the match."""
    proc = _make_proc("Prepar3D.exe", pid=5678)
    proc.cpu_percent.side_effect = psutil.AccessDenied(pid=5678)

    with patch("psutil.process_iter", return_value=[proc]):
        result = check_p3d_process("Prepar3D.exe")

    assert result.running is True
    assert result.pid == 5678
    assert result.cpu_percent is None
    assert result.error is None


def test_no_such_process_during_iteration_is_skipped():
    """A process that disappears mid-iteration should be skipped, not crash."""
    vanishing = _make_proc("Prepar3D.exe", pid=111)
    vanishing.cpu_percent.side_effect = psutil.NoSuchProcess(pid=111)

    with patch("psutil.process_iter", return_value=[vanishing]):
        result = check_p3d_process("Prepar3D.exe")

    # Process vanished — treated as not running
    assert result.running is False


def test_case_insensitive_match():
    proc = _make_proc("PREPAR3D.EXE", pid=999)
    proc.cpu_percent.return_value = 5.0
    mem = MagicMock()
    mem.rss = 100 * 1024 * 1024
    proc.memory_info.return_value = mem
    proc.memory_percent.return_value = 10.0

    with patch("psutil.process_iter", return_value=[proc]):
        result = check_p3d_process("Prepar3D.exe")

    assert result.running is True
    assert result.pid == 999
