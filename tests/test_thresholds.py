"""
Unit tests for threshold evaluation functions.

These tests run without any real hosts, psutil calls, or network access.
"""

import pytest
from src.common.thresholds import Thresholds, evaluate_cpu, evaluate_ram, evaluate_disk


@pytest.fixture
def t():
    return Thresholds()


# ── CPU ──────────────────────────────────────────────────────────────────────

def test_cpu_ok(t):
    assert evaluate_cpu(50.0, t) == "OK"

def test_cpu_at_warning_boundary(t):
    assert evaluate_cpu(85.0, t) == "WARNING"

def test_cpu_above_warning(t):
    assert evaluate_cpu(90.0, t) == "WARNING"

def test_cpu_at_critical_boundary(t):
    assert evaluate_cpu(95.0, t) == "CRITICAL"

def test_cpu_above_critical(t):
    assert evaluate_cpu(99.0, t) == "CRITICAL"

def test_cpu_zero(t):
    assert evaluate_cpu(0.0, t) == "OK"


# ── RAM ──────────────────────────────────────────────────────────────────────

def test_ram_ok(t):
    assert evaluate_ram(70.0, t) == "OK"

def test_ram_at_warning_boundary(t):
    assert evaluate_ram(85.0, t) == "WARNING"

def test_ram_at_critical_boundary(t):
    assert evaluate_ram(92.0, t) == "CRITICAL"

def test_ram_above_critical(t):
    assert evaluate_ram(95.0, t) == "CRITICAL"


# ── Disk ─────────────────────────────────────────────────────────────────────

def test_disk_ok(t):
    assert evaluate_disk(50.0, 50.0, t) == "OK"

def test_disk_warning_by_percent(t):
    # 15 % free — below the 20 % warning threshold
    assert evaluate_disk(15.0, 50.0, t) == "WARNING"

def test_disk_warning_by_gb(t):
    # 15 GB free — below the 20 GB warning threshold
    assert evaluate_disk(50.0, 15.0, t) == "WARNING"

def test_disk_critical_by_percent(t):
    assert evaluate_disk(8.0, 50.0, t) == "CRITICAL"

def test_disk_critical_by_gb(t):
    assert evaluate_disk(50.0, 5.0, t) == "CRITICAL"

def test_disk_at_warning_boundary_percent(t):
    assert evaluate_disk(20.0, 50.0, t) == "WARNING"

def test_disk_at_critical_boundary_percent(t):
    assert evaluate_disk(10.0, 50.0, t) == "CRITICAL"

def test_disk_critical_wins_over_warning(t):
    # Both metrics below critical floor
    assert evaluate_disk(5.0, 5.0, t) == "CRITICAL"


# ── Custom thresholds ─────────────────────────────────────────────────────────

def test_custom_cpu_thresholds():
    t = Thresholds(cpu_warning_percent=70.0, cpu_critical_percent=90.0)
    assert evaluate_cpu(75.0, t) == "WARNING"
    assert evaluate_cpu(91.0, t) == "CRITICAL"
    assert evaluate_cpu(65.0, t) == "OK"
