"""Static pins for the visual-pool snapshot harvester timer."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_ROOT = REPO_ROOT / "systemd"
UNITS_DIR = SYSTEMD_ROOT / "units"
PRESET = SYSTEMD_ROOT / "user-preset.d" / "hapax.preset"
SERVICE = UNITS_DIR / "hapax-visual-pool-snapshot-harvester.service"
TIMER = UNITS_DIR / "hapax-visual-pool-snapshot-harvester.timer"


def _lines(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_visual_pool_snapshot_harvester_units_are_install_visible() -> None:
    assert SERVICE.exists()
    assert TIMER.exists()
    assert not (SYSTEMD_ROOT / SERVICE.name).exists()
    assert not (SYSTEMD_ROOT / TIMER.name).exists()


def test_visual_pool_snapshot_harvester_service_runs_repo_script() -> None:
    service_lines = _lines(SERVICE)

    assert "Type=oneshot" in service_lines
    assert "ConditionPathIsDirectory=/dev/shm/hapax-compositor" in service_lines
    assert "WorkingDirectory=%h/projects/hapax-council" in service_lines
    assert (
        "ExecStart=%h/.local/bin/uv --directory %h/projects/hapax-council "
        "run python scripts/visual-pool-snapshot-harvester.py"
    ) in service_lines


def test_visual_pool_snapshot_harvester_timer_is_periodic_and_preset_enabled() -> None:
    timer_lines = _lines(TIMER)
    preset_lines = _lines(PRESET)

    assert "Unit=hapax-visual-pool-snapshot-harvester.service" in timer_lines
    assert "OnUnitActiveSec=1min" in timer_lines
    assert "enable hapax-visual-pool-snapshot-harvester.timer" in preset_lines
