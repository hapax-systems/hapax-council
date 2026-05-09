"""Static checks for audio-health systemd readiness durability."""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
REBUILD_WORKTREE = "%h/.cache/hapax/rebuild/worktree"
SOURCE_ACTIVATION_WORKTREE = "%h/.cache/hapax/source-activation/worktree"

AUDIO_HEALTH_UNITS = [
    "hapax-audio-health-lufs-s.service",
    "hapax-audio-health-crest-flatness.service",
    "hapax-audio-health-inter-stage-corr.service",
    "hapax-audio-health-topology-drift.service",
    "hapax-audio-health-channel-position.service",
    "hapax-audio-health-pipewire-xrun.service",
    "hapax-audio-health-l12-usb.service",
    "hapax-audio-health-meta.service",
]


def _load_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(path, encoding="utf-8")
    return parser


def test_audio_health_units_are_honest_simple_services() -> None:
    for unit_name in AUDIO_HEALTH_UNITS:
        unit_path = UNITS_DIR / unit_name
        parser = _load_unit(unit_path)
        text = unit_path.read_text(encoding="utf-8")

        assert parser.get("Service", "Type") == "simple", unit_name
        assert parser.get("Service", "NotifyAccess") == "all", unit_name
        assert parser.get("Service", "WatchdogSec") == "0", unit_name
        assert "Type=notify" not in text, unit_name


def test_audio_health_units_run_from_current_deployed_worktree() -> None:
    for unit_name in AUDIO_HEALTH_UNITS:
        unit_path = UNITS_DIR / unit_name
        parser = _load_unit(unit_path)
        service = parser["Service"]

        assert parser.get("Unit", "ConditionPathExists") == f"{REBUILD_WORKTREE}/pyproject.toml"
        assert service["WorkingDirectory"] == REBUILD_WORKTREE
        assert service["ExecStart"].startswith("%h/.local/bin/uv run python -m ")
        assert "%h/projects/hapax-council" not in "\n".join(
            [
                service["WorkingDirectory"],
                service["ExecStart"],
            ]
        )


def test_equipment_state_uses_source_activation_worktree() -> None:
    unit_path = UNITS_DIR / "hapax-equipment-state.service"
    parser = _load_unit(unit_path)
    text = unit_path.read_text(encoding="utf-8")
    writer = f"{SOURCE_ACTIVATION_WORKTREE}/scripts/equipment-state-writer"

    assert parser.get("Unit", "ConditionPathExists") == writer
    assert parser.get("Service", "Type") == "oneshot"
    assert parser.get("Service", "ExecStart") == writer

    environment_lines = [
        line.removeprefix("Environment=")
        for line in text.splitlines()
        if line.startswith("Environment=")
    ]
    assert environment_lines == [f"PYTHONPATH={SOURCE_ACTIVATION_WORKTREE}"]
    assert "%h/projects/hapax-council" not in text
