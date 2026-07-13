"""Retirement tests for the old Antigrav enable-latch launch path."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LAUNCHER = REPO / "scripts" / "hapax-antigrav"


def test_launcher_no_longer_wires_agy_latch_or_hook_override() -> None:
    src = LAUNCHER.read_text(encoding="utf-8")

    assert "hapax_check_enable_latch antigrav" not in src
    assert "HAPAX_ANTIGRAV_OVERRIDE_HOOK_WIRING" not in src
    assert "--prompt-interactive" not in src
    assert "cc-claim" not in src
    assert "reason_code=antigrav_worker_stub_refusal" in src
