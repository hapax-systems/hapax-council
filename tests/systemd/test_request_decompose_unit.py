"""Static checks for the request-decompose systemd activation contract."""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SERVICE_UNIT = UNITS_DIR / "hapax-request-decompose.service"
TIMER_UNIT = UNITS_DIR / "hapax-request-decompose.timer"
READY_SERVICE_UNIT = UNITS_DIR / "hapax-cc-task-offer-ready.service"
READY_TIMER_UNIT = UNITS_DIR / "hapax-cc-task-offer-ready.timer"
PRESET_UNIT = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"
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
    assert "Environment=HAPAX_REQUEST_DECOMPOSE_LIMIT=3" in service_text

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


def test_request_pipeline_timers_are_preset_enabled() -> None:
    preset_lines = {
        line.strip()
        for line in PRESET_UNIT.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "enable hapax-request-intake-consumer.timer" in preset_lines
    assert "enable hapax-request-decompose.timer" in preset_lines
    assert "enable hapax-cc-task-offer-ready.timer" in preset_lines


def test_ready_offer_unit_uses_source_activation_worktree() -> None:
    parser = _load_unit(READY_SERVICE_UNIT)
    service_text = READY_SERVICE_UNIT.read_text(encoding="utf-8")

    assert parser.get("Service", "Type") == "oneshot"
    assert parser.get("Service", "WorkingDirectory") == ACTIVE_WORKTREE
    assert parser.get("Service", "ExecStart") == (
        f"{ACTIVE_WORKTREE}/scripts/cc-task-offer-ready --reconcile"
    )
    assert "%h/projects/hapax-council" not in service_text


def test_ready_offer_timer_targets_ready_offer_service() -> None:
    parser = _load_unit(READY_TIMER_UNIT)

    assert parser.get("Timer", "OnUnitActiveSec") == "300"
    assert parser.get("Timer", "Unit", fallback=READY_SERVICE_UNIT.name) == READY_SERVICE_UNIT.name
    assert parser.get("Install", "WantedBy") == "timers.target"
