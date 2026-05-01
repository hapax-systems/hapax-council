"""Tests for the affordance winner-similarity Prometheus histogram."""

from __future__ import annotations

import math

import pytest

prometheus_client = pytest.importorskip("prometheus_client")

from shared.affordance_metrics import AffordanceMetrics  # noqa: E402
from shared.affordance_score_metrics import (  # noqa: E402
    WINNER_SIMILARITY_BUCKETS,
    observe_winner_similarity,
    winner_similarity_total_count,
)

# ── Bucket cover ────────────────────────────────────────────────────────


class TestBuckets:
    def test_eleven_buckets_zero_to_one(self) -> None:
        assert WINNER_SIMILARITY_BUCKETS == (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
        assert len(WINNER_SIMILARITY_BUCKETS) == 11

    def test_buckets_strictly_increasing(self) -> None:
        for a, b in zip(WINNER_SIMILARITY_BUCKETS, WINNER_SIMILARITY_BUCKETS[1:], strict=True):
            assert a < b


# ── observe_winner_similarity ──────────────────────────────────────────


class TestObserve:
    def test_in_range_observation_increments_count(self) -> None:
        before = winner_similarity_total_count() or 0
        observe_winner_similarity(0.85)
        after = winner_similarity_total_count() or 0
        assert after - before == 1

    def test_zero_observation_increments_count(self) -> None:
        before = winner_similarity_total_count() or 0
        observe_winner_similarity(0.0)
        after = winner_similarity_total_count() or 0
        assert after - before == 1

    def test_one_observation_increments_count(self) -> None:
        before = winner_similarity_total_count() or 0
        observe_winner_similarity(1.0)
        after = winner_similarity_total_count() or 0
        assert after - before == 1

    def test_negative_value_clamps_to_zero(self) -> None:
        before = winner_similarity_total_count() or 0
        observe_winner_similarity(-0.5)
        after = winner_similarity_total_count() or 0
        assert after - before == 1

    def test_above_one_clamps_to_one(self) -> None:
        before = winner_similarity_total_count() or 0
        observe_winner_similarity(2.5)
        after = winner_similarity_total_count() or 0
        assert after - before == 1

    def test_nan_is_dropped(self) -> None:
        before = winner_similarity_total_count() or 0
        observe_winner_similarity(math.nan)
        after = winner_similarity_total_count() or 0
        assert after - before == 0

    def test_non_numeric_dropped_silently(self) -> None:
        before = winner_similarity_total_count() or 0
        observe_winner_similarity("bogus")  # type: ignore[arg-type]
        after = winner_similarity_total_count() or 0
        assert after - before == 0


# ── AffordanceMetrics wire-in ───────────────────────────────────────────


class TestAffordanceMetricsWiring:
    def test_winner_selection_observes_histogram(self) -> None:
        metrics = AffordanceMetrics()
        before = winner_similarity_total_count() or 0
        metrics.record_selection(
            impingement_source="test",
            impingement_metric="metric",
            candidates_count=10,
            winner="env.weather_conditions",
            winner_similarity=0.72,
            winner_combined=0.65,
        )
        after = winner_similarity_total_count() or 0
        assert after - before == 1

    def test_no_winner_does_not_observe(self) -> None:
        metrics = AffordanceMetrics()
        before = winner_similarity_total_count() or 0
        metrics.record_selection(
            impingement_source="test",
            impingement_metric="metric",
            candidates_count=10,
            winner=None,  # empty selection — dispatch counter handles this
            winner_similarity=0.0,
            winner_combined=0.0,
        )
        after = winner_similarity_total_count() or 0
        assert after - before == 0

    def test_winner_with_zero_similarity_does_not_observe(self) -> None:
        """Defensive: a winner with similarity=0 is anomalous; skip it."""

        metrics = AffordanceMetrics()
        before = winner_similarity_total_count() or 0
        metrics.record_selection(
            impingement_source="test",
            impingement_metric="metric",
            candidates_count=1,
            winner="env.weather_conditions",
            winner_similarity=0.0,
            winner_combined=0.0,
        )
        after = winner_similarity_total_count() or 0
        assert after - before == 0

    def test_record_selection_still_appends_event_list(self) -> None:
        metrics = AffordanceMetrics()
        metrics.record_selection(
            impingement_source="test",
            impingement_metric="metric",
            candidates_count=1,
            winner="env.weather_conditions",
            winner_similarity=0.5,
        )
        assert len(metrics._selections) == 1


# ── Source-level pin ────────────────────────────────────────────────────


class TestSourceWire:
    def test_record_selection_imports_observe_winner_similarity(self) -> None:
        from pathlib import Path

        source = Path("shared/affordance_metrics.py").read_text(encoding="utf-8")
        idx = source.index("def record_selection")
        slice_after = source[idx : idx + 2000]
        assert "affordance_score_metrics" in slice_after, (
            "record_selection must import from affordance_score_metrics"
        )
        # Wire must be guarded by winner-non-None check.
        assert "winner is not None" in slice_after, "wire must skip empty selections (winner=None)"
