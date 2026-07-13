"""Retirement contract for the legacy ``scripts/hapax-gemini`` launcher."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LAUNCHER = REPO_ROOT / "scripts" / "hapax-gemini"


def test_hapax_gemini_help_reports_retirement() -> None:
    result = subprocess.run([str(LAUNCHER), "--help"], capture_output=True, text=True, timeout=5)

    assert result.returncode == 0
    assert "retired" in result.stdout
    assert "hapax-gemini-sidecar" in result.stdout
    assert "agy.review.direct" in result.stdout
    assert "hapax-antigrav" not in result.stdout


def test_hapax_gemini_fails_closed_without_launching_legacy_cli() -> None:
    result = subprocess.run(
        [str(LAUNCHER), "--role", "iota"], capture_output=True, text=True, timeout=5
    )

    assert result.returncode == 64
    assert "retired" in result.stderr
    assert "Native Gemini API and LiteLLM usage is unaffected" in result.stderr
