"""Static checks for Obsidian Publish sync user units."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"
SERVICE = UNITS_DIR / "hapax-obsidian-publish-sync.service"
TIMER = UNITS_DIR / "hapax-obsidian-publish-sync.timer"


def test_obsidian_publish_units_live_in_canonical_dir() -> None:
    assert SERVICE.exists()
    assert TIMER.exists()
    assert not (SYSTEMD_ROOT / SERVICE.name).exists()
    assert not (SYSTEMD_ROOT / TIMER.name).exists()


def test_obsidian_publish_service_invokes_repo_script_and_headless_bin() -> None:
    text = SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in text
    assert "WorkingDirectory=%h/Documents/Personal" in text
    assert "Environment=HAPAX_OBSIDIAN_VAULT=%h/Documents/Personal" in text
    assert (
        "Environment=HAPAX_OBSIDIAN_PUBLISH_CONFIG=%h/projects/hapax-council/config/obsidian-publish"
        in text
    )
    assert "Environment=HAPAX_OBSIDIAN_HEADLESS_BIN=%h/.npm-global/bin/ob" in text
    assert (
        "ExecStart=%h/projects/hapax-council/scripts/hapax-obsidian-publish-sync --install-headless"
        in text
    )


def test_obsidian_publish_timer_runs_the_service_periodically() -> None:
    text = TIMER.read_text(encoding="utf-8")

    assert "OnBootSec=10min" in text
    assert "OnUnitActiveSec=30min" in text
    assert "RandomizedDelaySec=5min" in text
    assert "Persistent=true" in text
    assert "Unit=hapax-obsidian-publish-sync.service" in text


def test_obsidian_publish_timer_is_preset_enabled() -> None:
    lines = {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "enable hapax-obsidian-publish-sync.timer" in lines
