"""Retirement contract for legacy Gemini tmux send helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SENDER = REPO_ROOT / "scripts" / "hapax-gemini-send"
SMOKE = REPO_ROOT / "scripts" / "hapax-gemini-smoke-send"


def test_gemini_sender_fails_closed() -> None:
    result = subprocess.run(
        [str(SENDER), "iota", "hello"], capture_output=True, text=True, timeout=5
    )

    assert result.returncode == 64
    assert "retired" in result.stderr
    assert "measured agy" in result.stderr
    assert "hapax-antigrav" not in result.stderr


def test_gemini_smoke_sender_fails_closed() -> None:
    result = subprocess.run([str(SMOKE), "iota"], capture_output=True, text=True, timeout=5)

    assert result.returncode == 64
    assert "retired" in result.stderr
    assert "measured agy supply-leaf" in result.stderr
    assert "governance receipts" in result.stderr
