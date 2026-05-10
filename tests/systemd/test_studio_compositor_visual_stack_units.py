from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS_DIR = REPO_ROOT / "systemd" / "units"
STUDIO = UNITS_DIR / "studio-compositor.service"
BRIDGE = UNITS_DIR / "hapax-v4l2-bridge.service"
SOURCE_ROOT = "%h/.cache/hapax/source-activation/worktree"


def _load_unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment]
    parser.read(path, encoding="utf-8")
    return parser


def _active_unit_lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_studio_compositor_runs_from_activation_worktree() -> None:
    parser = _load_unit(STUDIO)
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Service", "ExecStart").startswith(f"{SOURCE_ROOT}/.venv/bin/python")
    assert parser.get("Service", "Environment", fallback="") is not None
    lines = _active_unit_lines(STUDIO)
    execution_lines = [
        line
        for line in lines
        if line.startswith(("ExecStart=", "ExecStartPre=", "ExecStopPost=", "WorkingDirectory="))
    ]
    assert execution_lines
    assert all("%h/projects/hapax-council" not in line for line in execution_lines)
    assert any("hapax-compositor-runtime-source-check" in line for line in execution_lines)
    assert any("v4l2-bridge.sock*" in line and "-delete" in line for line in execution_lines)
    assert any("HAPAX_COMPOSITOR_LAYOUT_PATH=" in line for line in lines)


def test_studio_compositor_starts_bridge_sidecar() -> None:
    parser = _load_unit(STUDIO)
    wants = parser.get("Unit", "Wants")
    assert "hapax-v4l2-bridge.service" in wants


def test_v4l2_bridge_runs_from_activation_worktree_and_is_supervised_by_studio() -> None:
    parser = _load_unit(BRIDGE)
    assert parser.get("Unit", "Requires") == "studio-compositor.service"
    assert parser.get("Unit", "BindsTo") == "studio-compositor.service"
    assert parser.get("Unit", "PartOf") == "studio-compositor.service"
    assert parser.get("Unit", "ConditionPathExists") == f"{SOURCE_ROOT}/scripts/hapax-v4l2-bridge"
    assert parser.get("Service", "WorkingDirectory") == SOURCE_ROOT
    assert parser.get("Service", "ExecStart").startswith(f"{SOURCE_ROOT}/scripts/hapax-v4l2-bridge")
    assert "hapax-compositor-runtime-source-check" in parser.get("Service", "ExecStartPre")
    assert parser.get("Service", "Restart") == "on-failure"
    lines = _active_unit_lines(BRIDGE)
    assert any("HAPAX_V4L2_BRIDGE_WAIT_SECONDS=60" in line for line in lines)
    assert any("HAPAX_V4L2_BRIDGE_ENABLED=1" in line for line in lines)


def test_simple_bridge_unit_does_not_claim_systemd_watchdog_without_sd_notify() -> None:
    parser = _load_unit(BRIDGE)
    assert parser.get("Service", "Type") == "simple"
    assert parser.get("Service", "WatchdogSec", fallback=None) is None


def test_runtime_source_check_script_exists_and_is_executable() -> None:
    script = REPO_ROOT / "scripts" / "hapax-compositor-runtime-source-check"
    assert script.exists()
    assert script.stat().st_mode & 0o100
