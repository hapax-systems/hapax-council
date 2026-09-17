"""Tests for scripts/avsdlc-release-precheck.py — the keystroke-time
release-evidence precheck that pr-release-gate.sh invokes.

Reuses shared.release_gate.evaluate_avsdlc_release_gate; these tests pin
the precheck's exit-code contract (0 clean / 1 blocked / 3 infra).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

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


# ── adoptability teeth (ADOPTABILITY-DETERMINATION-20260916 §7) ──────────────

GARAGE_DOOR = """---
authority_case: CASE-X
parent_spec: spec-x
route_metadata_schema: 1
avsdlc_axes: none
release_authorized: true
tags: [cc-task, garage-door]
adoptability:
  prior_art_receipt: receipts/prior-art.yaml
  demand_receipt: receipts/demand.yaml
  install_line: "{install_line}"
  platforms: [linux]
  zero_config: true
  ttfv_seconds: 30
  replaces_nothing: true
  api: cli
  licence: Apache-2.0
  repo_open: acme/tool
  release_notes: https://github.com/acme/tool/releases
  compare_page: https://example.org/compare
  operator_voice_post: https://example.org/post
  receipt: receipts/adoptability.json
---
body
"""


def test_garage_door_row_without_adoptability_receipt_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HAPAX_ADOPTABILITY_RECEIPT_ROOTS", str(tmp_path))
    note = _note(tmp_path, GARAGE_DOOR.format(install_line="curl -fsSL https://x/i.sh | sh"))
    result = _run(note, "--merge")
    assert result.returncode == 1
    assert "release_refused:adoptability_receipt_absent" in result.stderr
    assert "release_refused:estate_binding_in_install_surface" not in result.stderr


def test_garage_door_row_with_estate_binding_in_install_surface_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HAPAX_ADOPTABILITY_RECEIPT_ROOTS", str(tmp_path))
    note = _note(
        tmp_path, GARAGE_DOOR.format(install_line="git clone hapax-systems/hapax-council && make")
    )
    result = _run(note, "--merge")
    assert result.returncode == 1
    assert "release_refused:estate_binding_in_install_surface" in result.stderr


def test_non_garage_door_row_carries_no_adoptability_blockers(tmp_path: Path) -> None:
    text = CLEAN.replace("release_authorized: false", "release_authorized: true")
    text = text.replace(
        "avsdlc_axes: none\n", "avsdlc_axes: none\ntags: [cc-task, adoptability, teeth]\n"
    )
    result = _run(_note(tmp_path, text), "--merge")
    assert result.returncode == 0, result.stderr
