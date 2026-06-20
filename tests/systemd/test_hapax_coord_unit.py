from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-coord.service"
COORD_ACTIVATION = "%h/.cache/hapax/coord-activation/worktree"
FORBIDDEN_D2_ROOTS = (
    "/home/hapax/projects/hapax-coord",
    "source-activation/worktree",
    "scratch/vocab-export",
    "/data/cache",
)


def _read_unit() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(UNIT, encoding="utf-8")
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
