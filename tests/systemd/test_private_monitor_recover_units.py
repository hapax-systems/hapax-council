"""Systemd contract for private monitor witness refresh."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
SERVICE = UNITS_DIR / "hapax-private-monitor-recover.service"
TIMER = UNITS_DIR / "hapax-private-monitor-recover.timer"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"


def test_private_monitor_recover_units_are_install_visible() -> None:
    assert SERVICE.exists(), "private monitor recover service must live under systemd/units"
    assert TIMER.exists(), "private monitor recover timer must live under systemd/units"
    assert not (SYSTEMD_ROOT / SERVICE.name).exists(), "service shadows systemd/units"
    assert not (SYSTEMD_ROOT / TIMER.name).exists(), "timer shadows systemd/units"


def test_private_monitor_recover_service_publishes_blocked_absent_as_success() -> None:
    service = SERVICE.read_text(encoding="utf-8")

    assert "WorkingDirectory=" in service
    assert "hapax-private-monitor-recover" in service
    assert "--repo-root" in service
    assert "--install" in service
    assert "--dump-file" not in service
    assert "SuccessExitStatus=2" in service
    assert "After=pipewire.service pipewire-pulse.service wireplumber.service" in service


def test_private_monitor_recover_timer_keeps_router_freshness_inside_ttl() -> None:
    timer = TIMER.read_text(encoding="utf-8")

    assert "OnBootSec=30s" in timer
    assert "OnUnitActiveSec=60s" in timer
    assert "AccuracySec=10s" in timer
    assert "Unit=hapax-private-monitor-recover.service" in timer
    assert "Persistent=false" in timer


def test_private_monitor_recover_timer_is_preset_enabled() -> None:
    preset = PRESET.read_text(encoding="utf-8")

    assert "enable hapax-private-monitor-recover.timer" in preset
