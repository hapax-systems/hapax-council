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


def test_supervisor_service_execstart_is_branch_stable() -> None:
    """A must-always-run supervisor cannot depend on the canonical integrator
    worktree's transient branch — that worktree floats across feature branches
    and frequently lacks the supervisor script (it shipped in #3803), so a
    `%h/projects/hapax-council/scripts/...` ExecStart would fail to start.
    Point it at the deploy-maintained `~/.local/bin` symlink, which is exactly
    what the supervisor script itself assumes for its sibling launchers.
    """
    exec_start = _load(SUPERVISOR_SERVICE)["Service"]["ExecStart"]
    assert exec_start.endswith("/.local/bin/hapax-lane-supervisor"), exec_start
    assert "projects/hapax-council" not in exec_start, exec_start


def test_supervisor_service_defaults_to_appendix_only_local_dev_maintenance() -> None:
    unit = _load(SUPERVISOR_SERVICE)
    environment = unit["Service"].get("Environment", "")
    assert "HAPAX_LOCAL_DEV_MAINTENANCE_MODE=appendix-only" in environment


def test_supervisor_timer_ticks_every_60s() -> None:
    assert SUPERVISOR_TIMER.exists()
    unit = _load(SUPERVISOR_TIMER)
    assert unit["Timer"]["OnUnitActiveSec"] in {"60", "60s", "1min"}
    assert unit["Install"]["WantedBy"] == "timers.target"


def test_supervisor_timer_is_marked_auto_enable() -> None:
    """reform-improve-deploy-activation: the deploy auto-enables units that
    carry a `# Hapax-Auto-Enable: true` marker, so a newly-merged supervisor
    timer is `enable --now`'d instead of installed-but-sleeping (the FM-11
    live gap). The marker is meaningless without an [Install] section.
    """
    markers = [
        line.strip()
        for line in SUPERVISOR_TIMER.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("#") and "hapax-auto-enable" in line.lower()
    ]
    assert markers, "lane-supervisor.timer must carry a `# Hapax-Auto-Enable` marker"
    assert any("true" in marker.lower() for marker in markers)
    assert "Install" in _load(SUPERVISOR_TIMER)


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
    assert '/usr/bin/python3 -I "$HOME/.local/bin/hapax-methodology-dispatch"' in raw
