"""Tests for shared.operator_vad_gate (cc-task audio-audit-D Phase 0).

Pin the gate's three classification paths + Prometheus counter labels.
ResemBlyzer model load is Phase 1; here the match callable is a fixture
returning predetermined cosine similarities.
"""

from __future__ import annotations

import pytest

from shared.operator_vad_gate import (
    DEFAULT_MATCH_THRESHOLD,
    OperatorVADDecision,
    OperatorVADGate,
    hapax_vad_event_total,
)


@pytest.fixture(autouse=True)
def _reset_counter():
    """Clear the module-level counter between tests so per-test asserts work."""
    # prometheus_client Counter has no public reset; clear via internal.
    hapax_vad_event_total.clear()
    yield
    hapax_vad_event_total.clear()


def _counter_value(label: str) -> float:
    return hapax_vad_event_total.labels(is_operator=label)._value.get()


class TestThresholdValidation:
    def test_default_threshold_is_documented_value(self) -> None:
        assert DEFAULT_MATCH_THRESHOLD == 0.75

    def test_threshold_below_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="outside"):
            OperatorVADGate(lambda _: 0.5, match_threshold=-0.1)

    def test_threshold_above_one_rejected(self) -> None:
        with pytest.raises(ValueError, match="outside"):
            OperatorVADGate(lambda _: 0.5, match_threshold=1.5)

    def test_threshold_at_zero_and_one_accepted(self) -> None:
        OperatorVADGate(lambda _: 0.5, match_threshold=0.0)
        OperatorVADGate(lambda _: 0.5, match_threshold=1.0)

    def test_threshold_accessor_reflects_construction(self) -> None:
        gate = OperatorVADGate(lambda _: 0.5, match_threshold=0.82)
        assert gate.match_threshold == 0.82


class TestDecisionPaths:
    def test_match_above_threshold(self) -> None:
        gate = OperatorVADGate(lambda _: 0.9, match_threshold=0.75)
        decision = gate.decide(b"audio-window")
        assert decision.is_operator is True
        assert decision.confidence == pytest.approx(0.9)
        assert decision.reason == "match"
        assert decision.should_duck is True

    def test_match_at_threshold_inclusive(self) -> None:
        """Threshold is inclusive: similarity == threshold should match.

        Pin this so a future tightening doesn't silently flip semantics.
        """
        gate = OperatorVADGate(lambda _: 0.75, match_threshold=0.75)
        decision = gate.decide(b"audio-window")
        assert decision.reason == "match"
        assert decision.is_operator is True

    def test_below_threshold(self) -> None:
        gate = OperatorVADGate(lambda _: 0.5, match_threshold=0.75)
        decision = gate.decide(b"visitor-audio")
        assert decision.is_operator is False
        assert decision.confidence == pytest.approx(0.5)
        assert decision.reason == "below-threshold"
        assert decision.should_duck is False

    def test_no_fingerprint_loaded_fails_open(self) -> None:
        """Phase 0 policy: no fingerprint → treat as operator (fail-open).

        Pin this explicitly because flipping to fail-closed in Phase 1 will
        require a deliberate test edit.
        """
        gate = OperatorVADGate(lambda _: None)
        decision = gate.decide(b"any-audio")
        assert decision.is_operator is True
        assert decision.confidence is None
        assert decision.reason == "unknown-no-fingerprint"
        assert decision.should_duck is True

    def test_match_callable_out_of_range_rejected(self) -> None:
        gate = OperatorVADGate(lambda _: 1.5)
        with pytest.raises(ValueError, match="cosine similarity"):
            gate.decide(b"audio")

    def test_match_callable_negative_rejected(self) -> None:
        gate = OperatorVADGate(lambda _: -0.1)
        with pytest.raises(ValueError, match="cosine similarity"):
            gate.decide(b"audio")


class TestPrometheusCounter:
    def test_match_increments_true_label(self) -> None:
        gate = OperatorVADGate(lambda _: 0.9)
        gate.decide(b"audio")
        assert _counter_value("true") == 1
        assert _counter_value("false") == 0
        assert _counter_value("unknown") == 0

    def test_below_threshold_increments_false_label(self) -> None:
        gate = OperatorVADGate(lambda _: 0.4)
        gate.decide(b"audio")
        assert _counter_value("true") == 0
        assert _counter_value("false") == 1
        assert _counter_value("unknown") == 0

    def test_no_fingerprint_increments_unknown_label(self) -> None:
        gate = OperatorVADGate(lambda _: None)
        gate.decide(b"audio")
        assert _counter_value("true") == 0
        assert _counter_value("false") == 0
        assert _counter_value("unknown") == 1

    def test_repeated_calls_accumulate(self) -> None:
        gate = OperatorVADGate(lambda _: 0.9)
        for _ in range(5):
            gate.decide(b"audio")
        assert _counter_value("true") == 5

    def test_invalid_similarity_does_not_increment(self) -> None:
        """If the callable returns a bad similarity, fail loudly without
        polluting metrics."""
        gate = OperatorVADGate(lambda _: 2.0)
        with pytest.raises(ValueError):
            gate.decide(b"audio")
        assert _counter_value("true") == 0
        assert _counter_value("false") == 0
        assert _counter_value("unknown") == 0


class TestMixedFixture:
    """Auditor D acceptance: with a fixture mixing operator + non-operator
    speech, duck triggers only on operator segments."""

    def test_mixed_stream_only_operator_segments_duck(self) -> None:
        # Synthetic similarities for an alternating stream:
        # operator (0.9), visitor (0.4), operator (0.85), visitor (0.3),
        # operator-warmup (None → fail-open).
        stream = iter([0.9, 0.4, 0.85, 0.3, None])
        gate = OperatorVADGate(lambda _: next(stream))

        decisions: list[OperatorVADDecision] = [gate.decide(b"x") for _ in range(5)]
        ducks = [d.should_duck for d in decisions]

        # Operator segments duck (indexes 0, 2); visitor segments do not (1, 3);
        # warm-up duck is fail-open (4).
        assert ducks == [True, False, True, False, True]
        assert _counter_value("true") == 2
        assert _counter_value("false") == 2
        assert _counter_value("unknown") == 1
