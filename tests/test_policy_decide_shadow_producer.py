"""Tests for the policy-decide shadow PRODUCER + evaluator (reform fix, unblock 3b-cutover).

Phase 3b shipped the shadow machinery (``run_shadow`` / ``shadow_compare`` /
``record_divergence``) but nothing invoked it on a live tool-call stream, so the
``3b-cutover`` manifest unit gated on an *evidence-shaped predicate with no
producer*. This module pins the two halves of the fix:

* ``replay_decision_log`` — the PRODUCER. Replays the gate's own decision log
  (which records the gate's REAL exit code, NOT a re-derived ``_LEGACY_*_RE``
  verdict) through ``policy_decide`` and rebuilds the divergence ledger.
* ``evaluate_shadow_clean`` — the missing EVALUATOR. Computes
  "shadow-week-clean + asymmetric-divergence" from the decision log (coverage)
  and the divergence ledger (asymmetry) so a real ledger can actually unblock
  the cutover gate — and an absent/short ledger correctly stays NOT-clean.
"""

import json
from datetime import UTC, datetime

from shared.policy_decide import (
    build_cutover_receipt,
    evaluate_shadow_clean,
    load_window_start,
    replay_decision_log,
    restart_window,
)

# --- A gate decision-log row: the gate's REAL verdict + the state it decided on -


def _row(**over) -> dict:
    """One ``cc-task-gate-decisions.jsonl`` row. ``legacy_exit`` is the gate's real exit."""
    base = dict(
        ts="2026-05-31T12:00:00Z",
        legacy_exit=0,  # 0 = gate allowed, 2 = gate blocked (the REAL exit code)
        role="theta",
        session_id="sid-1",
        task_id="reform-fix-shadow-producer-20260531",
        tool_name="Edit",
        command="",
        file_path="shared/policy_decide.py",
        mutation_surface="source",
        status="in_progress",
        assigned_to="theta",
        authority_case="CASE-FORMAL-GOVERNANCE-001",
        parent_spec="~/Documents/Personal/30-areas/hapax/coordination-reform-master-design-2026-05-30.md",
        stage="S6_IMPLEMENTATION",
        implementation_authorized="true",
        source_mutation_authorized="true",
        docs_mutation_authorized="true",
        runtime_mutation_authorized="false",
        # The gate joins mutation_scope_refs with the \x1f unit separator.
        mutation_scope_refs="shared/policy_decide.py\x1ftests/",
    )
    base.update(over)
    return base


