"""Tests for the local development fake heartbeat writer."""

from scripts.write_fake_heartbeat import build_heartbeat_payload


def test_fake_heartbeat_payload_matches_schema():
    payload = build_heartbeat_payload(
        host_name="host-01",
        p3d_running=True,
        cpu_percent=20.0,
        ram_percent=40.0,
        disk_free_percent=60.0,
        disk_free_gb=120.0,
    )

    assert payload["schema_version"] == "1.0"
    assert payload["host"] == "host-01"
    assert payload["watchdog_version"].startswith("dev-")
    assert payload["status"] == "HEALTHY"
    assert payload["p3d"]["running"] is True
    assert payload["tightvnc"]["service_running"] is True
    assert payload["resources"]["cpu_percent"] == 20.0
    assert payload["events"]["recent_app_crash_count"] == 0
    assert payload["errors"] == []


def test_fake_heartbeat_payload_can_simulate_problem_states():
    p3d_down = build_heartbeat_payload(
        host_name="host-01",
        p3d_running=False,
        cpu_percent=20.0,
        ram_percent=40.0,
        disk_free_percent=60.0,
        disk_free_gb=120.0,
    )
    assert p3d_down["status"] == "P3D_NOT_RUNNING"

    resource_warning = build_heartbeat_payload(
        host_name="host-01",
        p3d_running=True,
        cpu_percent=90.0,
        ram_percent=40.0,
        disk_free_percent=60.0,
        disk_free_gb=120.0,
    )
    assert resource_warning["status"] == "RESOURCE_WARNING"

    resource_critical = build_heartbeat_payload(
        host_name="host-01",
        p3d_running=True,
        cpu_percent=96.0,
        ram_percent=40.0,
        disk_free_percent=60.0,
        disk_free_gb=120.0,
    )
    assert resource_critical["status"] == "RESOURCE_CRITICAL"
