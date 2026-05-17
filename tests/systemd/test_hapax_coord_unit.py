from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "systemd" / "units" / "hapax-coord.service"


def _read_unit() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(UNIT, encoding="utf-8")
    return parser


def test_hapax_coord_unit_is_source_only_shape() -> None:
    parser = _read_unit()

    assert parser.get("Service", "Type") == "simple"
    assert parser.get("Service", "WorkingDirectory") == "%h/projects/hapax-coord"
    assert (
        parser.get("Service", "ExecStart")
        == "%h/projects/hapax-coord/scripts/run-dev.sh --daemon --host 127.0.0.1 --port 8765"
    )
    assert parser.get("Unit", "ConditionPathExists") == "%h/projects/hapax-coord/scripts/run-dev.sh"
    assert parser.get("Unit", "Documentation") == "file://%h/projects/hapax-coord/README.md"
    assert (
        parser.get("Service", "Environment")
        == "HAPAX_COORD_COUNCIL_ROOT=%h/.cache/hapax/source-activation/worktree"
    )


def test_hapax_coord_unit_does_not_install_or_expose_secrets() -> None:
    text = UNIT.read_text(encoding="utf-8")

    assert "systemctl" not in text
    assert "0.0.0.0" not in text
    assert "PASSWORD_STORE_DIR" not in text
    assert "GNUPGHOME" not in text
    assert "TOKEN" not in text
    assert "SECRET" not in text
