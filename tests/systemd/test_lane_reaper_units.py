"""Pins for the parked transitional lane-reaper compatibility units."""

from __future__ import annotations

import configparser
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
UNIT_NAMES = ("hapax-lane-reaper.service", "hapax-lane-reaper.timer")


def _text(name: str) -> str:
    return (UNITS_DIR / name).read_text(encoding="utf-8")


def _unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(_text(name))
    return parser


@pytest.mark.parametrize("name", UNIT_NAMES)
def test_lane_reaper_units_are_truthfully_parked_and_non_notifying(name: str) -> None:
    text = _text(name)
    description = _unit(name)["Unit"]["Description"]

    assert text.splitlines()[0] == "# Hapax-Parked: true"
    for required in ("Hapax Parked", "legacy", "tmux", "inventory", "projection"):
        assert required in description
    assert not re.search(r"\b(?:kill|reap|clean|recover|scan)\w*\b", description, re.I)
    assert "OnFailure=" not in text
    assert "Hapax-Auto-Enable" not in text
    assert "Hapax-Timer-Enable-Only" not in text
    assert "[Install]" not in text
    assert "WantedBy=" not in text


def test_lane_reaper_service_uses_deploy_maintained_local_bin() -> None:
    unit = _unit("hapax-lane-reaper.service")
    text = _text("hapax-lane-reaper.service")

    assert unit["Service"]["ExecStart"] == ("%h/.local/bin/hapax-lane-reaper --threshold 30")
    assert "projects/hapax-council" not in text


def test_lane_reaper_timer_retains_only_inert_compatibility_cadence() -> None:
    unit = _unit("hapax-lane-reaper.timer")

    assert set(unit["Timer"]) == {"OnBootSec", "OnUnitActiveSec", "RandomizedDelaySec"}
    assert unit["Timer"]["OnUnitActiveSec"] == "30min"
