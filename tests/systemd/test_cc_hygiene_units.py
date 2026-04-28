"""Static install-path pins for cc-hygiene systemd units."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"

CC_HYGIENE_UNITS = {
    "hapax-cc-hygiene.timer",
    "hapax-cc-pr-merge-watcher.timer",
}


def test_cc_hygiene_units_are_in_canonical_units_dir() -> None:
    for timer in sorted(CC_HYGIENE_UNITS):
        service = timer.removesuffix(".timer") + ".service"
        assert (UNITS_DIR / timer).exists(), f"{timer} must be install-visible"
        assert (UNITS_DIR / service).exists(), f"{service} must be install-visible"


def test_cc_hygiene_units_do_not_have_root_level_shadows() -> None:
    for timer in sorted(CC_HYGIENE_UNITS):
        service = timer.removesuffix(".timer") + ".service"
        assert not (SYSTEMD_ROOT / timer).exists(), f"{timer} shadows systemd/units"
        assert not (SYSTEMD_ROOT / service).exists(), f"{service} shadows systemd/units"


def test_cc_hygiene_timers_are_preset_enabled() -> None:
    preset_lines = {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for timer in sorted(CC_HYGIENE_UNITS):
        assert f"enable {timer}" in preset_lines
