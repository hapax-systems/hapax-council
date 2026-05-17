"""Tests for methodology-gated lane watchdog prompts."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WATCHDOG_SCRIPTS = (
    REPO_ROOT / "scripts" / "hapax-lane-idle-watchdog",
    REPO_ROOT / "scripts" / "hapax-lane-rate-limit-watchdog",
)
FORBIDDEN_GENERIC_PROMPTS = (
    "highest-WSJF",
    "highest WSJF",
    "Claim and start:",
    "Claim the highest",
    "claim the next",
    "claim next",
    "cc-claim <task_id>",
    "find the highest",
)


def test_lane_watchdogs_delegate_new_assignments_to_methodology_dispatch() -> None:
    for script in WATCHDOG_SCRIPTS:
        text = script.read_text(encoding="utf-8")
        assert "hapax-methodology-dispatch" in text
        assert "--print-prompt" in text
        assert "Do not claim work from the pool" in text


def test_lane_watchdogs_do_not_emit_generic_pool_claim_prompts() -> None:
    for script in WATCHDOG_SCRIPTS:
        text = script.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_GENERIC_PROMPTS:
            assert forbidden not in text


def test_lane_watchdog_shell_syntax() -> None:
    for script in WATCHDOG_SCRIPTS:
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
