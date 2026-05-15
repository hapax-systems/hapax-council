"""Tests for the systemd + agent topology inventory script."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.hapax_topology_inventory import (
    InventoryReport,
    classify_service,
    parse_service_type,
    scan_agents,
    scan_units,
)


def test_service_type_detection(tmp_path: Path) -> None:
    (tmp_path / "oneshot.service").write_text("[Service]\nType=oneshot\n")
    (tmp_path / "simple.service").write_text("[Service]\nType=simple\n")
    (tmp_path / "notify.service").write_text("[Service]\nType=notify\n")
    (tmp_path / "default.service").write_text("[Service]\nExecStart=/bin/true\n")

    assert parse_service_type(tmp_path / "oneshot.service") == "oneshot"
    assert parse_service_type(tmp_path / "simple.service") == "simple"
    assert parse_service_type(tmp_path / "notify.service") == "notify"
    assert parse_service_type(tmp_path / "default.service") == "simple"


def test_timer_service_pairing(tmp_path: Path) -> None:
    (tmp_path / "health-monitor.service").write_text("[Service]\nType=oneshot\n")
    (tmp_path / "health-monitor.timer").write_text("[Timer]\nOnCalendar=*:0/15\n")
    (tmp_path / "orphan-daemon.service").write_text("[Service]\nType=simple\n")

    report = scan_units(tmp_path)
    assert len(report.timer_pairings) == 1
    assert report.timer_pairings[0] == ("health-monitor.timer", "health-monitor.service")
    orphan = next(s for s in report.services if s.name == "orphan-daemon.service")
    assert orphan.paired_timer is None


def test_governance_tier_classification() -> None:
    assert classify_service("hapax-audio-routing-check.service") == (0, "governance")
    assert classify_service("vram-watchdog.service") == (0, "governance")
    assert classify_service("hapax-usb-topology-witness.service") == (0, "governance")
    assert classify_service("hapax-daimonion-quarantine-watchdog.service") == (0, "governance")
    assert classify_service("hapax-broadcast-orchestrator.service") == (0, "governance")


def test_audio_egress_classification() -> None:
    assert classify_service("audio-recorder.service")[1] == "audio-egress"
    assert classify_service("hapax-broadcast-audio-health.service")[0] <= 1


def test_maintenance_classification() -> None:
    assert classify_service("hapax-backup-local.service") == (3, "maintenance")
    assert classify_service("cache-cleanup.service") == (3, "maintenance")
    assert classify_service("container-cleanup.service") == (3, "maintenance")


def test_agent_module_discovery(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    manifests_dir = tmp_path / "manifests"
    agents_dir.mkdir()
    manifests_dir.mkdir()

    (agents_dir / "alpha").mkdir()
    (agents_dir / "alpha" / "__main__.py").write_text("pass")
    (agents_dir / "beta").mkdir()
    (agents_dir / "beta" / "__main__.py").write_text("pass")
    (agents_dir / "gamma").mkdir()
    (agents_dir / "__pycache__").mkdir()

    (manifests_dir / "alpha.yaml").write_text("id: alpha")

    dirs, runnable, registered = scan_agents(agents_dir, manifests_dir)
    assert dirs == 3
    assert runnable == 2
    assert registered == 1


def test_check_mode_detects_stale_counts(tmp_path: Path) -> None:
    readme = tmp_path / "systemd" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text(
        "Timers: <!-- topology-inventory:timers -->5<!-- /topology-inventory:timers -->\n"
        "Services: <!-- topology-inventory:services -->10<!-- /topology-inventory:services -->\n"
    )

    report = InventoryReport()
    report.timers = [f"t{i}.timer" for i in range(5)]
    for i in range(10):
        from scripts.hapax_topology_inventory import ServiceInfo

        report.services.append(ServiceInfo(name=f"s{i}.service", unit_type="service"))

    with patch("scripts.hapax_topology_inventory.REPO_ROOT", tmp_path):
        from scripts.hapax_topology_inventory import check_mode

        assert check_mode(report) == 0

    report.timers.append("extra.timer")
    with patch("scripts.hapax_topology_inventory.REPO_ROOT", tmp_path):
        assert check_mode(report) == 1
