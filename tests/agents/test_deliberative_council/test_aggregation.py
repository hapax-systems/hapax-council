from __future__ import annotations

from agents.deliberative_council.aggregation import (
    aggregate_scores,
    compute_confidence_band,
    compute_iqr,
    should_shortcircuit,
)
from agents.deliberative_council.models import ConvergenceStatus, PhaseOneResult


def _make_results(scores_per_model: dict[str, dict[str, int]]) -> list[PhaseOneResult]:
    return [
        PhaseOneResult(model_alias=alias, scores=scores, rationale={})
        for alias, scores in scores_per_model.items()
    ]


class TestIQR:
    def test_unanimous(self) -> None:
        assert compute_iqr([4, 4, 4, 4, 4, 4]) == 0.0

    def test_spread(self) -> None:
        assert compute_iqr([1, 2, 3, 4, 5]) > 0

    def test_single_value(self) -> None:
        assert compute_iqr([3]) == 0.0


class TestShortCircuit:
    def test_unanimous_shortcircuits(self) -> None:
        results = _make_results(
            {
                "opus": {"a": 4, "b": 4},
                "balanced": {"a": 4, "b": 4},
                "gemini": {"a": 4, "b": 4},
                "local": {"a": 4, "b": 3},
                "web": {"a": 4, "b": 4},
                "mistral": {"a": 4, "b": 4},
            }
        )
        assert should_shortcircuit(results, threshold=1.0)

    def test_divergent_does_not_shortcircuit(self) -> None:
        results = _make_results(
            {
                "opus": {"a": 5},
                "balanced": {"a": 1},
                "gemini": {"a": 3},
                "local": {"a": 2},
            }
        )
        assert not should_shortcircuit(results, threshold=1.0)


class TestAggregateScores:
    def test_converged(self) -> None:
        results = _make_results({"a": {"x": 4}, "b": {"x": 4}, "c": {"x": 5}, "d": {"x": 4}})
        agg = aggregate_scores(results, contested_threshold=2.0)
        assert agg["x"].status == ConvergenceStatus.CONVERGED
        assert agg["x"].score == 4

    def test_hung(self) -> None:
        results = _make_results({"a": {"x": 1}, "b": {"x": 5}, "c": {"x": 1}, "d": {"x": 5}})
        agg = aggregate_scores(results, contested_threshold=2.0)
        assert agg["x"].status == ConvergenceStatus.HUNG

    def test_contested(self) -> None:
        results = _make_results({"a": {"x": 2}, "b": {"x": 4}, "c": {"x": 3}, "d": {"x": 4}})
        agg = aggregate_scores(results, contested_threshold=2.0)
        assert agg["x"].status in {ConvergenceStatus.CONVERGED, ConvergenceStatus.CONTESTED}


class TestConfidenceBand:
    def test_narrow_for_unanimous(self) -> None:
        lo, hi = compute_confidence_band([4, 4, 4, 4])
        assert lo == hi == 4

    def test_wide_for_spread(self) -> None:
        lo, hi = compute_confidence_band([1, 2, 4, 5])
        assert hi - lo >= 2
