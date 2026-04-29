"""Tests for safe Codex operator dossier bootstrap rendering."""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
HELPER = REPO_ROOT / "scripts" / "codex-operator-dossier-context.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "codex"


def _run_helper(source: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python", str(HELPER), "--source", str(source)],
        capture_output=True,
        text=True,
        timeout=5,
    )


def test_safe_dossier_summary_renders() -> None:
    result = _run_helper(FIXTURE_ROOT / "operator-dossier-safe.md")

    assert result.returncode == 0, result.stderr
    assert "status: safe_summary" in result.stdout
    assert "SAFE-CODEX-DOSSIER-FIXTURE" in result.stdout
    assert "Update only from durable operator directives" in result.stdout
    assert "Invalidate after contradiction" in result.stdout


def test_unsafe_dossier_summary_fails_closed_without_copying_content() -> None:
    result = _run_helper(FIXTURE_ROOT / "operator-dossier-unsafe.md")

    assert result.returncode == 0, result.stderr
    assert "status: unavailable" in result.stdout
    assert "source failed leak guard" in result.stdout
    assert "do-not-leak-token-value" not in result.stdout
    assert "do-not-leak-private-transcript-content" not in result.stdout
    assert "Operator:" not in result.stdout
