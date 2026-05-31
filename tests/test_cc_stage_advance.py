"""Tests for scripts/cc-stage-advance — the council-side AVSDLC stage-setter.

Self-contained (no shared conftest): each test builds a synthetic vault under a
pinned HOME and invokes the script via subprocess. Coordination reform Phase 2.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "scripts" / "cc-stage-advance"


def _make_task(
    home: Path,
    task_id: str,
    *,
    stage: str | None = "S6_IMPLEMENTATION",
    authority_case: str | None = "CASE-TEST-001",
    status: str = "in_progress",
) -> Path:
    active = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    active.mkdir(parents=True, exist_ok=True)
    note = active / f"{task_id}-x.md"
    stage_line = f"stage: {stage}\n" if stage else ""
    ac_line = f"authority_case: {authority_case}\n" if authority_case else ""
    note.write_text(
        f"""---
type: cc-task
task_id: {task_id}
title: "T"
status: {status}
assigned_to: alpha
{ac_line}{stage_line}updated_at: 2026-01-01T00:00:00Z
---

# T

## Session log
""",
        encoding="utf-8",
    )
    return note


def _run(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["HAPAX_AGENT_ROLE"] = "alpha"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def _note(home: Path, task_id: str) -> Path:
    active = home / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active"
    return next(iter(active.glob(f"{task_id}-*.md")))


class TestStageAdvance:
    def test_forward_advance_sets_stage_and_ledgers(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t1")
        r = _run(tmp_path, "t1", "S7_RELEASE")
        assert r.returncode == 0, r.stderr
        assert "stage: S7_RELEASE" in _note(tmp_path, "t1").read_text()
        ledger = tmp_path / ".cache" / "hapax" / "authority-case-ledger.jsonl"
        assert ledger.exists()
        rec = json.loads(ledger.read_text().splitlines()[-1])
        assert rec["kind"] == "stage_transition"
        assert rec["from_stage"] == "S6_IMPLEMENTATION"
        assert rec["to_stage"] == "S7_RELEASE"
        assert rec["authority_case"] == "CASE-TEST-001"

    def test_backward_refused_without_flag(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t2", stage="S7_RELEASE")
        r = _run(tmp_path, "t2", "S6_IMPLEMENTATION")
        assert r.returncode == 2
        assert "backward" in r.stderr.lower()

    def test_backward_allowed_with_flag(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t3", stage="S7_RELEASE")
        r = _run(tmp_path, "t3", "S6_IMPLEMENTATION", "--allow-backward")
        assert r.returncode == 0, r.stderr

    def test_invalid_stage_refused(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t4")
        r = _run(tmp_path, "t4", "PHASE_SEVEN")
        assert r.returncode == 2

    def test_missing_authority_case_refused(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t5", authority_case=None)
        r = _run(tmp_path, "t5", "S7_RELEASE")
        assert r.returncode == 2
        assert "authority_case" in r.stderr

    def test_backfill_stage_when_absent(self, tmp_path: Path) -> None:
        _make_task(tmp_path, "t6", stage=None)
        r = _run(tmp_path, "t6", "S6_IMPLEMENTATION")
        assert r.returncode == 0, r.stderr
        assert "stage: S6_IMPLEMENTATION" in _note(tmp_path, "t6").read_text()

    def test_not_found_is_error(self, tmp_path: Path) -> None:
        (tmp_path / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks" / "active").mkdir(
            parents=True
        )
        r = _run(tmp_path, "nope", "S7_RELEASE")
        assert r.returncode == 3
