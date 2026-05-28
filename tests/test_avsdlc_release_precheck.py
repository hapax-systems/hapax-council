"""Tests for scripts/avsdlc-release-precheck.py — the keystroke-time
release-evidence precheck that pr-release-gate.sh invokes.

Reuses shared.release_gate.evaluate_avsdlc_release_gate; these tests pin
the precheck's exit-code contract (0 clean / 1 blocked / 3 infra).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "avsdlc-release-precheck.py"

CLEAN = """---
authority_case: CASE-X
parent_spec: spec-x
route_metadata_schema: 1
avsdlc_axes: none
release_authorized: false
---
body
"""


def _run(note: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(note), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )


def _note(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "task.md"
    p.write_text(text)
    return p


def test_clean_task_create_passes(tmp_path: Path) -> None:
    result = _run(_note(tmp_path, CLEAN))
    assert result.returncode == 0, result.stderr


def test_merge_blocked_without_release_authorized(tmp_path: Path) -> None:
    result = _run(_note(tmp_path, CLEAN), "--merge")
    assert result.returncode == 1
    assert "release_not_authorized" in result.stderr


def test_merge_passes_when_release_authorized(tmp_path: Path) -> None:
    text = CLEAN.replace("release_authorized: false", "release_authorized: true")
    result = _run(_note(tmp_path, text), "--merge")
    assert result.returncode == 0, result.stderr


def test_missing_parent_spec_blocks(tmp_path: Path) -> None:
    text = CLEAN.replace("parent_spec: spec-x\n", "")
    result = _run(_note(tmp_path, text))
    assert result.returncode == 1
    assert "task_missing_parent_spec" in result.stderr


def test_missing_route_schema_blocks(tmp_path: Path) -> None:
    text = CLEAN.replace("route_metadata_schema: 1\n", "")
    result = _run(_note(tmp_path, text))
    assert result.returncode == 1
    assert "route_metadata_schema" in result.stderr


def test_explicit_axis_without_evidence_blocks(tmp_path: Path) -> None:
    text = (
        "---\n"
        "authority_case: CASE-X\n"
        "parent_spec: spec-x\n"
        "route_metadata_schema: 1\n"
        "avsdlc_axes:\n"
        "  - visual\n"
        "---\nbody\n"
    )
    result = _run(_note(tmp_path, text))
    assert result.returncode == 1
    assert "avsdlc_release_gate" in result.stderr


def test_note_not_found_is_infra(tmp_path: Path) -> None:
    result = _run(tmp_path / "does-not-exist.md")
    assert result.returncode == 3
