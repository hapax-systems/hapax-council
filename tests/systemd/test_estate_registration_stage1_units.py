"""Stage 1 estate-registration units: what merge is and is not allowed to do."""

from pathlib import Path


def test_stage1_timers_are_parked_so_merge_does_not_activate_them() -> None:
    """Four review families, 2026-09-04: the post-merge deploy runs `enable --now` on every
    unmarked new timer, so an unparked Stage 1 timer activates on merge — the stage gate the
    whole PR exists to respect. Activation is a deliberate step after merge, never a side effect
    of it."""
    units = Path(__file__).resolve().parents[2] / "systemd" / "units"
    for name in (
        "hapax-estate-canary.timer",
        "hapax-estate-canary-peer-check.timer",
        "hapax-estate-drift-sweep.timer",
    ):
        text = (units / name).read_text(encoding="utf-8")
        assert "# Hapax-Parked: true" in text, f"{name} would activate on merge"
