"""Static checks for the Daimonion quarantine watchdog units."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"
SERVICE = UNITS_DIR / "hapax-daimonion-quarantine-watchdog.service"
TIMER = UNITS_DIR / "hapax-daimonion-quarantine-watchdog.timer"


def test_daimonion_quarantine_watchdog_units_are_install_visible() -> None:
    assert SERVICE.exists(), "quarantine watchdog service must live under systemd/units"
    assert TIMER.exists(), "quarantine watchdog timer must live under systemd/units"
    assert not (SYSTEMD_ROOT / SERVICE.name).exists(), "service shadows systemd/units"
    assert not (SYSTEMD_ROOT / TIMER.name).exists(), "timer shadows systemd/units"


def test_daimonion_quarantine_watchdog_service_enforces_only_containment() -> None:
    service = SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in service
    assert "hapax-daimonion-quarantine-watchdog --enforce" in service
    assert "SuccessExitStatus=2" in service
    assert "TimeoutStartSec=60s" in service
    assert "restart hapax-daimonion" not in service
    assert "unmask" not in service
    assert "unmute" not in service
    assert "After=pipewire.service pipewire-pulse.service wireplumber.service" in service


def test_daimonion_quarantine_watchdog_timer_is_frequent_while_incident_active() -> None:
    timer = TIMER.read_text(encoding="utf-8")

    assert "OnBootSec=15s" in timer
    assert "OnUnitActiveSec=30s" in timer
    assert "AccuracySec=5s" in timer
    assert "Persistent=false" in timer
    assert "Unit=hapax-daimonion-quarantine-watchdog.service" in timer


def test_daimonion_quarantine_watchdog_timer_is_preset_enabled() -> None:
    preset_lines = {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "enable hapax-daimonion-quarantine-watchdog.timer" in preset_lines
