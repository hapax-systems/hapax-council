"""Static checks for the request-intake consumer systemd activation contract."""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"

SERVICE_UNIT = UNITS_DIR / "hapax-request-intake-consumer.service"
TIMER_UNIT = UNITS_DIR / "hapax-request-intake-consumer.timer"
PATH_UNIT = UNITS_DIR / "hapax-request-intake-consumer.path"
CONSUMER_SERVICE = "hapax-request-intake-consumer.service"
ACTIVE_REQUESTS_DIR = "%h/Documents/Personal/20-projects/hapax-requests/active"


def _load_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(path, encoding="utf-8")
    return parser


def _preset_lines() -> set[str]:
    return {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_request_intake_units_live_in_canonical_systemd_units_dir() -> None:
    assert SERVICE_UNIT.is_file()
    assert TIMER_UNIT.is_file()
    assert PATH_UNIT.is_file()
    assert not (SYSTEMD_ROOT / SERVICE_UNIT.name).exists()
    assert not (SYSTEMD_ROOT / TIMER_UNIT.name).exists()
    assert not (SYSTEMD_ROOT / PATH_UNIT.name).exists()


def test_service_unit_has_consumer_contract_and_unit_condition() -> None:
    parser = _load_unit(SERVICE_UNIT)
    service_text = SERVICE_UNIT.read_text(encoding="utf-8")

    assert parser.get("Service", "Type") == "oneshot"
    assert (
        parser.get("Unit", "ConditionPathExists")
        == "%h/.cache/hapax/source-activation/worktree/scripts/request-intake-consumer"
    )
    assert parser.get("Service", "ConditionPathExists", fallback=None) is None
    assert [
        line.removeprefix("Environment=")
        for line in service_text.splitlines()
        if line.startswith("Environment=")
    ] == [
        "HAPAX_REQUEST_RECEIPTS=%h/.cache/hapax/request-receipts",
        "HAPAX_REQUEST_INTAKE_STATE=%h/.cache/hapax/request-intake-state.json",
        "HAPAX_AGENT_NAME=request-intake-consumer",
    ]

    exec_start = parser.get("Service", "ExecStart")
    assert exec_start.startswith(
        "%h/.cache/hapax/source-activation/worktree/scripts/request-intake-consumer "
    )
    for flag in ("--write-receipt", "--write-state", "--write-planning-feed"):
        assert flag in exec_start


def test_timer_preserves_periodic_consumer_sweep() -> None:
    parser = _load_unit(TIMER_UNIT)

    assert parser.get("Timer", "OnBootSec") == "2min"
    assert parser.get("Timer", "OnUnitActiveSec") == "2min"
    assert parser.get("Timer", "Persistent") == "true"
    assert parser.get("Timer", "Unit", fallback=CONSUMER_SERVICE) == CONSUMER_SERVICE
    assert parser.get("Install", "WantedBy") == "timers.target"


def test_path_unit_watches_active_request_folder_and_triggers_consumer() -> None:
    parser = _load_unit(PATH_UNIT)

    assert parser.get("Path", "PathChanged") == ACTIVE_REQUESTS_DIR
    assert parser.get("Path", "PathModified") == ACTIVE_REQUESTS_DIR
    assert parser.get("Path", "Unit") == CONSUMER_SERVICE
    assert parser.get("Path", "MakeDirectory", fallback="false") == "false"
    assert parser.get("Install", "WantedBy") == "default.target"


def test_request_intake_timer_and_path_are_preset_enabled() -> None:
    lines = _preset_lines()
    assert "enable hapax-request-intake-consumer.timer" in lines
    assert "enable hapax-request-intake-consumer.path" in lines
