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
    # Redirect the coord SSOT log under the test HOME so emitting a stage event
    # never touches /var/lib/hapax/coord during the test.
    env["HAPAX_COORD_DIR"] = str(home / ".cache" / "hapax" / "coord")
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

    def test_unreadable_source_stage_refuses_instead_of_skipping_the_guard(
        self, tmp_path: Path
    ) -> None:
        """An unreadable CURRENT stage must refuse, not silently disable ordering.

        The backward guard is a conjunction beginning `from_num is not None`, so a stage this
        script cannot parse short-circuited it and the transition proceeded with no ordering
        check at all. The destination already fail-CLOSES; the source fail-OPENED. That
        asymmetry is the defect.

        `S8L_BRIDGE_V3_4_...` is not invented for the test — it is live in an active cc-task,
        and `_STAGE_RE` does not match it because `S8L` is not `S<digits>`.
        """
        _make_task(tmp_path, "t7", stage="S8L_BRIDGE_V3_4_SUPPORT_FREEZE_ACCEPTED_RUNTIME_HOLD")
        r = _run(tmp_path, "t7", "S2_SCOPED")
        assert r.returncode == 2, r.stderr
        assert "cannot read the current stage" in r.stderr
        assert "Next:" in r.stderr, "a refusal must name its own remedy"
        assert "stage: S8L_BRIDGE" in _note(tmp_path, "t7").read_text(), "nothing was written"

    def test_unreadable_source_is_refused_even_with_allow_backward(self, tmp_path: Path) -> None:
        """--allow-backward waives ORDERING; it must not waive UNREADABILITY.

        Collapsing the two would restore the fail-open behind a flag that reads as though it
        only relaxes direction.
        """
        _make_task(tmp_path, "t8", stage="S8L_BRIDGE_V3_4_SUPPORT_FREEZE_ACCEPTED_RUNTIME_HOLD")
        r = _run(tmp_path, "t8", "S2_SCOPED", "--allow-backward")
        assert r.returncode == 2, r.stderr
        assert "cannot read the current stage" in r.stderr

    def test_labelled_stages_in_live_use_still_advance(self, tmp_path: Path) -> None:
        """Guard against over-tightening, with measured numbers.

        Of 2,626 live stage values (2026-08-10), 474 are refused by the canonical catalog but
        472 of those are accepted by this script's `_STAGE_RE` and advance fine. Wiring the
        catalog's `is_legal_stage_edge` here TODAY would refuse all 54 distinct label forms —
        `S1_INTAKE`, `S5_REVIEW_GATE`, `S5_DESIGN` among them — which is precisely why that
        wiring is not part of this change and needs a token/label reconciliation first.
        """
        for label in ("S1_INTAKE", "S5_REVIEW_GATE", "S5_DESIGN", "S4_BLOCKED_ON_DEPENDENCY"):
            task = f"lbl{label.lower().replace('_', '')}"
            _make_task(tmp_path, task, stage=label)
            r = _run(tmp_path, task, "S9_CLOSEOUT")
            assert r.returncode == 0, f"{label} should still advance: {r.stderr}"
