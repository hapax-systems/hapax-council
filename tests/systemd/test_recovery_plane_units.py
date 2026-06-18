from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS = REPO_ROOT / "systemd" / "units"
STABLE_BUNDLE = "%h/.local/lib/hapax-recovery/council/current"
VOLATILE_MARKERS = (
    ".cache/hapax/source-activation/worktree",
    "/data/cache/hapax/scratch",
    "scratch/vocab-export",
)


def _read_unit(name: str) -> str:
    return (UNITS / name).read_text(encoding="utf-8")


def test_notify_failure_runs_from_stable_recovery_bundle() -> None:
    text = _read_unit("notify-failure@.service")

    assert (f"ExecStart={STABLE_BUNDLE}/scripts/hapax-p0-incident-intake service-failed %i") in text
    for marker in VOLATILE_MARKERS:
        assert marker not in text


def test_coord_rebuild_runs_from_stable_recovery_bundle() -> None:
    text = _read_unit("hapax-coord-rebuild.service")

    assert "# Hapax-Auto-Enable: true" in text
    assert "Wants=network-online.target" in text
    assert "After=network-online.target" in text
    assert "OnFailure=notify-failure@%n.service" in text
    assert f"ExecStart={STABLE_BUNDLE}/scripts/hapax-coord-deploy" in text
    for marker in VOLATILE_MARKERS:
        assert marker not in text


def test_recovery_plane_notify_failure_template_names_have_no_spaces() -> None:
    assert not (UNITS / "notify-failure @.service").exists()

    for unit in ("hapax-coord-rebuild.service", "notify-failure@.service"):
        text = _read_unit(unit)
        assert "notify-failure @" not in text
        assert "OnFailure=notify-failure@%n.service" in text or unit == "notify-failure@.service"


def test_coord_rebuild_timer_auto_enables() -> None:
    text = _read_unit("hapax-coord-rebuild.timer")

    assert "# Hapax-Auto-Enable: true" in text
    assert "OnBootSec=2min" in text
    assert "OnUnitActiveSec=5min" in text
    assert "Persistent=false" in text
    assert "WantedBy=timers.target" in text
