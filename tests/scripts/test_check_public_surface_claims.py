from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check-public-surface-claims.py"


def test_public_surface_claim_gate_fails_absolute_claim(tmp_path: Path) -> None:
    doc = tmp_path / "bad.md"
    doc.write_text("No test results, no push.\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(doc)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Hapax.PublicClaimOverreach" in result.stdout


def test_public_surface_claim_gate_passes_scoped_claim(tmp_path: Path) -> None:
    doc = tmp_path / "good.md"
    doc.write_text(
        "Missing test evidence blocks the governed push path.\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(doc)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_public_surface_claim_gate_warnings_fail_escalates(tmp_path: Path) -> None:
    doc = tmp_path / "warn.md"
    doc.write_text("This is an existence proof.\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--warnings-fail", str(doc)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Hapax.PublicClaimOverreach" in result.stdout


def test_public_surface_claim_gate_ignores_unsupported_file_suffix(tmp_path: Path) -> None:
    doc = tmp_path / "bad.txt"
    doc.write_text("No test results, no push.\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(doc)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
