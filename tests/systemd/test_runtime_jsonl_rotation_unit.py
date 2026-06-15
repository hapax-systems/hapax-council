"""Systemd contract for the audit-w0 JSONL rotation owner."""

from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

UNITS = Path(__file__).resolve().parents[2] / "systemd" / "units"
SERVICE = "hapax-rotate-dispatch-recruitment-impingements.service"
TIMER = "hapax-rotate-dispatch-recruitment-impingements.timer"


def _parse_unit(name: str) -> ConfigParser:
    parser = ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(UNITS / name)
    return parser


def test_rotation_service_is_tracked_under_systemd_units() -> None:
    assert (UNITS / SERVICE).is_file()
    assert (UNITS / TIMER).is_file()
    assert "rotate" in SERVICE and "dispatch" in SERVICE


def test_rotation_service_runs_source_activated_rotator() -> None:
    parsed = _parse_unit(SERVICE)
    service = parsed["Service"]

    assert service["Type"] == "oneshot"
    assert service["WorkingDirectory"] == "%h/.cache/hapax/source-activation/worktree"
    assert "shared.runtime_jsonl_rotator" in service["ExecStart"]
    assert "--target all" in service["ExecStart"]
    assert "--json" in service["ExecStart"]


def test_rotation_timer_fires_frequently_and_enables_by_timer_target() -> None:
    parsed = _parse_unit(TIMER)

    assert parsed["Timer"]["Unit"] == SERVICE
    assert parsed["Timer"]["OnUnitActiveSec"] == "15min"
    assert parsed["Install"]["WantedBy"] == "timers.target"
