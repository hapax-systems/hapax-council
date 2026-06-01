"""Tests for the policy_decide AUTO-PROMOTION state machine (reform 3b-cutover).

Phase 3b shipped the shadow PRODUCER (``replay_decision_log``) and the cutover
EVALUATOR (``evaluate_shadow_clean``), but ``3b-cutover`` — making ``policy_decide``
authoritative — stayed a MANUAL cliff: nothing advanced when the predicate passed.
This module pins the missing piece: a reversible, version-stamped promotion state
machine that auto-advances ``shadow → canary → authoritative`` while the shadow-week
predicate holds, and rolls back the instant it does not.

The transition function ``decide_promotion`` is PURE (time + verdict injected) so the
whole ladder — including the 24h canary dwell and the permanent-canary version reset
(master design §4.1) — is unit-testable without sleeping or touching disk. The
``run_promotion_cycle`` driver wires it to the on-disk state + audit ledger.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.policy_decide import (
    POLICY_DECIDE_FN_VERSION,
    PROMOTION_AUTHORITATIVE,
    PROMOTION_CANARY,
    PROMOTION_SHADOW,
    PromotionState,
    decide_promotion,
    load_promotion_state,
    run_promotion_cycle,
)

_T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
_DAY = timedelta(days=1)


def _verdict(clean: bool, *, tightening: int = 0, total: int = 300, span: float = 8.0) -> dict:
    """A minimal ``evaluate_shadow_clean``-shaped verdict for the transition function."""
    return {
        "clean": clean,
        "coverage_ok": clean,
        "asymmetric_ok": tightening == 0,
        "total_decisions": total,
        "span_days": span,
        "divergences": tightening,
        "loosening": 0,
        "tightening": tightening,
        "reasons": [] if clean else ["synthetic not-clean"],
    }


def _state(
    name: str, *, entered: datetime = _T0, version: str = POLICY_DECIDE_FN_VERSION
) -> PromotionState:
    return PromotionState(
        state=name, policy_version=version, entered_state_at=entered, updated_at=entered
    )


# --- The pure transition function: decide_promotion ---------------------------


class TestDecidePromotion:
    def test_shadow_clean_promotes_to_canary(self):
        decision = decide_promotion(
            _state(PROMOTION_SHADOW),
            _verdict(True),
            policy_version=POLICY_DECIDE_FN_VERSION,
            now=_T0,
        )
        assert decision.from_state == PROMOTION_SHADOW
        assert decision.to_state == PROMOTION_CANARY
        assert decision.changed is True

    def test_shadow_not_clean_stays_shadow(self):
        decision = decide_promotion(
            _state(PROMOTION_SHADOW),
            _verdict(False, tightening=5),
            policy_version=POLICY_DECIDE_FN_VERSION,
            now=_T0,
        )
        assert decision.to_state == PROMOTION_SHADOW
        assert decision.changed is False

    def test_canary_clean_before_window_stays_canary(self):
        decision = decide_promotion(
            _state(PROMOTION_CANARY, entered=_T0),
            _verdict(True),
            policy_version=POLICY_DECIDE_FN_VERSION,
            now=_T0 + timedelta(hours=12),
            canary_window_seconds=24 * 3600,
        )
        assert decision.to_state == PROMOTION_CANARY
        assert decision.changed is False

    def test_canary_clean_after_window_promotes_to_authoritative(self):
        decision = decide_promotion(
            _state(PROMOTION_CANARY, entered=_T0),
            _verdict(True),
            policy_version=POLICY_DECIDE_FN_VERSION,
            now=_T0 + timedelta(hours=25),
            canary_window_seconds=24 * 3600,
        )
        assert decision.to_state == PROMOTION_AUTHORITATIVE
        assert decision.changed is True

    def test_canary_not_clean_rolls_back_to_shadow(self):
        # Reversibility: a tightening divergence appearing mid-canary demotes — never a cliff.
        decision = decide_promotion(
            _state(PROMOTION_CANARY, entered=_T0),
            _verdict(False, tightening=1),
            policy_version=POLICY_DECIDE_FN_VERSION,
            now=_T0 + timedelta(hours=30),
            canary_window_seconds=24 * 3600,
        )
        assert decision.to_state == PROMOTION_SHADOW
        assert decision.changed is True

    def test_authoritative_not_clean_rolls_back_to_shadow(self):
        decision = decide_promotion(
            _state(PROMOTION_AUTHORITATIVE, entered=_T0),
            _verdict(False, tightening=2),
            policy_version=POLICY_DECIDE_FN_VERSION,
            now=_T0 + 10 * _DAY,
        )
        assert decision.to_state == PROMOTION_SHADOW
        assert decision.changed is True

    def test_authoritative_clean_stays_authoritative(self):
        decision = decide_promotion(
            _state(PROMOTION_AUTHORITATIVE, entered=_T0),
            _verdict(True),
            policy_version=POLICY_DECIDE_FN_VERSION,
            now=_T0 + 10 * _DAY,
        )
        assert decision.to_state == PROMOTION_AUTHORITATIVE
        assert decision.changed is False

    def test_version_change_resets_to_shadow_from_canary(self):
        # Permanent canary discipline (§4.1): any policy_decide change re-enters shadow,
        # even a clean canary that already cleared its dwell window.
        decision = decide_promotion(
            _state(PROMOTION_CANARY, entered=_T0, version="0.0.9"),
            _verdict(True),
            policy_version="0.1.0",
            now=_T0 + 5 * _DAY,
            canary_window_seconds=24 * 3600,
        )
        assert decision.to_state == PROMOTION_SHADOW
        assert decision.changed is True
        assert "0.0.9" in decision.reason and "0.1.0" in decision.reason

    def test_version_change_resets_to_shadow_from_authoritative(self):
        decision = decide_promotion(
            _state(PROMOTION_AUTHORITATIVE, entered=_T0, version="0.0.9"),
            _verdict(True),
            policy_version="0.1.0",
            now=_T0 + 5 * _DAY,
        )
        assert decision.to_state == PROMOTION_SHADOW
        assert decision.changed is True

    def test_decision_carries_policy_version_stamp(self):
        decision = decide_promotion(
            _state(PROMOTION_SHADOW), _verdict(True), policy_version="9.9.9", now=_T0
        )
        assert decision.policy_version == "9.9.9"


# --- The on-disk driver: run_promotion_cycle ----------------------------------
#
# These exercise the real evaluate_shadow_clean → decide_promotion → persist → audit
# chain against synthetic decision-log + divergence-ledger files in a temp dir, so the
# driver (not just the pure transition) is covered: a clean week advances and persists,
# a divergent week does not, the canary dwell carries across two ticks via the on-disk
# entry clock, and a too-short window never promotes (the freeze-blocks-thaw guard).


def _iso(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _clean_decision_log(n: int = 6, span_days: float = 8.0) -> list[dict]:
    """``n`` gated-decision rows whose timestamps span ``span_days`` — the coverage evidence."""
    start = _T0 - timedelta(days=span_days)
    step = timedelta(days=span_days) / max(1, n - 1)
    return [{"ts": _iso(start + step * i), "tool_name": "Bash"} for i in range(n)]


def _loosening_row() -> dict:
    """A LOOSENING divergence (legacy blocked, policy_decide allows) — acceptable asymmetry."""
    return {"diverged": True, "legacy_blocked": True, "new_verdict": "allow"}


def _tightening_row() -> dict:
    """A TIGHTENING divergence (legacy allowed, policy_decide blocks) — makes a week NOT clean."""
    return {"diverged": True, "legacy_blocked": False, "new_verdict": "block"}


class TestRunPromotionCycle:
    """The on-disk driver: evaluate_shadow_clean → decide → persist posture → audit ledger."""

    @staticmethod
    def _paths(tmp: str) -> tuple[Path, Path, Path, Path]:
        d = Path(tmp)
        # gate decision log (coverage), divergence ledger (asymmetry), posture, audit ledger
        return (
            d / "decisions.jsonl",
            d / "shadow.jsonl",
            d / "promotion.json",
            d / "promotion.jsonl",
        )

    def test_clean_week_promotes_shadow_to_canary_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlog, sledger, state, ledger = self._paths(tmp)
            _write_jsonl(dlog, _clean_decision_log())
            _write_jsonl(sledger, [_loosening_row()])
            result = run_promotion_cycle(
                decision_log_path=dlog,
                shadow_ledger_path=sledger,
                state_path=state,
                ledger_path=ledger,
                now=_T0,
                min_days=1.0,
                min_decisions=3,
            )
            assert result["clean"] is True
            assert result["from_state"] == PROMOTION_SHADOW
            assert result["to_state"] == PROMOTION_CANARY
            assert result["changed"] is True
            persisted = load_promotion_state(state)
            assert persisted.state == PROMOTION_CANARY
            assert persisted.entered_state_at == _T0
            rows = [json.loads(line) for line in ledger.read_text().splitlines() if line]
            assert len(rows) == 1
            assert rows[0]["to_state"] == PROMOTION_CANARY

    def test_divergent_week_stays_shadow_and_writes_no_audit_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlog, sledger, state, ledger = self._paths(tmp)
            _write_jsonl(dlog, _clean_decision_log())
            _write_jsonl(sledger, [_loosening_row(), _tightening_row()])
            result = run_promotion_cycle(
                decision_log_path=dlog,
                shadow_ledger_path=sledger,
                state_path=state,
                ledger_path=ledger,
                now=_T0,
                min_days=1.0,
                min_decisions=3,
            )
            assert result["clean"] is False
            assert result["to_state"] == PROMOTION_SHADOW
            assert result["changed"] is False
            assert load_promotion_state(state).state == PROMOTION_SHADOW
            assert not ledger.exists()  # no transition → no audit row

    def test_canary_reaches_authoritative_after_dwell_across_two_ticks(self):
        with tempfile.TemporaryDirectory() as tmp:
            dlog, sledger, state, ledger = self._paths(tmp)
            _write_jsonl(dlog, _clean_decision_log())
            _write_jsonl(sledger, [_loosening_row()])
            first = run_promotion_cycle(
                decision_log_path=dlog,
                shadow_ledger_path=sledger,
                state_path=state,
                ledger_path=ledger,
                now=_T0,
                min_days=1.0,
                min_decisions=3,
                canary_window_seconds=24 * 3600,
            )
            assert first["to_state"] == PROMOTION_CANARY
            # 25h later the persisted entry clock has cleared the 24h dwell → authoritative.
            second = run_promotion_cycle(
                decision_log_path=dlog,
                shadow_ledger_path=sledger,
                state_path=state,
                ledger_path=ledger,
                now=_T0 + timedelta(hours=25),
                min_days=1.0,
                min_decisions=3,
                canary_window_seconds=24 * 3600,
            )
            assert second["from_state"] == PROMOTION_CANARY
            assert second["to_state"] == PROMOTION_AUTHORITATIVE
            assert load_promotion_state(state).state == PROMOTION_AUTHORITATIVE

    def test_insufficient_evidence_does_not_promote(self):
        # The freeze-blocks-thaw guard: a short/empty window is NOT clean, so it never promotes.
        with tempfile.TemporaryDirectory() as tmp:
            dlog, sledger, state, ledger = self._paths(tmp)
            _write_jsonl(dlog, _clean_decision_log(n=2, span_days=0.05))
            _write_jsonl(sledger, [])
            result = run_promotion_cycle(
                decision_log_path=dlog,
                shadow_ledger_path=sledger,
                state_path=state,
                ledger_path=ledger,
                now=_T0,
                min_days=7.0,
                min_decisions=200,
            )
            assert result["clean"] is False
            assert result["to_state"] == PROMOTION_SHADOW
