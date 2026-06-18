from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNITS = REPO_ROOT / "systemd" / "units"
PRESET = REPO_ROOT / "systemd" / "user-preset.d" / "hapax.preset"
SOURCE_ACTIVATION = "%h/.cache/hapax/source-activation/worktree"


def test_segment_prep_emit_health_service_routes_failure_to_notify_intake() -> None:
    text = (UNITS / "hapax-segment-prep-emit-health.service").read_text(encoding="utf-8")

    assert "OnFailure=notify-failure@%n.service" in text
    assert f"WorkingDirectory={SOURCE_ACTIVATION}" in text
    assert f"Environment=PYTHONPATH={SOURCE_ACTIVATION}" in text
    assert (
        f"ExecStartPre={SOURCE_ACTIVATION}/scripts/hapax-compositor-runtime-source-check "
        "--require-file scripts/hapax-segment-prep-emit-health"
    ) in text
    assert f"ExecStart={SOURCE_ACTIVATION}/scripts/hapax-segment-prep-emit-health" in text


def test_segment_prep_emit_health_timer_runs_after_daily_prep_window() -> None:
    text = (UNITS / "hapax-segment-prep-emit-health.timer").read_text(encoding="utf-8")

    assert "# Hapax-Auto-Enable: true" in text
    assert "OnCalendar=*-*-* 06:20:00 UTC" in text
    assert "Persistent=true" in text
    assert "RandomizedDelaySec=300" in text
    assert "Unit=hapax-segment-prep-emit-health.service" in text
    assert "WantedBy=timers.target" in text


def test_segment_prep_emit_health_timer_is_preset_enabled() -> None:
    preset_lines = {
        line.strip()
        for line in PRESET.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert "enable hapax-segment-prep-emit-health.timer" in preset_lines
