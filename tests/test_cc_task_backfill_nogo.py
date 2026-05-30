"""Tests for scripts/cc-task-backfill-nogo (FR-PACKET-VALIDATOR-TEMPLATE-GAP).

A one-shot batch that backfills missing no-go fields across every active cc-task
via the diff-gated cc-task-repair path, idempotently — so the ~90%+ of live
tasks missing these fields stop hitting a release-time wall on first push.

Subprocess against synthetic vault fixtures under ``tmp_path`` (HOME override).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "cc-task-backfill-nogo"

NOGO_BOOLEANS = (
    "implementation_authorized",
    "source_mutation_authorized",
    "docs_mutation_authorized",
    "runtime_mutation_authorized",
    "release_authorized",
    "public_current",
)


def _active_dir(tmp_path: Path) -> Path:
    active = tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    active.mkdir(parents=True, exist_ok=True)
    return active


def _make_note(active: Path, task_id: str, *, with_nogo: bool) -> Path:
    nogo_block = ""
    if with_nogo:
        nogo_block = (
            "route_metadata_schema: 1\n"
            "stage: S6_IMPLEMENTATION\n"
            + "".join(f"{field}: false\n" for field in NOGO_BOOLEANS)
            + "mutation_scope_refs: []\ndepends_on: []\nblocks: []\n"
        )
    note = active / f"{task_id}-fixture.md"
    session = "\n## Session log\n" if with_nogo else ""
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "Backfill fixture"
priority: p2
wsjf: 5.0
status: offered
assigned_to: unassigned
parent_spec: ~/projects/hapax-council/docs/specs/x.md
authority_case: CASE-TEST-001
quality_floor: standard
mutation_surface: source
authority_level: authoritative
created_at: 2026-05-29T00:00:00Z
updated_at: 2026-05-29T00:00:00Z
{nogo_block}---

# Backfill fixture
{session}"""
    )
    return note


def _run_backfill(*args: str, home: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CLAUDE_ROLE"] = "eta"
    return subprocess.run(
        ["python3", str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_backfills_notes_missing_nogo(tmp_path: Path) -> None:
    active = _active_dir(tmp_path)
    incomplete1 = _make_note(active, "bf-001", with_nogo=False)
    incomplete2 = _make_note(active, "bf-002", with_nogo=False)
    complete = _make_note(active, "bf-003", with_nogo=True)
    complete_before = complete.read_text(encoding="utf-8")

    result = _run_backfill(home=tmp_path)
    assert result.returncode == 0, f"out={result.stdout!r} err={result.stderr!r}"

    for note in (incomplete1, incomplete2):
        text = note.read_text(encoding="utf-8")
        for field in NOGO_BOOLEANS:
            assert f"{field}: false" in text, f"{note.name} missing {field}:\n{text}"
    # A note that already carries every no-go field is left byte-identical.
    assert complete.read_text(encoding="utf-8") == complete_before


def test_uses_the_repair_path(tmp_path: Path) -> None:
    active = _active_dir(tmp_path)
    _make_note(active, "bf-repair-001", with_nogo=False)
    result = _run_backfill(home=tmp_path)
    assert result.returncode == 0, result.stderr
    ledger = tmp_path / ".cache" / "hapax" / "cc-task-gate-bootstrap-ledger.jsonl"
    assert ledger.exists(), "backfill must drive cc-task-repair (which ledgers task_repair)"
    records = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert any(r.get("kind") == "task_repair" for r in records), records


def test_idempotent_second_run_changes_nothing(tmp_path: Path) -> None:
    active = _active_dir(tmp_path)
    note = _make_note(active, "bf-idem-001", with_nogo=False)
    first = _run_backfill(home=tmp_path)
    assert first.returncode == 0, first.stderr
    after_first = note.read_text(encoding="utf-8")

    second = _run_backfill(home=tmp_path)
    assert second.returncode == 0, second.stderr
    assert note.read_text(encoding="utf-8") == after_first  # no churn on re-run
