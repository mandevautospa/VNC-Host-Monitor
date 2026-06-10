"""Tests for process_checks.check_p3d_process()."""

from unittest.mock import MagicMock, patch

import psutil
import pytest

from src.host_agent.process_checks import P3D_EXPECTED_NAMES, _normalize_name, check_p3d_process


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
    assert result.matched_process_name == "Prepar3D.exe"


def test_process_not_found_returns_not_running():
    proc = _make_proc("SomeOtherApp.exe")

    with patch("psutil.process_iter", return_value=[proc]):
        result = check_p3d_process("Prepar3D.exe")

    assert result.running is False
    assert result.pid is None
    assert result.matched_process_name is None


def test_access_denied_on_stats_still_reports_running():
    """AccessDenied while reading CPU/memory stats must not suppress the match."""
    proc = _make_proc("Prepar3D.exe", pid=5678)
    proc.cpu_percent.side_effect = psutil.AccessDenied(pid=5678)

    with patch("psutil.process_iter", return_value=[proc]):
        result = check_p3d_process("Prepar3D.exe")

    assert result.running is True
    assert result.pid == 5678
    assert result.cpu_percent is None
    assert result.memory_mb is None
    assert result.memory_percent is None
    assert result.error is None
    assert result.matched_process_name == "Prepar3D.exe"


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
    assert result.matched_process_name == "PREPAR3D.EXE"


# ── Multi-name / normalization tests ─────────────────────────────────────────

def test_list_of_names_matches_first_found():
    proc = _make_proc("Prepar3D.exe", pid=42)
    proc.cpu_percent.return_value = 10.0
    mem = MagicMock()
    mem.rss = 50 * 1024 * 1024
    proc.memory_info.return_value = mem
    proc.memory_percent.return_value = 5.0

    with patch("psutil.process_iter", return_value=[proc]):
        result = check_p3d_process(["Prepar3D.exe", "prepar3d.exe", "Prepar3D"])

    assert result.running is True
    assert result.matched_process_name == "Prepar3D.exe"


def test_exe_suffix_stripped_for_comparison():
    """'Prepar3D' (no .exe) in names should match a process named 'Prepar3D.exe'."""
    proc = _make_proc("Prepar3D.exe", pid=77)
    proc.cpu_percent.return_value = 0.5
    mem = MagicMock()
    mem.rss = 80 * 1024 * 1024
    proc.memory_info.return_value = mem
    proc.memory_percent.return_value = 8.0

    with patch("psutil.process_iter", return_value=[proc]):
        result = check_p3d_process("Prepar3D")  # no .exe

    assert result.running is True


def test_default_expected_names_constant():
    assert "Prepar3D.exe" in P3D_EXPECTED_NAMES
    assert "prepar3d.exe" in P3D_EXPECTED_NAMES
    assert "Prepar3D" in P3D_EXPECTED_NAMES
    assert "prepar3d" in P3D_EXPECTED_NAMES


def test_normalize_name():
    assert _normalize_name("Prepar3D.exe") == "prepar3d"
    assert _normalize_name("prepar3d.exe") == "prepar3d"
    assert _normalize_name("Prepar3D") == "prepar3d"
    assert _normalize_name("PREPAR3D.EXE") == "prepar3d"
    assert _normalize_name("notepad.exe") == "notepad"


def test_p3d_all_expected_names_match():
    """Every name in P3D_EXPECTED_NAMES should match a running 'Prepar3D.exe' process."""
    for name in P3D_EXPECTED_NAMES:
        proc = _make_proc("Prepar3D.exe", pid=1)
        proc.cpu_percent.return_value = 1.0
        mem = MagicMock()
        mem.rss = 10 * 1024 * 1024
        proc.memory_info.return_value = mem
        proc.memory_percent.return_value = 1.0
        with patch("psutil.process_iter", return_value=[proc]):
            result = check_p3d_process(name)
        assert result.running is True, f"Expected match for {name!r}"

