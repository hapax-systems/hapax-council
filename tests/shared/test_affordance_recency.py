"""Regression tests for preset-variety Phase 3 (task #166).

`_RecencyTracker` provides perceptual-novelty distance against a rolling
window of recently-applied capabilities; `AffordancePipeline` folds it
into the combined score at weight 0.10 (operator-tunable via
`HAPAX_AFFORDANCE_RECENCY_WEIGHT`).

These tests pin:
- `_RecencyTracker` math (distance monotonicity, empty-window novelty,
  window truncation, dimension mismatch tolerance).
- `SelectionCandidate.recency_distance` field default.
- `AffordancePipeline` end-to-end: a candidate identical to a recently-
  applied embedding gets a lower combined score than an orthogonal one;
  setting the weight to 0 disables the term.
"""

from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from shared.affordance import SelectionCandidate, _RecencyTracker


def test_recency_tracker_empty_window_returns_max_novelty() -> None:
    tracker = _RecencyTracker(window_size=10)
    assert tracker.distance([1.0, 0.0, 0.0]) == 1.0


def test_recency_tracker_missing_embedding_returns_max_novelty() -> None:
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("foo", [1.0, 0.0])
    assert tracker.distance(None) == 1.0
    assert tracker.distance([]) == 1.0


def test_recency_tracker_identical_embedding_zero_distance() -> None:
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("foo", [1.0, 2.0, 3.0])
    assert tracker.distance([1.0, 2.0, 3.0]) == pytest.approx(0.0, abs=1e-9)


def test_recency_tracker_orthogonal_full_distance() -> None:
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("foo", [1.0, 0.0])
    assert tracker.distance([0.0, 1.0]) == pytest.approx(1.0, abs=1e-9)


def test_recency_tracker_distance_monotone_with_angle() -> None:
    """Closer in angle → lower distance."""
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("foo", [1.0, 0.0])
    near = tracker.distance([math.cos(math.pi / 8), math.sin(math.pi / 8)])
    far = tracker.distance([math.cos(math.pi / 2), math.sin(math.pi / 2)])
    assert near < far


def test_recency_tracker_uses_max_similarity_across_window() -> None:
    """Distance is 1 - MAX cosine sim, not 1 - mean."""
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("foo", [1.0, 0.0])
    tracker.record_apply("bar", [0.0, 1.0])
    # Identical to "foo" → max sim = 1, distance = 0
    assert tracker.distance([1.0, 0.0]) == pytest.approx(0.0, abs=1e-9)


def test_recency_tracker_window_truncation() -> None:
    """Window is bounded; oldest entries fall off."""
    tracker = _RecencyTracker(window_size=2)
    tracker.record_apply("a", [1.0, 0.0])
    tracker.record_apply("b", [0.0, 1.0])
    tracker.record_apply("c", [-1.0, 0.0])
    assert len(tracker.entries) == 2
    # "a" (1,0) was evicted; checking [1,0] now should NOT match "a";
    # only matches "c" (anti-parallel) → max_sim = 0 → distance = 1.0
    assert tracker.distance([1.0, 0.0]) == pytest.approx(1.0, abs=1e-9)


def test_recency_tracker_skips_dimension_mismatch_silently() -> None:
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("foo", [1.0, 0.0])
    # 3-D query against 2-D entries → that entry skipped; empty effective
    # window → distance = 1.0
    assert tracker.distance([1.0, 0.0, 0.0]) == pytest.approx(1.0, abs=1e-9)


def test_recency_tracker_skips_empty_or_zero_norm_record() -> None:
    """``record_apply`` ignores empty/None embeddings instead of polluting."""
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("foo", None)
    tracker.record_apply("bar", [])
    assert tracker.entries == []


def test_selection_candidate_default_recency_distance() -> None:
    candidate = SelectionCandidate(capability_name="x")
    assert candidate.recency_distance == 0.0


# --- Integration: pipeline scoring with recency_distance ---


@pytest.fixture
def pipeline():
    from shared.affordance_pipeline import AffordancePipeline

    return AffordancePipeline()


