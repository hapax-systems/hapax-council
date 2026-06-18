from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-coord.service"
ACTIVATION_WORKTREE = "%h/.cache/hapax/coord-activation/worktree"


def _read_unit() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(UNIT, encoding="utf-8")
    return parser


def test_hapax_coord_unit_runs_from_coord_activation_worktree() -> None:
    parser = _read_unit()
    text = UNIT.read_text(encoding="utf-8")
    conditions = [
        line.removeprefix("ConditionPathExists=")
        for line in text.splitlines()
        if line.startswith("ConditionPathExists=")
    ]

    assert parser.get("Service", "Type") == "simple"
    assert parser.get("Service", "Environment") == f"HAPAX_COORD_ROOT={ACTIVATION_WORKTREE}"
    assert parser.get("Service", "WorkingDirectory") == ACTIVATION_WORKTREE
    assert (
        parser.get("Service", "ExecStart") == f"{ACTIVATION_WORKTREE}/scripts/run-dev.sh --daemon"
    )
    assert conditions == [
        f"{ACTIVATION_WORKTREE}/scripts/run-dev.sh",
        f"{ACTIVATION_WORKTREE}/.deployed-sha",
    ]
    assert parser.get("Unit", "OnFailure") == "notify-failure@%n.service"


def test_hapax_coord_unit_does_not_install_or_expose_secrets() -> None:
    text = UNIT.read_text(encoding="utf-8")

    assert "systemctl" not in text
    assert text.count("Environment=") == 1
    assert "0.0.0.0" not in text
    assert "/home/hapax/projects/hapax-coord/scripts/run-dev.sh" not in text
