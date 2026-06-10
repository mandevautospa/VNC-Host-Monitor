from src.common.dis_monitor import (
    DisHostState,
    DisSample,
    DisStatus,
    PlaceholderCollector,
    check_dis_health,
)


class _FixedSampleCollector(PlaceholderCollector):
    def __init__(self, sample: DisSample) -> None:
        self._sample = sample

    def collect(self, host_name: str) -> DisSample:
        return self._sample


def test_dis_monitoring_defaults_to_enabled_when_section_present():
    result = check_dis_health(
        host_name="host-01",
        p3d_running=True,
        dis_config={"default_status_when_unavailable": "DIS_UNKNOWN"},
        host_dis_config={},
        collector=PlaceholderCollector(),
        state=DisHostState(),
    )

    assert result.dis_status == DisStatus.DIS_UNKNOWN


def test_dis_monitoring_respects_explicit_global_disable():
    result = check_dis_health(
        host_name="host-01",
        p3d_running=True,
        dis_config={"enabled": False},
        host_dis_config={},
        collector=PlaceholderCollector(),
        state=DisHostState(),
    )

    assert result.dis_status == DisStatus.DIS_DISABLED


def test_dis_monitoring_respects_explicit_host_disable():
    result = check_dis_health(
        host_name="host-01",
        p3d_running=True,
        dis_config={"enabled": True},
        host_dis_config={"enabled": False},
        collector=_FixedSampleCollector(
            DisSample(available=True, packets_total=100, bytes_total=1000)
        ),
        state=DisHostState(),
    )

    assert result.dis_status == DisStatus.DIS_DISABLED
