"""Lane idle watchdog systemd units.

The idle watchdog is the governed reminder path for idle claimed lanes and the
guardrail that keeps unclaimed lanes waiting for methodology dispatch. Its timer
must come up on deploy; otherwise the script can exist in source while lane
drift recurs silently.
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
WATCHDOG_SERVICE = UNITS_DIR / "hapax-lane-idle-watchdog.service"
WATCHDOG_TIMER = UNITS_DIR / "hapax-lane-idle-watchdog.timer"


def _load(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser


def test_idle_watchdog_service_runs_source_activation_script() -> None:
    assert WATCHDOG_SERVICE.exists()
    unit = _load(WATCHDOG_SERVICE)
    assert unit["Service"]["Type"] == "oneshot"
    assert (
        "%h/.cache/hapax/source-activation/worktree/scripts/hapax-lane-idle-watchdog"
        in unit["Service"]["ExecStart"]
    )
    assert "HAPAX_LOCAL_DEV_MAINTENANCE_MODE=appendix-only" in unit["Service"].get(
        "Environment", ""
    )
    assert "TimeoutStartSec" in unit["Service"]


def test_idle_watchdog_timer_ticks_every_two_minutes() -> None:
    assert WATCHDOG_TIMER.exists()
    unit = _load(WATCHDOG_TIMER)
    assert unit["Timer"]["OnBootSec"] in {"180", "180s", "3min"}
    assert unit["Timer"]["OnUnitActiveSec"] in {"120", "120s", "2min"}
    assert unit["Install"]["WantedBy"] == "timers.target"


def test_idle_watchdog_timer_is_marked_auto_enable() -> None:
    """Deploy must enable+start this timer, not merely install the file."""
    markers = [
        line.strip()
        for line in WATCHDOG_TIMER.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("#") and "hapax-auto-enable" in line.lower()
    ]
    assert markers, "lane-idle-watchdog.timer must carry a Hapax-Auto-Enable marker"
    assert any("true" in marker.lower() for marker in markers)
    assert "Install" in _load(WATCHDOG_TIMER)