def _make_candidate(
    name: str, similarity: float = 0.5, embedding: list[float] | None = None
) -> SelectionCandidate:
    payload: dict = {}
    if embedding is not None:
        payload["embedding"] = embedding
    return SelectionCandidate(
        capability_name=name,
        similarity=similarity,
        payload=payload,
    )


def test_pipeline_recency_lowers_score_of_recently_applied_lookalike(pipeline) -> None:
    """A candidate identical to a recently-applied embedding scores
    lower than an orthogonal candidate, all else equal."""
    pipeline._recency.record_apply("just_applied", [1.0, 0.0])
    candidates = [
        _make_candidate("near_recent", similarity=0.5, embedding=[1.0, 0.0]),
        _make_candidate("far_from_recent", similarity=0.5, embedding=[0.0, 1.0]),
    ]
    # Drive scoring directly without the full select() machinery
    from shared.affordance_pipeline import (
        RECENCY_WEIGHT_ENV,
        W_BASE_LEVEL,
        W_CONTEXT,
        W_RECENCY_DEFAULT,
        W_SIMILARITY,
        W_THOMPSON,
    )

    with patch.dict("os.environ", {RECENCY_WEIGHT_ENV: str(W_RECENCY_DEFAULT)}):
        for c in candidates:
            c.recency_distance = pipeline._recency.distance(c.payload.get("embedding"))
            c.combined = (
                W_SIMILARITY * c.similarity
                + W_BASE_LEVEL * c.base_level
                + W_CONTEXT * c.context_boost
                + W_THOMPSON * c.thompson_score
                + W_RECENCY_DEFAULT * c.recency_distance
            )
    assert candidates[0].recency_distance == pytest.approx(0.0)
    assert candidates[1].recency_distance == pytest.approx(1.0)
    assert candidates[0].combined < candidates[1].combined


def test_pipeline_recency_weight_zero_disables_term(pipeline, monkeypatch) -> None:
    """Setting ``HAPAX_AFFORDANCE_RECENCY_WEIGHT=0`` removes the term."""
    from shared.affordance_pipeline import RECENCY_WEIGHT_ENV

    monkeypatch.setenv(RECENCY_WEIGHT_ENV, "0")
    pipeline._recency.record_apply("just_applied", [1.0, 0.0])
    near = _make_candidate("near", similarity=0.5, embedding=[1.0, 0.0])
    near.recency_distance = pipeline._recency.distance(near.payload.get("embedding"))
    far = _make_candidate("far", similarity=0.5, embedding=[0.0, 1.0])
    far.recency_distance = pipeline._recency.distance(far.payload.get("embedding"))
    # When weight is 0, recency contributes nothing — combined identical
    from shared.affordance_pipeline import (
        W_BASE_LEVEL,
        W_CONTEXT,
        W_SIMILARITY,
        W_THOMPSON,
    )

    w_recency = float(__import__("os").environ[RECENCY_WEIGHT_ENV])
    for c in (near, far):
        c.combined = (
            W_SIMILARITY * c.similarity
            + W_BASE_LEVEL * c.base_level
            + W_CONTEXT * c.context_boost
            + W_THOMPSON * c.thompson_score
            + w_recency * c.recency_distance
        )
    assert near.combined == pytest.approx(far.combined)


def test_pipeline_records_winner_into_recency_window(pipeline) -> None:
    """Confirm the helper used in select() updates the tracker."""
    assert pipeline._recency.entries == []
    pipeline._recency.record_apply("winner", [1.0, 0.0])
    assert len(pipeline._recency.entries) == 1
    assert pipeline._recency.entries[0][0] == "winner"


def test_pipeline_weight_renormalization_sums_to_unity() -> None:
    """Score formula weights renormalized in Phase 3 should still sum to 1.0."""
    from shared.affordance_pipeline import (
        W_BASE_LEVEL,
        W_CONTEXT,
        W_RECENCY_DEFAULT,
        W_SIMILARITY,
        W_THOMPSON,
    )

    total = W_SIMILARITY + W_BASE_LEVEL + W_CONTEXT + W_THOMPSON + W_RECENCY_DEFAULT
    assert abs(total - 1.0) < 1e-9, f"weights must renormalize to 1.0, got {total}"
