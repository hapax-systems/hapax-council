from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SERVICE = REPO / "systemd" / "units" / "hapax-sdlc-vocab-export.service"
TIMER = REPO / "systemd" / "units" / "hapax-sdlc-vocab-export.timer"


def test_sdlc_vocab_export_unit_uses_source_activation_worktree() -> None:
    text = SERVICE.read_text(encoding="utf-8")

    assert "# Hapax-Auto-Enable: true" not in text
    assert (
        "ConditionPathExists=%h/.cache/hapax/source-activation/worktree/scripts/hapax-sdlc-vocab-export"
        in text
    )
    assert "ConditionPathExists=%h/.local/bin/uv" in text
    assert "OnFailure=notify-failure@%n.service" in text
    assert "WorkingDirectory=%h/.cache/hapax/source-activation/worktree" in text
    assert "TimeoutStartSec=300" in text
    assert (
        "ExecStart=%h/.local/bin/uv --directory "
        "%h/.cache/hapax/source-activation/worktree run --frozen python "
        "scripts/hapax-sdlc-vocab-export"
    ) in text


def test_sdlc_vocab_export_unit_avoids_retired_scratch_bridge() -> None:
    combined = SERVICE.read_text(encoding="utf-8") + TIMER.read_text(encoding="utf-8")

    assert "scratch/vocab-export" not in combined
    assert "/data/cache" not in combined


def test_sdlc_vocab_export_timer_is_auto_enabled() -> None:
    text = TIMER.read_text(encoding="utf-8")

    assert "# Hapax-Auto-Enable: true" in text
    assert "OnUnitActiveSec=10min" in text
    assert "WantedBy=timers.target" in text
