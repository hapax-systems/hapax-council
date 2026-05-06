"""Static checks for the segment-prep ledger publication path/service units."""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
PATH_UNIT = UNITS_DIR / "hapax-segment-prep-ledger-publish.path"
SERVICE_UNIT = UNITS_DIR / "hapax-segment-prep-ledger-publish.service"


def _load_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(path, encoding="utf-8")
    return parser


def test_units_live_in_canonical_systemd_units_path() -> None:
    assert PATH_UNIT.is_file()
    assert SERVICE_UNIT.is_file()
    assert PATH_UNIT.parent.name == "units"
    assert SERVICE_UNIT.parent.name == "units"


def test_path_unit_watches_prediction_ledger() -> None:
    parser = _load_unit(PATH_UNIT)

    assert parser.get("Path", "Unit") == "hapax-segment-prep-ledger-publish.service"
    watched = parser.get("Path", "PathChanged")
    assert watched.endswith(
        "Documents/Personal/20-projects/hapax-research/ledgers/"
        "segment-prep-framework-prediction-ledger.md"
    )


def test_service_unit_queues_publication_script_only() -> None:
    parser = _load_unit(SERVICE_UNIT)
    exec_start = parser.get("Service", "ExecStart")

    assert parser.get("Service", "Type") == "oneshot"
    assert "scripts/publish_segment_prep_prediction_ledger.py" in exec_start
    assert "daily_segment_prep" not in exec_start
    assert "unload" not in exec_start.lower()
    assert "qwen" not in exec_start.lower()
