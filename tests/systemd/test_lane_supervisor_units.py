"""FM-11 lane supervisor systemd units (coordination-reform 2026-05-30 Phase 6).

Pins the supervisor oneshot+timer and the Restart=always+StartLimit hardening
of the claude lane template unit, so the "dead lanes always auto-restart"
mandate cannot silently regress to the old Restart=no.
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SUPERVISOR_SERVICE = UNITS_DIR / "hapax-lane-supervisor.service"
SUPERVISOR_TIMER = UNITS_DIR / "hapax-lane-supervisor.timer"
CLAUDE_LANE = UNITS_DIR / "hapax-claude-lane@.service"


def _load(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # preserve case (systemd keys are CamelCase)
    parser.read(path, encoding="utf-8")
    return parser


def test_supervisor_service_is_oneshot_running_the_supervisor() -> None:
    assert SUPERVISOR_SERVICE.exists()
    unit = _load(SUPERVISOR_SERVICE)
    assert unit["Service"]["Type"] == "oneshot"
    assert "hapax-lane-supervisor" in unit["Service"]["ExecStart"]
    # A hung launcher must not wedge the oneshot forever.
    assert "TimeoutStartSec" in unit["Service"]


def test_supervisor_timer_ticks_every_60s() -> None:
    assert SUPERVISOR_TIMER.exists()
    unit = _load(SUPERVISOR_TIMER)
    assert unit["Timer"]["OnUnitActiveSec"] in {"60", "60s", "1min"}
    assert unit["Install"]["WantedBy"] == "timers.target"


def test_claude_lane_unit_restarts_always_with_startlimit() -> None:
    """FM-11 FORMALIZE: the lane template must auto-restart (not Restart=no),
    bounded by a StartLimit so a crashloop backs off instead of spinning.
    """
    assert CLAUDE_LANE.exists()
    unit = _load(CLAUDE_LANE)
    assert unit["Service"]["Restart"] == "always"
    assert unit["Service"]["Restart"] != "no"
    assert "RestartSec" in unit["Service"]
    # StartLimit* live in [Unit] per systemd.unit(5).
    assert "StartLimitIntervalSec" in unit["Unit"]
    assert "StartLimitBurst" in unit["Unit"]


def test_claude_lane_unit_still_binds_per_lane_task_env() -> None:
    """Restart=always must not drop the per-lane governed-task binding."""
    raw = CLAUDE_LANE.read_text(encoding="utf-8")
    assert "HAPAX_DISPATCH_TASK" in raw
    assert "EnvironmentFile" in raw
