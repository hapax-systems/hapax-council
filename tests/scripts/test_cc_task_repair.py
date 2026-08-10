"""cc-task-repair's blocked_witness backfill, and the boundary it must not cross.

Repair exists to backfill governance scaffolding so a session is not wedged by a malformed
note. `blocked_witness` joined that set on 2026-08-10 for a measured reason: 239 active
tasks were blocked with no witness, which is 70% of the blocked queue, and without a repair
path the field could only ever be written by hand — which is why almost none of them had one.

The hazard to pin is that backfilling a witness must not become a way to CHANGE a task's
standing. A null witness still fails is_active_blocked_with_evidence, so the task stays
blocked; only the absence becomes visible.

Self-contained per the repo testing convention (no shared conftest fixtures).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "cc-task-repair"

TASK = """---
type: cc-task
task_id: repair-fixture
title: "repair-fixture"
status: blocked
blocked_reason: waiting_for_something
assigned_to: cx-test
kind: build
authority_case: CASE-TEST
parent_spec: docs/spec.md
quality_floor: deterministic_ok
authority_level: support_non_authoritative
mutation_surface: vault_docs
---

# repair-fixture
"""


def _run(task_id: str, vault: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(vault.parent)}
    return subprocess.run(
        ["python3", str(SCRIPT), task_id, *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _vault(tmp_path: Path, body: str = TASK) -> tuple[Path, Path]:
    active = tmp_path / "home" / "Documents/Personal/20-projects/hapax-cc-tasks/active"
    active.mkdir(parents=True)
    note = active / "repair-fixture.md"
    note.write_text(body, encoding="utf-8")
    return active.parents[3], note


def test_blocked_witness_is_backfillable(tmp_path: Path) -> None:
    """Without this, a condition-blocked task can never acquire the field that frees it."""
    vault, note = _vault(tmp_path)
    result = _run("repair-fixture", vault, "--set", "blocked_witness=test -f /etc/hostname")
    assert result.returncode in (0, 1), result.stderr
    assert "blocked_witness: test -f /etc/hostname" in note.read_text(encoding="utf-8")


def test_backfilling_a_witness_does_not_change_task_standing(tmp_path: Path) -> None:
    """The boundary: repair may create the slot, never move the task out of `blocked`."""
    vault, note = _vault(tmp_path)
    _run("repair-fixture", vault, "--set", "blocked_witness=test -f /etc/hostname")
    text = note.read_text(encoding="utf-8")
    assert "status: blocked" in text
    assert "status: offered" not in text
    assert "blocked_reason: waiting_for_something" in text


def test_a_default_backfill_leaves_the_witness_null(tmp_path: Path) -> None:
    """A bare repair must not invent a witness. Null makes the absence visible, nothing more.

    An invented witness would be worse than none: it would satisfy
    is_active_blocked_with_evidence and convert an unevaluable hold into a false one.
    """
    vault, note = _vault(tmp_path)
    _run("repair-fixture", vault)
    assert "blocked_witness: null" in note.read_text(encoding="utf-8")


def test_repair_still_refuses_a_non_scaffolding_field(tmp_path: Path) -> None:
    """Widening the scaffold set by one field must not widen it generally."""
    vault, _ = _vault(tmp_path)
    result = _run("repair-fixture", vault, "--set", "status=offered")
    assert "REFUSED" in result.stdout + result.stderr
    assert "not a scaffolding field" in result.stdout + result.stderr


def test_repair_never_overwrites_an_existing_witness(tmp_path: Path) -> None:
    """Backfill means absent-only. Overwriting would let repair rewrite live evidence."""
    body = TASK.replace(
        "blocked_reason: waiting_for_something",
        "blocked_reason: waiting_for_something\nblocked_witness: the-original-witness",
    )
    vault, note = _vault(tmp_path, body)
    _run("repair-fixture", vault, "--set", "blocked_witness=a-different-witness")
    text = note.read_text(encoding="utf-8")
    assert "blocked_witness: the-original-witness" in text
    assert "a-different-witness" not in text
