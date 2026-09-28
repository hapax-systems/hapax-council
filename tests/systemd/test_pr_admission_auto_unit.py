"""Static contract for the PR admission governor auto-cycle unit's start timeout."""

from __future__ import annotations

import configparser
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SERVICE = UNITS_DIR / "hapax-pr-admission-auto.service"
TIMER = UNITS_DIR / "hapax-pr-admission-auto.timer"

# Timer-driven ticks measured on appendix 2026-09-24 at 86-100 open PRs: median 166s,
# p95 228s, longest success 290s. At 30s the unit never completed a tick.
MEASURED_TICK_FLOOR_S = 300

_SPAN = re.compile(r"(\d+)\s*(min|s)\b")


def _seconds(span: str) -> int:
    parts = _SPAN.findall(span)
    assert parts, f"unparsed systemd time span: {span!r}"
    return sum(int(value) * (60 if unit == "min" else 1) for value, unit in parts)


def _read_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str  # preserve systemd key casing
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def _start_timeout() -> int:
    return _seconds(_read_unit(SERVICE).get("Service", "TimeoutStartSec"))


def test_start_timeout_covers_measured_tick() -> None:
    assert _start_timeout() >= MEASURED_TICK_FLOOR_S


def test_start_timeout_stays_inside_timer_cadence() -> None:
    cadence = _seconds(_read_unit(TIMER).get("Timer", "OnUnitActiveSec"))

    # A tick that cannot finish inside the cadence is a design signal, not a
    # reason to keep raising the timeout.
    assert _start_timeout() < cadence
