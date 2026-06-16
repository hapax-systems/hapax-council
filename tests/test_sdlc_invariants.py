"""Tests for the SDLC-ladder runtime invariant trace checks (Phase 3c).

Coordination reform Phase 3c (master design §4.5, NEW-1). The never-stuck
invariants INV-1..5 ship as RUNTIME trace checks: pure, advisory functions over
the ladder + an authority-case-ledger trace. They NEVER raise and NEVER block —
a violation is ledgered, never enforced (TLC stays advisory-only; these are its
runtime companions). INV-4/INV-5 build on Phase 3b ``policy_decide(kernel_up=
False)`` + the cognition carve-out, proving escape survives a dead kernel.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from shared.policy_decide import ToolCall, policy_decide
from shared.sdlc_invariants import (
    SDLC_LADDER,
    InvariantResult,
    Ladder,
    _load_ledger_trace,
    check_all,
    check_inv1_deadlock_freedom,
    check_inv2_liveness,
    check_inv3_escape,
    check_inv4_authority_escapable,
    check_inv5_cognition_writable,
    record_invariant_findings,
)

# --- ladder shape -------------------------------------------------------------


class TestLadderShape:
    def test_has_s0_through_s11(self):
        for n in range(12):
            assert f"S{n}" in SDLC_LADDER.stages

    def test_s11_is_terminal(self):
        assert "S11" in SDLC_LADDER.terminal

    def test_has_disconfirmation_branch_and_blocked(self):
        assert "S3_5" in SDLC_LADDER.stages
        assert SDLC_LADDER.blocked  # non-empty blocked set

    def test_blocked_has_escape_edges(self):
        for b in SDLC_LADDER.blocked:
            assert SDLC_LADDER.transitions.get(b)  # escape exists


# --- INV-1 deadlock-freedom ---------------------------------------------------


class TestInv1DeadlockFreedom:
    def test_holds_on_canonical_ladder(self):
        r = check_inv1_deadlock_freedom()
        assert isinstance(r, InvariantResult)
        assert r.invariant == "INV-1"
        assert r.holds and not r.violations

    def test_detects_nonterminal_deadend(self):
        bad = Ladder(
            stages=("S0", "X"),
            transitions={"S0": frozenset({"X"}), "X": frozenset()},
            terminal=frozenset(),
            blocked=frozenset(),
        )
        r = check_inv1_deadlock_freedom(bad)
        assert not r.holds
        assert any("X" in v for v in r.violations)


# --- INV-3 escape -------------------------------------------------------------


class TestInv3Escape:
    def test_holds_blocked_has_escape(self):
        r = check_inv3_escape()
        assert r.invariant == "INV-3"
        assert r.holds

    def test_detects_blocked_without_escape(self):
        bad = Ladder(
            stages=("BLOCKED",),
            transitions={"BLOCKED": frozenset()},
            terminal=frozenset(),
            blocked=frozenset({"BLOCKED"}),
        )
        r = check_inv3_escape(bad)
        assert not r.holds
        assert any("BLOCKED" in v for v in r.violations)


# --- INV-2 liveness (trace check) ---------------------------------------------


class TestInv2Liveness:
    def test_terminal_task_is_live(self):
        trace = [{"task_id": "t1", "to_stage": "S11", "timestamp": 100.0}]
        r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        assert r.invariant == "INV-2"
        assert r.holds

    def test_fresh_nonterminal_is_live(self):
        trace = [{"task_id": "t1", "to_stage": "S6", "timestamp": 999_000.0}]
        r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        assert r.holds

    def test_stale_nonterminal_violates(self):
        trace = [{"task_id": "t1", "to_stage": "S6", "timestamp": 100.0}]
        r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        assert not r.holds
        assert any("t1" in v for v in r.violations)

    def test_uses_latest_transition_per_task(self):
        trace = [
            {"task_id": "t1", "to_stage": "S6", "timestamp": 100.0},
            {"task_id": "t1", "to_stage": "S11", "timestamp": 999_500.0},
        ]
        r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        assert r.holds  # latest stage is terminal

    def test_unknown_stage_violates(self):
        trace = [{"task_id": "t1", "to_stage": "S99", "timestamp": 999_999.0}]
        r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        assert not r.holds

    def test_empty_trace_holds_vacuously(self):
        r = check_inv2_liveness([], now=1_000_000.0, stale_after_s=3600)
        assert r.holds

    def test_s7_release_is_operational_terminal_not_stuck(self):
        # S7_RELEASE (token "S7") is the OPERATIONAL terminal: a released/merged task
        # is done, not stuck — even when its last ledger stamp is long past. This is
        # the false positive INV-2 fired on ~47 released tasks (the bug this fixes).
        trace = [{"task_id": "released", "to_stage": "S7", "timestamp": 100.0}]
        r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        assert r.holds, r.violations

    def test_stale_s6_stuck_while_released_s7_is_live(self):
        # Discrimination: a stale mid-implementation S6 IS stuck (a real signal), but
        # a stale released S7 is NOT — recognizing S7 must not silence a genuine S6.
        trace = [
            {"task_id": "mid", "to_stage": "S6", "timestamp": 100.0},
            {"task_id": "released", "to_stage": "S7", "timestamp": 100.0},
        ]
        r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        assert not r.holds
        assert any("mid:stuck:S6" in v for v in r.violations)
        assert not any(v.startswith("released") for v in r.violations)

    def test_terminal_task_status_is_operational_terminal_not_stuck(self):
        # Closed task notes are the work-state surface. A done task whose historical
        # stage never advanced past S6 must not page forever as stale implementation.
        trace = [{"task_id": "closed", "to_stage": "S6", "timestamp": 100.0, "task_status": "done"}]
        r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        assert r.holds, r.violations

    def test_evidenced_active_block_is_not_reported_as_unbounded_stuck(self):
        trace = [
            {
                "task_id": "blocked",
                "to_stage": "S5",
                "timestamp": 100.0,
                "task_status": "blocked",
                "blocked_reason": "awaiting_independent_review",
                "blocked_witness": "/tmp/review-packet.md",
            }
        ]
        r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        assert r.holds, r.violations

    def test_blocked_without_witness_still_violates(self):
        trace = [
            {
                "task_id": "blocked",
                "to_stage": "S5",
                "timestamp": 100.0,
                "task_status": "blocked",
                "blocked_reason": "awaiting_independent_review",
            }
        ]
        r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        assert not r.holds
        assert any("blocked:stuck:S5" in v for v in r.violations)


# --- INV-2 ledger parsing: the producer/consumer field contract (regression) --


class TestLoadLedgerTrace:
    """``_load_ledger_trace`` must read the producer's ``ts`` key. Reading the
    wrong key (``timestamp``) silently fell back to 0.0, so every record looked
    ~56 years stale and INV-2 false-positived on every live task. These tests
    pin the producer/consumer field contract that let that bug ship unnoticed.
    """

    def _write(self, records: list[dict]) -> Path:
        fd, name = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        path = Path(name)
        path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
        return path

    def _task_note(
        self,
        vault: Path,
        subdir: str,
        task_id: str,
        *,
        status: str,
        blocked_reason: str | None = None,
        blocked_witness: str | None = None,
    ) -> None:
        directory = vault / subdir
        directory.mkdir(parents=True, exist_ok=True)
        extra = ""
        if blocked_reason is not None:
            extra += f"blocked_reason: {blocked_reason}\n"
        if blocked_witness is not None:
            extra += f"blocked_witness: {blocked_witness}\n"
        (directory / f"{task_id}.md").write_text(
            (f"---\ntype: cc-task\ntask_id: {task_id}\nstatus: {status}\n{extra}---\n"),
            encoding="utf-8",
        )

    def test_parses_producer_ts_key(self):
        iso = "2026-06-02T01:43:51Z"
        expected = datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        path = self._write([{"ts": iso, "task_id": "t1", "to_stage": "S6"}])
        try:
            trace = _load_ledger_trace(path)
        finally:
            path.unlink(missing_ok=True)
        assert len(trace) == 1
        # The bug: a valid record silently parsed to 0.0. Guard the regression.
        assert float(trace[0]["timestamp"]) > 0.0
        assert abs(float(trace[0]["timestamp"]) - expected) < 1.0

    def test_fresh_ts_record_is_live_not_decades_stale(self):
        iso = "2026-06-02T01:43:51Z"
        ref = datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        path = self._write([{"ts": iso, "task_id": "t1", "to_stage": "S6"}])
        try:
            trace = _load_ledger_trace(path)
            # 'now' just after the record: a correctly-parsed fresh record is live.
            r = check_inv2_liveness(trace, now=ref + 60.0, stale_after_s=3600)
        finally:
            path.unlink(missing_ok=True)
        assert r.holds, r.violations

    def test_tolerates_legacy_timestamp_key(self):
        iso = "2026-06-02T01:43:51Z"
        expected = datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        path = self._write([{"timestamp": iso, "task_id": "t1", "to_stage": "S6"}])
        try:
            trace = _load_ledger_trace(path)
        finally:
            path.unlink(missing_ok=True)
        assert abs(float(trace[0]["timestamp"]) - expected) < 1.0

    def test_released_s7_release_record_is_live_via_loader(self):
        # End-to-end: the live ledger writes the full token "S7_RELEASE"; the loader
        # tokenizes it to "S7", which INV-2 must read as the operational terminal
        # (done, not stuck) even for a release stamped days ago.
        iso = "2026-05-25T00:00:00Z"
        ref = datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        path = self._write([{"ts": iso, "task_id": "released", "to_stage": "S7_RELEASE"}])
        try:
            trace = _load_ledger_trace(path)
            r = check_inv2_liveness(trace, now=ref + 7 * 86400.0, stale_after_s=86400.0)
        finally:
            path.unlink(missing_ok=True)
        assert r.holds, r.violations

    def test_non_stage_event_without_to_stage_does_not_override_latest_stage(self):
        iso_stage = "2026-05-25T00:00:00Z"
        iso_event = "2026-06-02T00:00:00Z"
        ref = datetime.fromisoformat(iso_event.replace("Z", "+00:00")).timestamp()
        path = self._write(
            [
                {
                    "kind": "stage_transition",
                    "ts": iso_stage,
                    "task_id": "released",
                    "to_stage": "S7_RELEASE",
                },
                {
                    "kind": "release_authorization",
                    "ts": iso_event,
                    "task_id": "released",
                    "fields": ["release_authorized=true"],
                },
            ]
        )
        try:
            trace = _load_ledger_trace(path)
            r = check_inv2_liveness(trace, now=ref + 7 * 86400.0, stale_after_s=86400.0)
        finally:
            path.unlink(missing_ok=True)
        assert len(trace) == 1
        assert trace[0]["to_stage"] == "S7"
        assert r.holds, r.violations

    def test_non_stage_reoffer_event_with_status_like_to_stage_is_ignored(self):
        iso_stage = "2026-06-02T00:00:00Z"
        iso_event = "2026-06-03T00:00:00Z"
        ref = datetime.fromisoformat(iso_stage.replace("Z", "+00:00")).timestamp()
        path = self._write(
            [
                {
                    "kind": "stage_transition",
                    "ts": iso_stage,
                    "task_id": "mid",
                    "to_stage": "S6_IMPLEMENTATION",
                },
                {
                    "kind": "lane_stalled_reoffer",
                    "ts": iso_event,
                    "task_id": "mid",
                    "to_stage": "offered",
                },
            ]
        )
        try:
            trace = _load_ledger_trace(path)
            r = check_inv2_liveness(trace, now=ref + 7200.0, stale_after_s=3600)
        finally:
            path.unlink(missing_ok=True)
        assert len(trace) == 1
        assert trace[0]["to_stage"] == "S6"
        assert not r.holds
        assert any("mid:stuck:S6" in v for v in r.violations)
        assert not any("unknown_stage:offered" in v for v in r.violations)

    def test_malformed_blank_stage_transition_still_surfaces(self):
        iso = "2026-06-02T00:00:00Z"
        path = self._write([{"kind": "stage_transition", "ts": iso, "task_id": "bad"}])
        try:
            trace = _load_ledger_trace(path)
            r = check_inv2_liveness(trace, now=1_000_000.0, stale_after_s=3600)
        finally:
            path.unlink(missing_ok=True)
        assert len(trace) == 1
        assert not r.holds
        assert any("bad:unknown_stage:<blank>" in v for v in r.violations)

    def test_vault_done_status_suppresses_stale_s6_false_positive(self, tmp_path):
        iso = "2026-06-02T00:00:00Z"
        ref = datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        path = self._write(
            [{"kind": "stage_transition", "ts": iso, "task_id": "closed", "to_stage": "S6"}]
        )
        self._task_note(tmp_path, "closed", "closed", status="done")
        try:
            trace = _load_ledger_trace(path, vault_tasks=tmp_path)
            r = check_inv2_liveness(trace, now=ref + 7 * 86400.0, stale_after_s=86400.0)
        finally:
            path.unlink(missing_ok=True)
        assert trace[0]["task_status"] == "done"
        assert r.holds, r.violations

    def test_vault_evidenced_blocked_status_suppresses_unbounded_stuck_page(self, tmp_path):
        iso = "2026-06-02T00:00:00Z"
        ref = datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
        path = self._write(
            [{"kind": "stage_transition", "ts": iso, "task_id": "blocked", "to_stage": "S5"}]
        )
        self._task_note(
            tmp_path,
            "active",
            "blocked",
            status="blocked",
            blocked_reason="awaiting_independent_review",
            blocked_witness="/tmp/review-packet.md",
        )
        try:
            trace = _load_ledger_trace(path, vault_tasks=tmp_path)
            r = check_inv2_liveness(trace, now=ref + 7 * 86400.0, stale_after_s=86400.0)
        finally:
            path.unlink(missing_ok=True)
        assert trace[0]["task_status"] == "blocked"
        assert r.holds, r.violations


# --- INV-4 / INV-5 build on Phase 3b policy_decide ----------------------------


class TestInv4AuthorityEscapable:
    def test_holds_kernel_down_directionally_correct(self):
        r = check_inv4_authority_escapable()
        assert r.invariant == "INV-4"
        assert r.holds


class TestInv5CognitionWritable:
    def test_holds_cognition_always_allowed(self):
        r = check_inv5_cognition_writable()
        assert r.invariant == "INV-5"
        assert r.holds


# --- check_all + advisory ledger ----------------------------------------------


class TestCheckAll:
    def test_all_canonical_invariants_hold(self):
        results = check_all(trace=[], now=0.0)
        assert {r.invariant for r in results} == {"INV-1", "INV-2", "INV-3", "INV-4", "INV-5"}
        assert all(r.holds for r in results)


class TestRecordFindings:
    def test_records_only_violations(self, tmp_path):
        ledger = tmp_path / "inv.jsonl"
        bad = check_inv3_escape(
            Ladder(
                stages=("BLOCKED",),
                transitions={"BLOCKED": frozenset()},
                terminal=frozenset(),
                blocked=frozenset({"BLOCKED"}),
            )
        )
        good = check_inv1_deadlock_freedom()
        record_invariant_findings([bad, good], ledger_path=ledger)
        lines = ledger.read_text().strip().splitlines()
        assert len(lines) == 1  # only the violation is recorded
        row = json.loads(lines[0])
        assert row["invariant"] == "INV-3"
        assert row["holds"] is False

    def test_never_raises_on_unwritable_path(self):
        bad = check_inv3_escape(
            Ladder(
                stages=("BLOCKED",),
                transitions={"BLOCKED": frozenset()},
                terminal=frozenset(),
                blocked=frozenset({"BLOCKED"}),
            )
        )
        record_invariant_findings([bad], ledger_path="/this/does/not/exist/inv.jsonl")


# --- daemon-down chaos test (INV-4/INV-5) -------------------------------------


class TestDaemonDownChaos:
    """Kill the kernel (kernel_up=False) and prove escape survives (master design §4.5 INV-4)."""

    def test_reversible_work_not_stuck_when_kernel_down(self):
        d = policy_decide(ToolCall("Edit", file_path="shared/foo.py"), None, None, kernel_up=False)
        assert d.allowed  # reversible op fails OPEN — never stuck on a dead kernel

    def test_irreversible_still_blocked_when_kernel_down(self):
        d = policy_decide(ToolCall("Bash", command="gh pr merge 1"), None, None, kernel_up=False)
        assert d.blocked  # the embedded floor still protects irreversible harm

    def test_cognition_writable_when_kernel_down(self):
        path = os.path.expanduser("~/.claude/projects/x/memory/note.md")
        d = policy_decide(ToolCall("Write", file_path=path), None, None, kernel_up=False)
        assert d.allowed  # a blocked lane can always think, even with the kernel down
