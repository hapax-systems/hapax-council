"""Static activation checks for V5 publication/attribution timers."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"

V5_TIMERS = {
    "hapax-orcid-verifier.timer",
    "hapax-self-federate-rss.timer",
    "hapax-datacite-snapshot.timer",
    "hapax-datacite-mirror.timer",
}


def test_v5_timers_are_in_canonical_units_dir() -> None:
    for timer in sorted(V5_TIMERS):
        service = timer.removesuffix(".timer") + ".service"
        assert (UNITS_DIR / timer).exists(), f"{timer} must be install-visible"
        assert (UNITS_DIR / service).exists(), f"{service} must be install-visible"


def test_v5_timers_do_not_have_root_level_shadow_units() -> None:
    for timer in sorted(V5_TIMERS):
        service = timer.removesuffix(".timer") + ".service"
        assert not (SYSTEMD_ROOT / timer).exists(), f"{timer} shadows systemd/units"
        assert not (SYSTEMD_ROOT / service).exists(), f"{service} shadows systemd/units"


def test_v5_timers_are_preset_enabled() -> None:
    assert PRESET.exists(), "systemd preset file missing"
    preset_lines = {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    for timer in sorted(V5_TIMERS):
        assert f"enable {timer}" in preset_lines


def test_install_script_sweeps_canonical_units_only() -> None:
    install_script = SYSTEMD_ROOT / "scripts" / "install-units.sh"
    body = install_script.read_text(encoding="utf-8")
    assert 'REPO_DIR="$(cd "$(dirname "$0")/../units" && pwd)"' in body
    assert '"$REPO_DIR"/*.timer' in body
