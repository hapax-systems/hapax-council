"""Static checks for the dataset card generator systemd timer."""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
SERVICE = UNITS_DIR / "hapax-dataset-card-generator.service"
TIMER = UNITS_DIR / "hapax-dataset-card-generator.timer"


def _read_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(path, encoding="utf-8")
    return parser


def test_dataset_card_generator_service_invokes_package_cli() -> None:
    parser = _read_unit(SERVICE)

    assert parser.get("Service", "Type") == "oneshot"
    assert parser.get("Service", "WorkingDirectory") == "%h/projects/hapax-council"
    exec_start = parser.get("Service", "ExecStart")
    assert "python -m agents.dataset_card_generator" in exec_start
    assert "--output %h/hapax-state/research/dataset-cards.md" in exec_start


def test_dataset_card_generator_timer_is_daily_and_enableable() -> None:
    parser = _read_unit(TIMER)

    assert parser.get("Timer", "Unit") == "hapax-dataset-card-generator.service"
    assert parser.get("Timer", "OnCalendar") == "*-*-* 05:20:00 UTC"
    assert parser.get("Timer", "Persistent").lower() == "true"
    assert parser.get("Install", "WantedBy") == "timers.target"
