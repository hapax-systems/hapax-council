"""Tests for governance replay harness and escalation."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agentgov.escalation import EscalationEvent, extract_escalations, format_ntfy_message
from agentgov.primitives import Veto, VetoChain
from agentgov.replay import (
    DecisionRecord,
    ReplayCertificate,
    ReplayVerdict,
    replay_batch,
    replay_decision,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


def _allow_all_chain() -> VetoChain[dict]:
    return VetoChain([Veto(name="allow", predicate=lambda _: True, axiom="test")])


def _deny_all_chain() -> VetoChain[dict]:
    return VetoChain([Veto(name="deny", predicate=lambda _: False, axiom="test")])


def _make_record(
    id: str = "rec-001",
    allowed: bool = True,
    denied_by: tuple[str, ...] = (),
) -> DecisionRecord:
    return DecisionRecord(
        id=id,
        timestamp="2026-05-16T00:00:00Z",
        context={"action": "test"},
        original_allowed=allowed,
        original_denied_by=denied_by,
    )


# ── Unit tests ──────────────────────────────────────────────────────────────


class TestReplayDecision:
    def test_same_outcome_passes(self):
        record = _make_record(allowed=True)
        cert = replay_decision(record, _allow_all_chain())
        assert cert.verdict == ReplayVerdict.PASS
        assert cert.current_allowed is True

    def test_regression_detected(self):
        record = _make_record(allowed=True)
        cert = replay_decision(record, _deny_all_chain())
        assert cert.verdict == ReplayVerdict.REGRESSION
        assert cert.is_regression
        assert cert.current_denied_by == ("deny",)

    def test_originally_denied_now_allowed_is_fail(self):
        record = _make_record(allowed=False, denied_by=("old-rule",))
        cert = replay_decision(record, _allow_all_chain())
        assert cert.verdict == ReplayVerdict.FAIL
        assert not cert.is_regression

    def test_both_denied_passes(self):
        record = _make_record(allowed=False, denied_by=("deny",))
        cert = replay_decision(record, _deny_all_chain())
        assert cert.verdict == ReplayVerdict.PASS

    def test_certificate_has_timestamp(self):
        cert = replay_decision(_make_record(), _allow_all_chain())
        assert cert.replayed_at != ""


class TestReplayBatch:
    def test_batch_aggregates(self):
        records = [
            _make_record(id="r1", allowed=True),
            _make_record(id="r2", allowed=True),
            _make_record(id="r3", allowed=False, denied_by=("x",)),
        ]
        report = replay_batch(records, _allow_all_chain())
        assert report.total == 3
        assert report.passed == 2
        assert report.failed == 1

    def test_batch_detects_regressions(self):
        records = [
            _make_record(id="r1", allowed=True),
            _make_record(id="r2", allowed=True),
        ]
        report = replay_batch(records, _deny_all_chain())
        assert len(report.regressions) == 2

    def test_empty_batch(self):
        report = replay_batch([], _allow_all_chain())
        assert report.total == 0
        assert report.passed == 0


class TestEscalation:
    def test_extracts_from_regressions(self):
        report = replay_batch(
            [_make_record(id="r1", allowed=True)],
            _deny_all_chain(),
        )
        events = extract_escalations(report)
        assert len(events) == 1
        assert events[0].severity == "regression"
        assert events[0].record_id == "r1"

    def test_no_escalation_on_clean(self):
        report = replay_batch(
            [_make_record(id="r1", allowed=True)],
            _allow_all_chain(),
        )
        events = extract_escalations(report)
        assert len(events) == 0

    def test_format_ntfy_message(self):
        events = [
            EscalationEvent(
                record_id="r1",
                severity="regression",
                summary="test",
                denied_by=("deny",),
            )
        ]
        msg = format_ntfy_message(events)
        assert "1 regression" in msg
        assert "r1" in msg

    def test_format_empty(self):
        assert format_ntfy_message([]) == ""


# ── Hypothesis property tests ───────────────────────────────────────────────

decision_records = st.builds(
    DecisionRecord,
    id=st.text(min_size=1, max_size=20),
    timestamp=st.just("2026-05-16T00:00:00Z"),
    context=st.just({"action": "test"}),
    original_allowed=st.booleans(),
    original_denied_by=st.just(()),
)


class TestReplayProperties:
    @given(record=decision_records)
    @settings(max_examples=50)
    def test_replay_never_raises(self, record: DecisionRecord):
        cert = replay_decision(record, _allow_all_chain())
        assert isinstance(cert, ReplayCertificate)

    @given(record=decision_records)
    @settings(max_examples=50)
    def test_same_chain_same_verdict_is_pass(self, record: DecisionRecord):
        chain = _allow_all_chain() if record.original_allowed else _deny_all_chain()
        cert = replay_decision(record, chain)
        assert cert.verdict == ReplayVerdict.PASS

    @given(records=st.lists(decision_records, min_size=0, max_size=10))
    @settings(max_examples=30)
    def test_batch_count_invariant(self, records: list[DecisionRecord]):
        report = replay_batch(records, _allow_all_chain())
        assert report.total == len(records)
        assert report.passed + report.failed + len(report.regressions) == report.total


# ── Idempotency ───────────────────────────────────────────────────────────


class TestReplayIdempotency:
    def test_replaying_same_sequence_twice_yields_same_verdicts(self):
        records = [
            _make_record(id="r1", allowed=True),
            _make_record(id="r2", allowed=False, denied_by=("old",)),
            _make_record(id="r3", allowed=True),
        ]
        chain = _allow_all_chain()
        report_1 = replay_batch(records, chain)
        report_2 = replay_batch(records, chain)
        verdicts_1 = [(c.record_id, c.verdict) for c in report_1.certificates]
        verdicts_2 = [(c.record_id, c.verdict) for c in report_2.certificates]
        assert verdicts_1 == verdicts_2

    def test_single_decision_idempotent(self):
        record = _make_record(id="idem", allowed=True)
        chain = _deny_all_chain()
        cert_1 = replay_decision(record, chain)
        cert_2 = replay_decision(record, chain)
        assert cert_1.verdict == cert_2.verdict
        assert cert_1.current_allowed == cert_2.current_allowed
        assert cert_1.current_denied_by == cert_2.current_denied_by


# ── Out-of-order input handling ────────────────────────────────────────────


class TestReplayOrdering:
    def test_order_does_not_affect_individual_verdicts(self):
        records = [
            _make_record(id="a", allowed=True),
            _make_record(id="b", allowed=False, denied_by=("x",)),
            _make_record(id="c", allowed=True),
        ]
        chain = _allow_all_chain()
        forward = replay_batch(records, chain)
        backward = replay_batch(list(reversed(records)), chain)
        fwd = {c.record_id: c.verdict for c in forward.certificates}
        bwd = {c.record_id: c.verdict for c in backward.certificates}
        assert fwd == bwd

    def test_shuffled_batch_same_aggregate_counts(self):
        records = [_make_record(id=f"r{i}", allowed=i % 2 == 0) for i in range(6)]
        chain = _allow_all_chain()
        original = replay_batch(records, chain)
        shuffled = replay_batch(records[3:] + records[:3], chain)
        assert original.passed == shuffled.passed
        assert original.failed == shuffled.failed
        assert len(original.regressions) == len(shuffled.regressions)


# ── Malformed / corrupted input ────────────────────────────────────────────


class TestReplayMalformedInput:
    def test_empty_context_replays_without_error(self):
        record = DecisionRecord(
            id="empty-ctx",
            timestamp="2026-05-16T00:00:00Z",
            context={},
            original_allowed=True,
        )
        cert = replay_decision(record, _allow_all_chain())
        assert cert.verdict == ReplayVerdict.PASS

    def test_none_values_in_context(self):
        record = DecisionRecord(
            id="none-ctx",
            timestamp="2026-05-16T00:00:00Z",
            context={"action": None, "extra": None},
            original_allowed=True,
        )
        cert = replay_decision(record, _allow_all_chain())
        assert isinstance(cert, ReplayCertificate)

    def test_unexpected_context_keys_tolerated(self):
        record = DecisionRecord(
            id="extra-keys",
            timestamp="2026-05-16T00:00:00Z",
            context={"unknown_field": 42, "nested": {"deep": True}},
            original_allowed=False,
            original_denied_by=("rule",),
        )
        cert = replay_decision(record, _deny_all_chain())
        assert cert.verdict == ReplayVerdict.PASS

    def test_predicate_exception_propagates(self):
        import pytest

        def bad_predicate(_: dict) -> bool:
            raise ValueError("corrupt data")

        chain = VetoChain([Veto(name="bad", predicate=bad_predicate, axiom="test")])
        record = _make_record(id="error")
        with pytest.raises(ValueError, match="corrupt data"):
            replay_decision(record, chain)
