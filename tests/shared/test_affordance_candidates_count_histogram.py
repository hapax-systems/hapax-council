"""Tests for the affordance candidates_count Prometheus histogram."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

prometheus_client = pytest.importorskip("prometheus_client")

from shared.affordance_metrics import AffordanceMetrics  # noqa: E402
from shared.affordance_score_metrics import (  # noqa: E402
    CANDIDATES_COUNT_BUCKETS,
    candidates_count_total_count,
    observe_candidates_count,
)

# ── Bucket cover ────────────────────────────────────────────────────────


class TestBuckets:
    def test_eight_buckets(self) -> None:
        assert CANDIDATES_COUNT_BUCKETS == (0.0, 1.0, 3.0, 5.0, 10.0, 25.0, 50.0, 100.0)
        assert len(CANDIDATES_COUNT_BUCKETS) == 8

    def test_buckets_strictly_increasing(self) -> None:
        for a, b in pairwise(CANDIDATES_COUNT_BUCKETS):
            assert a < b


# ── observe_candidates_count ───────────────────────────────────────────


class TestObserve:
    def test_zero_increments_count(self) -> None:
        before = candidates_count_total_count() or 0
        observe_candidates_count(0)
        after = candidates_count_total_count() or 0
        assert after - before == 1

    def test_one_increments_count(self) -> None:
        before = candidates_count_total_count() or 0
        observe_candidates_count(1)
        after = candidates_count_total_count() or 0
        assert after - before == 1

    def test_large_value_increments_count(self) -> None:
        # 200 lands in the +Inf overflow bucket but still counts.
        before = candidates_count_total_count() or 0
        observe_candidates_count(200)
        after = candidates_count_total_count() or 0
        assert after - before == 1

    def test_negative_value_dropped(self) -> None:
        before = candidates_count_total_count() or 0
        observe_candidates_count(-5)
        after = candidates_count_total_count() or 0
        assert after - before == 0

    def test_nan_dropped(self) -> None:
        before = candidates_count_total_count() or 0
        observe_candidates_count(math.nan)
        after = candidates_count_total_count() or 0
        assert after - before == 0

    def test_non_numeric_dropped(self) -> None:
        before = candidates_count_total_count() or 0
        observe_candidates_count("bogus")  # type: ignore[arg-type]
        after = candidates_count_total_count() or 0
        assert after - before == 0


# ── AffordanceMetrics wire-in ───────────────────────────────────────────


class TestAffordanceMetricsWiring:
    def test_observed_on_every_selection_with_winner(self) -> None:
        metrics = AffordanceMetrics()
        before = candidates_count_total_count() or 0
        metrics.record_selection(
            impingement_source="test",
            impingement_metric="metric",
            candidates_count=7,
            winner="env.weather_conditions",
            winner_similarity=0.9,
        )
        after = candidates_count_total_count() or 0
        assert after - before == 1

    def test_observed_on_empty_selection(self) -> None:
        """Retrieval-empty case is the most useful one to chart in Grafana.

        Counter trio already tracks the no-winner outcome; this histogram
        captures the candidate count that produced the empty result.
        """

        metrics = AffordanceMetrics()
        before = candidates_count_total_count() or 0
        metrics.record_selection(
            impingement_source="test",
            impingement_metric="metric",
            candidates_count=0,
            winner=None,
            winner_similarity=0.0,
        )
        after = candidates_count_total_count() or 0
        assert after - before == 1

    def test_three_selections_increment_three(self) -> None:
        metrics = AffordanceMetrics()
        before = candidates_count_total_count() or 0
        for cand in (5, 10, 50):
            metrics.record_selection(
                impingement_source="test",
                impingement_metric="metric",
                candidates_count=cand,
                winner=None,
                winner_similarity=0.0,
            )
        after = candidates_count_total_count() or 0
        assert after - before == 3


# ── Source-level pin ────────────────────────────────────────────────────


class TestSourceWire:
    def test_record_selection_imports_observe_candidates_count(self) -> None:
        from pathlib import Path

        source = Path("shared/affordance_metrics.py").read_text(encoding="utf-8")
        idx = source.index("def record_selection")
        slice_after = source[idx : idx + 2500]
        assert "observe_candidates_count" in slice_after, (
            "record_selection must call observe_candidates_count for the wire to fire"
        )
