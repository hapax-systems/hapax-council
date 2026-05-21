"""Static checks for the request-decompose systemd activation contract."""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SERVICE_UNIT = UNITS_DIR / "hapax-request-decompose.service"
TIMER_UNIT = UNITS_DIR / "hapax-request-decompose.timer"
ACTIVE_WORKTREE = "%h/.cache/hapax/source-activation/worktree"


def _load_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(path, encoding="utf-8")
    return parser


def test_request_decompose_unit_uses_source_activation_worktree() -> None:
    parser = _load_unit(SERVICE_UNIT)
    service_text = SERVICE_UNIT.read_text(encoding="utf-8")

    assert parser.get("Service", "Type") == "oneshot"
    assert parser.get("Service", "WorkingDirectory") == ACTIVE_WORKTREE
    assert parser.get("Service", "ExecStart") == (
        "%h/.local/bin/uv --directory "
        f"{ACTIVE_WORKTREE} run python scripts/request-decompose --scan"
    )
    assert f"ConditionPathExists={ACTIVE_WORKTREE}/scripts/request-decompose" in service_text
    assert "Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin" in service_text
    assert "Environment=HOME=%h" in service_text
    assert f"Environment=PYTHONPATH={ACTIVE_WORKTREE}" in service_text

    execution_lines = [
        line
        for line in service_text.splitlines()
        if line.startswith(
            (
                "ConditionPathExists=",
                "ExecStart=",
                "WorkingDirectory=",
                "Environment=PYTHONPATH=",
            )
        )
    ]
    assert execution_lines
    assert all("/home/hapax/projects/hapax-council" not in line for line in execution_lines)
    assert all("%h/projects/hapax-council" not in line for line in execution_lines)


def test_request_decompose_timer_targets_decompose_service() -> None:
    parser = _load_unit(TIMER_UNIT)

    assert parser.get("Timer", "OnBootSec") == "5min"
    assert parser.get("Timer", "OnUnitActiveSec") == "15min"
    assert parser.get("Timer", "Unit", fallback=SERVICE_UNIT.name) == SERVICE_UNIT.name
    assert parser.get("Install", "WantedBy") == "timers.target"
