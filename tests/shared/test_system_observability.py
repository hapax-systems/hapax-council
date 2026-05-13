from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence

from shared.system_observability import (
    ObservationState,
    RemediationMode,
    build_report,
    collect_resource_pressure,
    parse_failed_systemd_units,
)


class FakeRunner:
    def __init__(self, responses: dict[str, subprocess.CompletedProcess[str]]) -> None:
        self.responses = responses

    def __call__(
        self, args: Sequence[str], timeout: float = 10.0
    ) -> subprocess.CompletedProcess[str]:
        key = " ".join(args)
        return self.responses[key]


def completed(
    stdout: str, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_parse_failed_systemd_units_handles_bullet_output() -> None:
    text = """
● hapax-backup-local.service             loaded failed failed Hapax Local Backup
● hapax-usb-bandwidth-preflight.service  loaded failed failed Hapax USB bandwidth preflight
"""

    assert parse_failed_systemd_units(text) == [
        "hapax-backup-local.service",
        "hapax-usb-bandwidth-preflight.service",
    ]


def test_failed_systemd_units_become_incident_candidates() -> None:
    runner = FakeRunner(
        {
            "systemctl --user --failed --no-legend --plain": completed(
                "● hapax-backup-local.service loaded failed failed Hapax Local Backup\n"
            )
        }
    )

    report = build_report(
        include_rte=False,
        include_resources=False,
        runner=runner,
        observed_at="2026-05-08T18:55:00Z",
    )

    assert report.overall_state == ObservationState.WARN
    assert [c.entity_id for c in report.incident_candidates] == [
        "systemd.user-unit.hapax-backup-local.service"
    ]
    assert report.incident_candidates[0].remediation_mode == RemediationMode.DETERMINISTIC


def test_health_monitor_systemd_healthy_cannot_hide_failed_units() -> None:
    runner = FakeRunner(
        {
            "systemctl --user --failed --no-legend --plain": completed(
                "● hapax-backup-local.service loaded failed failed Hapax Local Backup\n"
            )
        }
    )
    health_report = {
        "overall_status": "healthy",
        "summary": "all good",
        "groups": [
            {
                "group": "systemd",
                "status": "healthy",
                "healthy_count": 5,
                "degraded_count": 0,
                "failed_count": 0,
            }
        ],
    }

    report = build_report(
        include_rte=False,
        include_resources=False,
        health_report=health_report,
        runner=runner,
        observed_at="2026-05-08T18:55:00Z",
    )

    candidate_ids = {candidate.candidate_id for candidate in report.incident_candidates}
    assert "systemd.user-unit.hapax-backup-local.service.liveness.fail" in candidate_ids
    assert "health-monitor.systemd.source-disagreement" in candidate_ids
    assert report.overall_state == ObservationState.FAIL


def test_stale_rte_tick_becomes_high_severity_candidate(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_RTE_STATE_CMD", "/tmp/hapax-rte-state")
    payload = {
        "status": "unknown",
        "tick_age_s": 97366.0,
        "tick_path": "/home/hapax/.cache/hapax/relay/rte-tick-old.yaml",
    }
    runner = FakeRunner(
        {
            "systemctl --user --failed --no-legend --plain": completed(""),
            "/tmp/hapax-rte-state --json": completed(
                json.dumps(payload),
                returncode=3,
            ),
        }
    )

    report = build_report(
        include_resources=False,
        runner=runner,
        observed_at="2026-05-08T18:55:00Z",
    )

    assert report.overall_state == ObservationState.FAIL
    assert report.incident_candidates[0].entity_id == "coordination.rte"
    assert report.incident_candidates[0].remediation_mode == RemediationMode.SESSION_REPAIR


def test_unknown_rte_state_is_not_treated_as_passing(monkeypatch) -> None:
    monkeypatch.setenv("HAPAX_RTE_STATE_CMD", "/tmp/hapax-rte-state")
    payload = {
        "status": "unknown",
        "reasons": ["no RTE tick log found"],
        "tick_age_s": None,
        "tick_path": None,
    }
    runner = FakeRunner(
        {
            "systemctl --user --failed --no-legend --plain": completed(""),
            "/tmp/hapax-rte-state --json": completed(
                json.dumps(payload),
                returncode=3,
            ),
        }
    )

    report = build_report(
        include_resources=False,
        runner=runner,
        observed_at="2026-05-08T18:55:00Z",
    )

    assert report.overall_state == ObservationState.WARN
    assert report.incident_candidates[0].entity_id == "coordination.rte"
    assert "exit 3" in report.incident_candidates[0].reason


def test_resource_pressure_splits_ram_zram_and_swappiness_classes() -> None:
    _, observations = collect_resource_pressure(
        meminfo={
            "MemTotal": 128 * 1024**3,
            "MemAvailable": 67 * 1024**3,
        },
        swaps=[],
        swappiness_value=150,
        expected_swappiness=10,
        observed_at="2026-05-13T18:55:00Z",
    )

    by_class = {obs.raw["pressure_class"]: obs for obs in observations}

    assert by_class["global_ram_pressure"].state == ObservationState.PASS
    assert by_class["zram_saturation"].state == ObservationState.PASS
    assert by_class["sysctl_drift"].state == ObservationState.FAIL
    assert by_class["sysctl_drift"].source == "/proc/sys/vm/swappiness"


def test_resource_pressure_zram_saturation_does_not_claim_global_ram_exhaustion() -> None:
    from shared.memory_pressure import parse_proc_swaps

    swaps = parse_proc_swaps(
        "\n".join(
            [
                "Filename Type Size Used Priority",
                "/dev/zram0 partition 33554432 33554432 100",
            ]
        )
    )
    _, observations = collect_resource_pressure(
        meminfo={
            "MemTotal": 128 * 1024**3,
            "MemAvailable": 67 * 1024**3,
        },
        swaps=swaps,
        swappiness_value=10,
        observed_at="2026-05-13T18:55:00Z",
    )

    by_class = {obs.raw["pressure_class"]: obs for obs in observations}

    assert by_class["global_ram_pressure"].state == ObservationState.PASS
    assert by_class["zram_saturation"].state == ObservationState.FAIL
    assert by_class["zram_saturation"].entity_id == "host.swap"
