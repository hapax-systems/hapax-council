from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-coord.service"
REBUILD_SERVICE = REPO_ROOT / "systemd" / "units" / "hapax-coord-rebuild.service"
REBUILD_TIMER = REPO_ROOT / "systemd" / "units" / "hapax-coord-rebuild.timer"
COORD_ACTIVATION = "%h/.cache/hapax/coord-activation/worktree"
SOURCE_ACTIVATION = "%h/.cache/hapax/source-activation/worktree"
FORBIDDEN_D2_ROOTS = (
    "/home/hapax/projects/hapax-coord",
    "source-activation/worktree",
    "scratch/vocab-export",
    "/data/cache",
)


def _read_unit() -> configparser.ConfigParser:
    return _read_systemd_unit(UNIT)


def _read_systemd_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(path, encoding="utf-8")
    return parser


def test_hapax_coord_unit_uses_coord_activation_worktree() -> None:
    parser = _read_unit()

    assert parser.get("Service", "Type") == "simple"
    assert parser.get("Unit", "ConditionPathExists") == f"{COORD_ACTIVATION}/scripts/run-dev.sh"
    assert parser.get("Service", "WorkingDirectory") == COORD_ACTIVATION
    assert parser.get("Service", "ExecStart") == f"{COORD_ACTIVATION}/scripts/run-dev.sh --daemon"


def test_hapax_coord_unit_avoids_reapable_or_mutable_d2_roots() -> None:
    text = UNIT.read_text(encoding="utf-8")

    for root in FORBIDDEN_D2_ROOTS:
        assert root not in text


def test_hapax_coord_unit_does_not_install_or_expose_secrets() -> None:
    text = UNIT.read_text(encoding="utf-8")

    assert "systemctl" not in text
    assert "Environment=" not in text
    assert "0.0.0.0" not in text


def test_hapax_coord_rebuild_service_runs_source_owned_deploy_helper() -> None:
    parser = _read_systemd_unit(REBUILD_SERVICE)

    assert parser.get("Service", "Type") == "oneshot"
    assert parser.get("Unit", "ConditionPathExists") == (
        f"{SOURCE_ACTIVATION}/scripts/hapax-coord-deploy"
    )
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ACTIVATION
    assert parser.get("Service", "ExecStart") == (f"{SOURCE_ACTIVATION}/scripts/hapax-coord-deploy")
    assert parser.get("Service", "TimeoutStartSec") == "300"
    assert parser.get("Unit", "Wants") == "network-online.target"
    assert parser.get("Unit", "After") == "network-online.target"
    assert parser.get("Unit", "OnFailure") == "notify-failure@%n.service"


def test_hapax_coord_rebuild_timer_is_durable_deploy_cadence() -> None:
    parser = _read_systemd_unit(REBUILD_TIMER)
    text = REBUILD_TIMER.read_text(encoding="utf-8")

    assert "# Hapax-Auto-Enable: true" in text
    assert parser.get("Timer", "Unit") == "hapax-coord-rebuild.service"
    assert parser.get("Timer", "OnBootSec") == "3min"
    assert parser.get("Timer", "OnUnitActiveSec") == "5min"
    assert parser.get("Timer", "AccuracySec") == "30s"
    assert parser.get("Timer", "Persistent") == "false"
    assert parser.get("Install", "WantedBy") == "timers.target"
