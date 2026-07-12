"""Lane supervisor systemd containment and adjacent lane-unit pins."""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SUPERVISOR_SERVICE = UNITS_DIR / "hapax-lane-supervisor.service"
SUPERVISOR_TIMER = UNITS_DIR / "hapax-lane-supervisor.timer"
REAPER_SERVICE = UNITS_DIR / "hapax-lane-reaper.service"
AUDIT_SERVICE = UNITS_DIR / "codex-claim-audit.service"
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
    assert "projection" in unit["Unit"]["Description"].lower()
    assert "TimeoutStartSec" in unit["Service"]


def test_supervisor_service_execstart_is_branch_stable() -> None:
    """The supervisor resolves and verifies one exact activated release."""
    unit = _load(SUPERVISOR_SERVICE)
    activated_root = "%h/.cache/hapax/source-activation/worktree"
    assert unit["Service"]["WorkingDirectory"] == "%h"
    command = unit["Service"]["ExecStart"]
    assert command.startswith("/usr/bin/bash -c ")
    assert "last-success-sha" in command
    assert "rev-parse HEAD" in command
    assert "status --porcelain --untracked-files=no" in command
    assert 'exec "$target/scripts/hapax-lane-supervisor"' in command
    raw = SUPERVISOR_SERVICE.read_text(encoding="utf-8")
    assert "projects/hapax-council" not in raw
    assert f"ConditionFileIsExecutable={activated_root}/scripts/hapax-lane-supervisor" in raw


def test_supervisor_service_enforces_read_only_projection() -> None:
    unit = _load(SUPERVISOR_SERVICE)
    service = unit["Service"]
    assert service["ProtectHome"] == "read-only"
    assert service["ProtectSystem"] == "strict"
    assert service["NoNewPrivileges"] == "true"
    assert service["PrivateNetwork"] == "true"
    assert service["RestrictAddressFamilies"] == "AF_UNIX"
    assert service["PrivateTmp"] == "true"
    assert service["CapabilityBoundingSet"] == ""
    assert service["AmbientCapabilities"] == ""
    assert service["ReadOnlyPaths"] == "%t /tmp /var/tmp"
    assert "SystemCallFilter=~@network-io kill " in SUPERVISOR_SERVICE.read_text(encoding="utf-8")
    assert "HAPAX_SUPERVISOR_METRICS_FILE=" in service.get("Environment", "")
    assert "OnFailure" not in unit["Unit"]


def test_supervisor_timer_ticks_every_60s() -> None:
    assert SUPERVISOR_TIMER.exists()
    unit = _load(SUPERVISOR_TIMER)
    assert unit["Timer"]["OnUnitActiveSec"] in {"60", "60s", "1min"}
    assert unit["Install"]["WantedBy"] == "timers.target"


def test_supervisor_timer_is_marked_auto_enable() -> None:
    """The recurring surface may auto-enable only because it is read-only."""
    markers = [
        line.strip()
        for line in SUPERVISOR_TIMER.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("#") and "hapax-auto-enable" in line.lower()
    ]
    assert markers, "lane-supervisor.timer must carry a `# Hapax-Auto-Enable` marker"
    assert any("true" in marker.lower() for marker in markers)
    assert "Install" in _load(SUPERVISOR_TIMER)
    assert "Project Hapax lane health" in SUPERVISOR_TIMER.read_text(encoding="utf-8")


def test_reaper_service_executes_canonical_source_activation() -> None:
    unit = _load(REAPER_SERVICE)
    service = unit["Service"]
    activated_root = "%h/.cache/hapax/source-activation/worktree"

    assert service["WorkingDirectory"] == "%h"
    assert "last-success-sha" in service["ExecStart"]
    assert 'exec "$target/scripts/hapax-lane-reaper" --threshold 30' in service["ExecStart"]
    raw = REAPER_SERVICE.read_text(encoding="utf-8")
    assert "projects/hapax-council" not in raw
    assert f"ConditionFileIsExecutable={activated_root}/scripts/hapax-lane-reaper" in raw


def test_reaper_service_is_independently_projection_only() -> None:
    unit = _load(REAPER_SERVICE)
    service = unit["Service"]
    raw = REAPER_SERVICE.read_text(encoding="utf-8")

    assert service["ProtectHome"] == "read-only"
    assert service["ProtectSystem"] == "strict"
    assert service["NoNewPrivileges"] == "true"
    assert service["PrivateNetwork"] == "true"
    assert service["RestrictAddressFamilies"] == "AF_UNIX"
    assert service["PrivateTmp"] == "true"
    assert service["CapabilityBoundingSet"] == ""
    assert service["AmbientCapabilities"] == ""
    assert service["ReadOnlyPaths"] == "%t /tmp /var/tmp"
    assert "SystemCallFilter=~@network-io kill " in raw
    assert "OnFailure=" not in raw


def test_all_projection_units_bind_release_and_cannot_reach_control_sockets() -> None:
    for path in (SUPERVISOR_SERVICE, REAPER_SERVICE, AUDIT_SERVICE):
        service = _load(path)["Service"]
        command = service["ExecStart"]
        assert "last-success-sha" in command
        assert "rev-parse HEAD" in command
        assert "status --porcelain --untracked-files=no" in command
        assert service["PrivateTmp"] == "true"
        assert "SystemCallFilter=~@network-io" in path.read_text(encoding="utf-8")


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