def _write_log(path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


# --- replay_decision_log: the producer -----------------------------------------


class TestReplayProducer:
    def test_writes_divergence_when_legacy_blocks_but_new_allows(self, tmp_path):
        # The FM-16 case-in-chief: the legacy substring gate BLOCKS `git checkout -b`
        # (exit 2); policy_decide correctly ALLOWS it. Replay must record this
        # divergence to the ledger as cutover evidence.
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        _write_log(
            log,
            [
                _row(
                    tool_name="Bash",
                    command="git checkout -b f origin/main",
                    file_path="",
                    legacy_exit=2,
                )
            ],
        )
        summary = replay_decision_log(log, ledger)
        assert summary["total"] == 1
        assert summary["divergences"] == 1
        assert summary["loosening"] == 1
        assert summary["tightening"] == 0
        rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
        assert len(rows) == 1
        assert rows[0]["legacy_blocked"] is True
        assert rows[0]["new_verdict"] == "allow"
        assert rows[0]["task_id"] == "reform-fix-shadow-producer-20260531"

    def test_no_divergence_when_both_allow(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        _write_log(log, [_row(legacy_exit=0)])  # in-scope edit; gate allowed, policy allows
        summary = replay_decision_log(log, ledger)
        assert summary["total"] == 1
        assert summary["divergences"] == 0
        assert ledger.read_text().strip() == ""

    def test_rebuild_is_idempotent(self, tmp_path):
        # The ledger is a DERIVED projection of the decision log: replaying twice
        # must not double-count (no offset drift, no accumulation).
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        _write_log(
            log,
            [
                _row(
                    tool_name="Bash",
                    command="git checkout -b f origin/main",
                    file_path="",
                    legacy_exit=2,
                )
            ],
        )
        replay_decision_log(log, ledger)
        replay_decision_log(log, ledger)
        rows = [line for line in ledger.read_text().splitlines() if line.strip()]
        assert len(rows) == 1

    def test_counts_tightening_when_legacy_allows_but_new_blocks(self, tmp_path):
        # The dangerous direction: the gate ALLOWED (exit 0) but policy_decide would
        # BLOCK (here: a task missing its authority_case). This is the regression
        # signal the evaluator must catch — replay must tally it as tightening.
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        _write_log(log, [_row(legacy_exit=0, authority_case="")])
        summary = replay_decision_log(log, ledger)
        assert summary["divergences"] == 1
        assert summary["tightening"] == 1
        assert summary["loosening"] == 0

    def test_missing_task_id_is_treated_as_no_claim(self, tmp_path):
        # A gate block before a claim is resolved (no task_id) → policy_decide also
        # blocks at the claim gate → both block → no divergence.
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        _write_log(
            log,
            [
                _row(
                    task_id="",
                    status="",
                    assigned_to="",
                    authority_case="",
                    parent_spec="",
                    legacy_exit=2,
                )
            ],
        )
        summary = replay_decision_log(log, ledger)
        assert summary["divergences"] == 0

    def test_skips_malformed_lines_without_raising(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        log.write_text(
            "not json at all\n"
            + json.dumps(
                _row(
                    tool_name="Bash",
                    command="git checkout -b f origin/main",
                    file_path="",
                    legacy_exit=2,
                )
            )
            + "\n"
            + "{ truncated\n",
            encoding="utf-8",
        )
        summary = replay_decision_log(log, ledger)
        assert summary["total"] == 1  # only the one well-formed row counted
        assert summary["divergences"] == 1

    def test_missing_decision_log_yields_empty_summary(self, tmp_path):
        summary = replay_decision_log(tmp_path / "absent.jsonl", tmp_path / "shadow.jsonl")
        assert summary["total"] == 0
        assert summary["divergences"] == 0


# --- evaluate_shadow_clean: the missing evaluator ------------------------------


def _seed_week(log, ledger, *, days: int, count: int, diverging_rows: list[dict] | None = None):
    """Seed a decision log spanning `days` with `count` allow-agreement rows, then
    replay so the ledger reflects any `diverging_rows`."""
    rows = []
    for i in range(count):
        day = 1 + (i * days) // max(count - 1, 1) if count > 1 else 1
        rows.append(_row(ts=f"2026-05-{day:02d}T12:00:00Z"))
    rows.extend(diverging_rows or [])
    _write_log(log, rows)
    replay_decision_log(log, ledger)


class TestEvaluatorCleanPredicate:
    def test_absent_ledger_is_not_clean(self, tmp_path):
        # The exact bug being fixed: no producer ⇒ no evidence ⇒ MUST NOT read clean.
        result = evaluate_shadow_clean(tmp_path / "absent.jsonl", tmp_path / "absent-shadow.jsonl")
        assert result["clean"] is False
        assert result["coverage_ok"] is False

    def test_full_week_with_only_loosening_divergences_is_clean(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        _seed_week(
            log,
            ledger,
            days=7,
            count=40,
            diverging_rows=[
                _row(
                    tool_name="Bash",
                    command="git checkout -b f origin/main",
                    file_path="",
                    legacy_exit=2,
                )
            ],
        )
        result = evaluate_shadow_clean(log, ledger, min_days=7, min_decisions=10)
        assert result["clean"] is True
        assert result["span_days"] >= 7
        assert result["tightening"] == 0
        assert result["loosening"] >= 1

    def test_tightening_divergence_is_not_clean(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        _seed_week(
            log,
            ledger,
            days=7,
            count=40,
            diverging_rows=[_row(legacy_exit=0, authority_case="")],  # legacy allow, new block
        )
        result = evaluate_shadow_clean(log, ledger, min_days=7, min_decisions=10)
        assert result["clean"] is False
        assert result["asymmetric_ok"] is False
        assert result["tightening"] >= 1

    def test_short_window_is_not_clean(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        _seed_week(log, ledger, days=2, count=40)  # only 2 days of evidence
        result = evaluate_shadow_clean(log, ledger, min_days=7, min_decisions=10)
        assert result["clean"] is False
        assert result["coverage_ok"] is False

    def test_too_few_decisions_is_not_clean(self, tmp_path):
        log = tmp_path / "decisions.jsonl"
        ledger = tmp_path / "shadow.jsonl"
        _seed_week(log, ledger, days=7, count=3)  # week-spanning but only 3 observations
        result = evaluate_shadow_clean(log, ledger, min_days=7, min_decisions=10)
        assert result["clean"] is False
        assert result["coverage_ok"] is False


# --- window restart: exclude pre-restart historical drift from the clean window ---
#
# Converging policy_decide removes the SYSTEMATIC over-blocks, but the historical
# decision log still carries a handful of genuinely-permissive-legacy decisions
# (roleless merges, a scratch worktree, an out-of-scope test edit) that policy_decide
# correctly blocks. Those are not a relaxation regression — so a non-destructive
# window-start boundary lets a fresh 7-day window accrue clean while PRESERVING the
# full log as evidence (vs destructively rotating it). "Restart" = stamp the boundary.


class TestWindowStartFilter:
    def test_replay_stamps_original_decision_ts_in_ledger(self, tmp_path):
        log = tmp_path / "d.jsonl"
        ledger = tmp_path / "s.jsonl"
        _write_log(log, [_row(ts="2026-05-20T00:00:00Z", legacy_exit=0, authority_case="")])
        replay_decision_log(log, ledger)
        rows = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
        assert rows and rows[0]["decision_ts"] == "2026-05-20T00:00:00Z"

    def test_tightening_before_window_start_is_excluded(self, tmp_path):
        log = tmp_path / "d.jsonl"
        ledger = tmp_path / "s.jsonl"
        old_tighten = _row(ts="2026-05-01T00:00:00Z", legacy_exit=0, authority_case="")
        fresh = [_row(ts=f"2026-05-{d:02d}T12:00:00Z") for d in range(20, 28)] * 3
        _write_log(log, [old_tighten, *fresh])
        replay_decision_log(log, ledger)
        ws = datetime(2026, 5, 15, tzinfo=UTC)
        full = evaluate_shadow_clean(log, ledger, min_days=7, min_decisions=10)
        windowed = evaluate_shadow_clean(log, ledger, min_days=7, min_decisions=10, window_start=ws)
        assert full["tightening"] >= 1  # the pre-restart drift counts over the full history
        assert windowed["tightening"] == 0  # excluded after the restart boundary
        assert windowed["clean"] is True
        assert str(windowed["window_start"]).startswith("2026-05-15")

    def test_window_start_file_roundtrip(self, tmp_path):
        f = tmp_path / "window-start"
        assert load_window_start(f) is None
        now = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
        restart_window(f, now=now)
        assert load_window_start(f) == now


class TestCutoverReceipt:
    def test_receipt_records_span_and_asymmetry_with_countdown(self):
        verdict = {
            "clean": False,
            "coverage_ok": False,
            "asymmetric_ok": True,
            "span_days": 2.5,
            "tightening": 0,
            "loosening": 4,
            "min_days": 7.0,
            "total_decisions": 50,
            "reasons": ["short window: 2.5d span < 7.0d shadow week"],
            "window_start": "2026-05-30T00:00:00Z",
        }
        receipt = build_cutover_receipt(verdict, now=datetime(2026, 6, 1, tzinfo=UTC))
        assert receipt["span_days"] == 2.5
        assert receipt["asymmetric_ok"] is True
        assert receipt["cutover_eligible"] is False
        assert receipt["countdown_days"] == 4.5
        assert receipt["window_start"] == "2026-05-30T00:00:00Z"
        assert str(receipt["generated_at"]).startswith("2026-06-01")

    def test_receipt_eligible_when_clean_zero_countdown(self):
        verdict = {
            "clean": True,
            "coverage_ok": True,
            "asymmetric_ok": True,
            "span_days": 8.0,
            "tightening": 0,
            "loosening": 3,
            "min_days": 7.0,
            "total_decisions": 300,
            "reasons": [],
            "window_start": None,
        }
        receipt = build_cutover_receipt(verdict, now=datetime(2026, 6, 10, tzinfo=UTC))
        assert receipt["cutover_eligible"] is True
        assert receipt["countdown_days"] == 0.0
