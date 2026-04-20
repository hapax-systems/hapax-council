"""Hypothesis property tests for aggregate_mix_quality + _parse_verdict (D-24 §11.6).

Randomised input coverage for two modules whose per-field surface is
small but whose compositional behaviour benefits from fuzzing:

- ``aggregate_mix_quality`` collapses 6 sub-scores via min(); property
  is that the aggregate is always in [0, 1] OR None, and never
  exceeds any individual normalised sub-score.
- ``Ring2Classifier._parse_verdict`` has a strict JSON-object schema
  contract; randomised malformed inputs MUST raise
  ClassifierParseError (never silently return a corrupt verdict).
"""

from __future__ import annotations

import json
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from shared.governance.classifier_degradation import ClassifierParseError
from shared.governance.ring2_classifier import Ring2Classifier
from shared.mix_quality.aggregate import SubScore, aggregate_mix_quality


class TestAggregateProperties:
    @given(
        values=st.lists(
            st.one_of(st.none(), st.floats(min_value=0.0, max_value=1.0, allow_nan=False)),
            min_size=0,
            max_size=10,
        )
    )
    @settings(max_examples=100)
    def test_aggregate_is_in_unit_interval_or_none(self, values: list[float | None]) -> None:
        """Aggregate ∈ [0,1] ∪ {None} — never exceeds 1.0 or goes negative."""
        subs = [SubScore(name=f"s{i}", value=v, normalised=v) for i, v in enumerate(values)]
        result = aggregate_mix_quality(subs)
        if result.aggregate is not None:
            assert 0.0 <= result.aggregate <= 1.0
            assert not math.isnan(result.aggregate)

    @given(
        values=st.lists(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
            min_size=1,
            max_size=10,
        )
    )
    @settings(max_examples=50)
    def test_aggregate_equals_min(self, values: list[float]) -> None:
        """When all sub-scores have values, aggregate = min(values)."""
        subs = [SubScore(name=f"s{i}", value=v, normalised=v) for i, v in enumerate(values)]
        result = aggregate_mix_quality(subs)
        assert result.aggregate is not None
        assert abs(result.aggregate - min(values)) < 1e-9

    def test_all_none_returns_none(self) -> None:
        """No sub-score has a value → aggregate is None."""
        subs = [SubScore(name=f"s{i}", value=None) for i in range(6)]
        result = aggregate_mix_quality(subs)
        assert result.aggregate is None


class TestParseVerdictProperties:
    """Ring2Classifier._parse_verdict MUST raise ClassifierParseError on bad input."""

    @given(garbage=st.text(min_size=0, max_size=200))
    @settings(max_examples=50)
    def test_random_text_either_parses_or_raises(self, garbage: str) -> None:
        """For arbitrary text input: either produces a valid assessment or raises."""
        cls = Ring2Classifier()
        try:
            assessment = cls._parse_verdict(garbage)
            # If no raise, the assessment must conform to the schema.
            assert assessment.risk in ("none", "low", "medium", "high")
        except ClassifierParseError:
            # Expected on most inputs.
            pass

    @given(
        risk=st.sampled_from(["none", "low", "medium", "high"]),
        allowed=st.booleans(),
        reason=st.text(min_size=0, max_size=100),
    )
    @settings(max_examples=50)
    def test_valid_json_always_parses(self, risk: str, allowed: bool, reason: str) -> None:
        """Well-formed verdicts always parse cleanly."""
        payload = json.dumps({"allowed": allowed, "risk": risk, "reason": reason})
        cls = Ring2Classifier()
        assessment = cls._parse_verdict(payload)
        assert assessment.risk == risk
        # High-risk is always blocked regardless of LLM's allowed field.
        expected_allowed = allowed if risk != "high" else False
        assert assessment.allowed == expected_allowed

    @given(
        bad_risk=st.text(min_size=1, max_size=20).filter(
            lambda s: s not in ("none", "low", "medium", "high")
        )
    )
    @settings(max_examples=30)
    def test_unknown_risk_always_raises(self, bad_risk: str) -> None:
        """Any non-canonical risk value MUST raise."""
        payload = json.dumps({"allowed": True, "risk": bad_risk, "reason": "x"})
        cls = Ring2Classifier()
        with pytest.raises(ClassifierParseError, match="unknown risk"):
            cls._parse_verdict(payload)
