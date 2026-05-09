"""Tests for systemd timer override files — validates syntax and structure."""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest

OVERRIDES_DIR = Path(__file__).parent.parent / "systemd" / "overrides" / "rnd"

EXPECTED_TIMERS = [
    # Sync-pipeline timers (claude-code-sync, obsidian-sync, chrome-sync,
    # gdrive-sync) moved to Docker supercronic — no host overrides needed.
    "profile-update.timer",
    "digest.timer",
    "daily-briefing.timer",
    "drift-detector.timer",
    "knowledge-maint.timer",
]


def test_all_override_files_exist():
    for name in EXPECTED_TIMERS:
        assert (OVERRIDES_DIR / name).is_file(), f"Missing override: {name}"


@pytest.mark.parametrize("timer_name", EXPECTED_TIMERS)
def test_override_has_timer_section(timer_name):
    """Each override must have a [Timer] section with schedule directives."""
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.read(OVERRIDES_DIR / timer_name)
    assert "Timer" in parser.sections(), f"{timer_name} missing [Timer] section"
    timer_section = dict(parser["Timer"])
    has_schedule = any(k in timer_section for k in ("oncalendar", "onbootsec", "onunitactivesec"))
    assert has_schedule, f"{timer_name} has no schedule directive"


def test_override_count_matches():
    """No extra override files beyond the expected set."""
    actual = {f.name for f in OVERRIDES_DIR.glob("*.timer")}
    assert actual == set(EXPECTED_TIMERS)
