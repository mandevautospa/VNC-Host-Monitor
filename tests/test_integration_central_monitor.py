"""
Integration test for central_monitor with mock heartbeat files and network conditions.

This test simulates a complete monitoring cycle with:
- Mock heartbeat files for each host
- Mock ping and VNC checks
- Real state evaluation and alerting logic

Run:
    pytest tests/test_integration_central_monitor.py -v
"""

import json
import logging
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.common.models import HostConfig, HostStatus, PingResult, VncResult, HeartbeatResult
from src.central_monitor.central_monitor import (
    _is_within_active_hours,
    _select_alert_threshold,
    _build_alert_detail,
)
from src.central_monitor.state_evaluator import evaluate_host_status
from src.common.thresholds import Thresholds, evaluate_cpu, evaluate_ram, evaluate_disk


class TestIntegrationCentralMonitor(unittest.TestCase):
    """Integration tests for central monitor."""

    def setUp(self):
        """Create temporary directory for mock heartbeat files."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.logger = logging.getLogger("test_integration")

    def tearDown(self):
        """Clean up temporary directory."""
        self.temp_dir.cleanup()

    def _create_heartbeat_file(self, host_name: str, age_seconds: int = 30) -> Path:
        """
        Create a mock heartbeat file for testing.
        
        Args:
            host_name: Name of the host
            age_seconds: How old the file should be (0 = fresh)
            
        Returns:
            Path to the created heartbeat file
        """
        now = datetime.now(timezone.utc).isoformat()
        heartbeat_data = {
            "schema_version": "1.0",
            "host": host_name,
            "timestamp": now,
            "watchdog_version": "1.0",
            "status": "HEALTHY",
            "p3d": {
                "running": True,
                "hang_suspected": False,
                "cpu_percent": 45.5,
            },
            "tightvnc": {
                "service_running": True,
            },
            "resources": {
                "cpu_percent": 45.5,
                "ram_percent": 62.0,
                "disk_free_percent": 35.0,
                "disk_free_gb": 150.0,
            },
            "events": {
                "recent_app_crash_count": 0,
                "recent_app_hang_count": 0,
            },
            "errors": [],
        }

        file_path = self.temp_path / f"{host_name}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(heartbeat_data, f)

        # Set file modification time to simulate age
        if age_seconds > 0:
            mtime = time.time() - age_seconds
            Path(file_path).touch()
            import os
            os.utime(file_path, (mtime, mtime))

        return file_path

    def test_fresh_heartbeat_healthy_network(self):
        """Test: Fresh heartbeat + passing network checks = HEALTHY."""
        heartbeat_path = self._create_heartbeat_file("host-01", age_seconds=15)

        # Read heartbeat
        from src.central_monitor.heartbeat_reader import read_heartbeat

        hb_result = read_heartbeat(str(heartbeat_path), stale_seconds=90)
        
        # Flatten the heartbeat data as central_monitor does
        d = hb_result.data or {}
        host_reported = {
            "status": d.get("status", "UNKNOWN"),
            "p3d_running": d.get("p3d", {}).get("running"),
            "p3d_hang_suspected": d.get("p3d", {}).get("hang_suspected"),
            "recent_app_crash_count": 0,
            "recent_app_hang_count": 0,
        }

        # Build result dict as central_monitor does
        result = {
            "host": "host-01",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": True,
                "vnc_banner_ok": True,
            },
            "heartbeat": {
                "exists": hb_result.exists,
                "fresh": hb_result.fresh,
            },
            "host_reported": host_reported,
        }

        # Evaluate status
        status = evaluate_host_status(result)

        self.assertEqual(status, HostStatus.HEALTHY, f"Expected HEALTHY, got {status}")
        self.assertTrue(hb_result.fresh, "Heartbeat should be fresh")

    def test_stale_heartbeat_detection(self):
        """Test: Stale heartbeat (>90s old) = HEARTBEAT_STALE."""
        heartbeat_path = self._create_heartbeat_file("host-02", age_seconds=120)

        from src.central_monitor.heartbeat_reader import read_heartbeat

        hb_result = read_heartbeat(str(heartbeat_path), stale_seconds=90)

        result = {
            "host": "host-02",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": True,
                "vnc_banner_ok": True,
            },
            "heartbeat": {
                "exists": hb_result.exists,
                "fresh": hb_result.fresh,
            },
            "host_reported": hb_result.data or {},
        }

        status = evaluate_host_status(result)

        self.assertEqual(
            status,
            HostStatus.HEARTBEAT_STALE,
            f"Expected HEARTBEAT_STALE, got {status}",
        )
        self.assertGreater(hb_result.age_seconds, 90)

    def test_missing_heartbeat_with_good_network(self):
        """Test: Missing heartbeat file = HEALTHY (if ping + VNC OK, assume not deployed yet)."""
        missing_path = self.temp_path / "host-03.json"

        from src.central_monitor.heartbeat_reader import read_heartbeat

        hb_result = read_heartbeat(str(missing_path), stale_seconds=90)

        result = {
            "host": "host-03",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": True,
                "vnc_banner_ok": True,
            },
            "heartbeat": {
                "exists": hb_result.exists,
                "fresh": False,
            },
            "host_reported": {},
        }

        status = evaluate_host_status(result)

        # If network OK but no heartbeat, treated as HEALTHY (not penalized)
        self.assertEqual(status, HostStatus.HEALTHY)

    def test_ping_failure_unreachable(self):
        """Test: Ping fails = HOST_UNREACHABLE."""
        result = {
            "host": "host-04",
            "network": {
                "ping_ok": False,
                "vnc_port_ok": None,
                "vnc_banner_ok": None,
            },
            "heartbeat": {
                "exists": False,
                "fresh": False,
            },
            "host_reported": {},
        }

        status = evaluate_host_status(result)

        self.assertEqual(
            status,
            HostStatus.HOST_UNREACHABLE,
            f"Expected HOST_UNREACHABLE, got {status}",
        )

    def test_vnc_port_closed(self):
        """Test: VNC port closed = VNC_DOWN."""
        result = {
            "host": "host-05",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": False,
                "vnc_banner_ok": True,
            },
            "heartbeat": {
                "exists": False,
                "fresh": False,
            },
            "host_reported": {},
        }

        status = evaluate_host_status(result)

        self.assertEqual(status, HostStatus.VNC_DOWN, f"Expected VNC_DOWN, got {status}")

    def test_vnc_banner_wrong(self):
        """Test: VNC banner not RFB = VNC_DOWN."""
        result = {
            "host": "host-06",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": True,
                "vnc_banner_ok": False,
            },
            "heartbeat": {
                "exists": False,
                "fresh": False,
            },
            "host_reported": {},
        }

        status = evaluate_host_status(result)

        self.assertEqual(status, HostStatus.VNC_DOWN, f"Expected VNC_DOWN, got {status}")

    def test_p3d_crash_detected(self):
        """Test: Recent crash events = P3D_CRASH_DETECTED."""
        heartbeat_path = self._create_heartbeat_file("host-07", age_seconds=30)

        from src.central_monitor.heartbeat_reader import read_heartbeat

        hb_result = read_heartbeat(str(heartbeat_path), stale_seconds=90)
        
        # Flatten the heartbeat data as central_monitor does
        d = hb_result.data or {}
        host_reported = {
            "status": d.get("status", "UNKNOWN"),
            "p3d_running": d.get("p3d", {}).get("running"),
            "p3d_hang_suspected": d.get("p3d", {}).get("hang_suspected"),
            "recent_app_crash_count": 1,  # Set to trigger crash detection
            "recent_app_hang_count": 0,
        }

        result = {
            "host": "host-07",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": True,
                "vnc_banner_ok": True,
            },
            "heartbeat": {
                "exists": hb_result.exists,
                "fresh": hb_result.fresh,
            },
            "host_reported": host_reported,
        }

        status = evaluate_host_status(result)

        self.assertEqual(
            status,
            HostStatus.P3D_CRASH_DETECTED,
            f"Expected P3D_CRASH_DETECTED, got {status}",
        )

    def test_p3d_not_running(self):
        """Test: P3D process not running = P3D_NOT_RUNNING."""
        heartbeat_path = self._create_heartbeat_file("host-08", age_seconds=30)

        from src.central_monitor.heartbeat_reader import read_heartbeat

        hb_result = read_heartbeat(str(heartbeat_path), stale_seconds=90)
        
        # Flatten the heartbeat data as central_monitor does
        d = hb_result.data or {}
        host_reported = {
            "status": d.get("status", "UNKNOWN"),
            "p3d_running": False,  # Set to trigger not running
            "p3d_hang_suspected": False,
            "recent_app_crash_count": 0,
            "recent_app_hang_count": 0,
        }

        result = {
            "host": "host-08",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": True,
                "vnc_banner_ok": True,
            },
            "heartbeat": {
                "exists": hb_result.exists,
                "fresh": hb_result.fresh,
            },
            "host_reported": host_reported,
        }

        status = evaluate_host_status(result)

        self.assertEqual(
            status,
            HostStatus.P3D_NOT_RUNNING,
            f"Expected P3D_NOT_RUNNING, got {status}",
        )

    def test_resource_critical(self):
        """Test: CPU above critical threshold (status = RESOURCE_CRITICAL)."""
        heartbeat_path = self._create_heartbeat_file("host-09", age_seconds=30)

        from src.central_monitor.heartbeat_reader import read_heartbeat

        hb_result = read_heartbeat(str(heartbeat_path), stale_seconds=90)
        data = hb_result.data or {}
        data["status"] = "RESOURCE_CRITICAL"
        data["resources"]["cpu_percent"] = 98.0

        result = {
            "host": "host-09",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": True,
                "vnc_banner_ok": True,
            },
            "heartbeat": {
                "exists": hb_result.exists,
                "fresh": hb_result.fresh,
            },
            "host_reported": data,
        }

        status = evaluate_host_status(result)

        self.assertEqual(
            status,
            HostStatus.RESOURCE_CRITICAL,
            f"Expected RESOURCE_CRITICAL, got {status}",
        )

    def test_resource_warning(self):
        """Test: RAM above warning threshold (status = RESOURCE_WARNING)."""
        heartbeat_path = self._create_heartbeat_file("host-10", age_seconds=30)

        from src.central_monitor.heartbeat_reader import read_heartbeat

        hb_result = read_heartbeat(str(heartbeat_path), stale_seconds=90)
        data = hb_result.data or {}
        data["status"] = "RESOURCE_WARNING"
        data["resources"]["ram_percent"] = 88.0
        data["resources"]["cpu_percent"] = 50.0

        result = {
            "host": "host-10",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": True,
                "vnc_banner_ok": True,
            },
            "heartbeat": {
                "exists": hb_result.exists,
                "fresh": hb_result.fresh,
            },
            "host_reported": data,
        }

        status = evaluate_host_status(result)

        self.assertEqual(
            status,
            HostStatus.RESOURCE_WARNING,
            f"Expected RESOURCE_WARNING, got {status}",
        )

    def test_disk_critical_by_percent(self):
        """Test: Disk < 10% free (status = RESOURCE_CRITICAL)."""
        heartbeat_path = self._create_heartbeat_file("host-11", age_seconds=30)

        from src.central_monitor.heartbeat_reader import read_heartbeat

        hb_result = read_heartbeat(str(heartbeat_path), stale_seconds=90)
        data = hb_result.data or {}
        data["status"] = "RESOURCE_CRITICAL"
        data["resources"]["disk_free_percent"] = 5.0
        data["resources"]["disk_free_gb"] = 100.0

        result = {
            "host": "host-11",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": True,
                "vnc_banner_ok": True,
            },
            "heartbeat": {
                "exists": hb_result.exists,
                "fresh": hb_result.fresh,
            },
            "host_reported": data,
        }

        status = evaluate_host_status(result)

        self.assertEqual(
            status,
            HostStatus.RESOURCE_CRITICAL,
            f"Expected RESOURCE_CRITICAL, got {status}",
        )

    def test_disk_critical_by_gb(self):
        """Test: Disk < 10GB free (status = RESOURCE_CRITICAL)."""
        heartbeat_path = self._create_heartbeat_file("host-12", age_seconds=30)

        from src.central_monitor.heartbeat_reader import read_heartbeat

        hb_result = read_heartbeat(str(heartbeat_path), stale_seconds=90)
        data = hb_result.data or {}
        data["status"] = "RESOURCE_CRITICAL"
        data["resources"]["disk_free_percent"] = 50.0
        data["resources"]["disk_free_gb"] = 5.0

        result = {
            "host": "host-12",
            "network": {
                "ping_ok": True,
                "vnc_port_ok": True,
                "vnc_banner_ok": True,
            },
            "heartbeat": {
                "exists": hb_result.exists,
                "fresh": hb_result.fresh,
            },
            "host_reported": data,
        }

        status = evaluate_host_status(result)

        self.assertEqual(
            status,
            HostStatus.RESOURCE_CRITICAL,
            f"Expected RESOURCE_CRITICAL (GB-based), got {status}",
        )

    def test_active_hours_logic(self):
        """Test: Active hours configuration correctly parsed and evaluated."""
        config_enabled = {
            "active_hours": {
                "enabled": True,
                "start": "07:00",
                "end": "18:00",
            }
        }

        config_disabled = {"active_hours": {"enabled": False}}

        # Active hours disabled → always active
        self.assertTrue(_is_within_active_hours(config_disabled))

        # Active hours enabled, check at specific times
        from datetime import time as dt_time, datetime

        # 12:00 (noon) → within 07:00-18:00
        dt_noon = datetime(2026, 5, 10, 12, 0, 0)
        self.assertTrue(_is_within_active_hours(config_enabled, dt_noon))

        # 22:00 (10 PM) → outside 07:00-18:00
        dt_night = datetime(2026, 5, 10, 22, 0, 0)
        self.assertFalse(_is_within_active_hours(config_enabled, dt_night))

    def test_alert_threshold_selection(self):
        """Test: Alert threshold selection based on status and active hours."""
        # Critical status → use critical threshold
        threshold = _select_alert_threshold(
            HostStatus.HOST_UNREACHABLE,
            alert_threshold=3,
            critical_threshold=2,
            is_active_hours=False,
        )
        self.assertEqual(threshold, 2)

        # P3D_NOT_RUNNING during active hours → use critical threshold
        threshold = _select_alert_threshold(
            HostStatus.P3D_NOT_RUNNING,
            alert_threshold=3,
            critical_threshold=2,
            is_active_hours=True,
        )
        self.assertEqual(threshold, 2)

        # P3D_NOT_RUNNING outside active hours → use alert threshold
        threshold = _select_alert_threshold(
            HostStatus.P3D_NOT_RUNNING,
            alert_threshold=3,
            critical_threshold=2,
            is_active_hours=False,
        )
        self.assertEqual(threshold, 3)

    def test_threshold_evaluators(self):
        """Test: Resource threshold evaluation logic."""
        t = Thresholds()

        # CPU tests
        self.assertEqual(evaluate_cpu(50.0, t), "OK")
        self.assertEqual(evaluate_cpu(87.0, t), "WARNING")
        self.assertEqual(evaluate_cpu(96.0, t), "CRITICAL")

        # RAM tests
        self.assertEqual(evaluate_ram(70.0, t), "OK")
        self.assertEqual(evaluate_ram(88.0, t), "WARNING")
        self.assertEqual(evaluate_ram(93.0, t), "CRITICAL")

        # Disk tests (OR logic: either percent or GB can trigger)
        self.assertEqual(evaluate_disk(50.0, 100.0, t), "OK")
        self.assertEqual(evaluate_disk(15.0, 100.0, t), "WARNING")
        self.assertEqual(evaluate_disk(50.0, 15.0, t), "WARNING")
        self.assertEqual(evaluate_disk(5.0, 100.0, t), "CRITICAL")
        self.assertEqual(evaluate_disk(50.0, 5.0, t), "CRITICAL")

    def test_heartbeat_file_read_error_handling(self):
        """Test: Graceful handling of malformed heartbeat files."""
        bad_json_path = self.temp_path / "bad.json"
        with open(bad_json_path, "w") as f:
            f.write("{invalid json content")

        from src.central_monitor.heartbeat_reader import read_heartbeat

        hb_result = read_heartbeat(str(bad_json_path), stale_seconds=90)

        self.assertTrue(hb_result.exists)
        self.assertFalse(hb_result.fresh)
        self.assertIn("JSON", hb_result.error)


if __name__ == "__main__":
    unittest.main()
