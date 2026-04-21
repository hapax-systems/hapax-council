"""Regression tests for preset-variety Phase 6 (task #166).

`AffordancePipeline._maybe_emit_perceptual_distance_impingement` emits a
``content.too-similar-recently`` impingement to the DMN bus when the
recency window has clustered above ``PERCEPTUAL_CLUSTER_THRESHOLD``.

Pins:
- Cluster math (mean pairwise cosine sim).
- No emission below threshold.
- Emission above threshold writes the documented payload.
- Cooldown enforced — no spam from sustained clusters.
- Disabled tracker (window <2) emits nothing.
- Impingement payload carries the right intent_family + content fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from shared.affordance import _RecencyTracker
from shared.affordance_pipeline import (
    PERCEPTUAL_CLUSTER_THRESHOLD,
    PERCEPTUAL_IMPINGEMENT_COOLDOWN_S,
    AffordancePipeline,
)


def test_recency_cluster_similarity_empty_window_returns_zero() -> None:
    tracker = _RecencyTracker(window_size=10)
    assert tracker.cluster_similarity() == 0.0


def test_recency_cluster_similarity_single_entry_returns_zero() -> None:
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("a", [1.0, 0.0])
    assert tracker.cluster_similarity() == 0.0


def test_recency_cluster_similarity_identical_entries_one() -> None:
    """All identical embeddings → mean pairwise sim = 1.0."""
    tracker = _RecencyTracker(window_size=10)
    for i in range(5):
        tracker.record_apply(f"a-{i}", [1.0, 0.0])
    assert tracker.cluster_similarity() == pytest.approx(1.0, abs=1e-9)


def test_recency_cluster_similarity_orthogonal_pair_zero() -> None:
    """Two orthogonal embeddings → mean pairwise sim = 0.0."""
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("a", [1.0, 0.0])
    tracker.record_apply("b", [0.0, 1.0])
    assert tracker.cluster_similarity() == pytest.approx(0.0, abs=1e-9)


def test_recency_cluster_similarity_mixed_high_and_low() -> None:
    """Three near-identical embeddings → high cluster sim."""
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("a", [1.0, 0.05])
    tracker.record_apply("b", [1.0, 0.0])
    tracker.record_apply("c", [0.99, 0.05])
    sim = tracker.cluster_similarity()
    assert sim > 0.99


def test_recency_cluster_similarity_skips_dimension_mismatch() -> None:
    """Pairs whose vectors differ in dimension are skipped silently."""
    tracker = _RecencyTracker(window_size=10)
    tracker.record_apply("a", [1.0, 0.0])
    tracker.record_apply("b", [1.0, 0.0, 0.0])  # mismatch
    tracker.record_apply("c", [1.0, 0.0])
    # a-c pair is identical (sim=1), other pairs skipped → mean = 1.0
    assert tracker.cluster_similarity() == pytest.approx(1.0, abs=1e-9)


# --- Pipeline integration ---


@pytest.fixture
def pipeline():
    return AffordancePipeline()


@pytest.fixture
def imp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect impingement writes to a temp file so the tests don't
    pollute the real /dev/shm/hapax-dmn/ bus."""
    import shared.affordance_pipeline as _ap

    target = tmp_path / "impingements.jsonl"
    monkeypatch.setattr(_ap, "_PERCEPTUAL_IMPINGEMENTS_FILE", target)
    return target


def test_no_emission_below_threshold(pipeline: AffordancePipeline, imp_file: Path) -> None:
    """Cluster similarity below threshold → no write."""
    pipeline._recency.record_apply("a", [1.0, 0.0])
    pipeline._recency.record_apply("b", [0.0, 1.0])
    pipeline._maybe_emit_perceptual_distance_impingement()
    assert not imp_file.exists() or imp_file.read_text() == ""


def test_emission_above_threshold_writes_jsonl(
    pipeline: AffordancePipeline, imp_file: Path
) -> None:
    """Cluster sim ≥ threshold → impingement written with documented payload."""
    for i in range(5):
        pipeline._recency.record_apply(f"x-{i}", [1.0, 0.0])
    pipeline._maybe_emit_perceptual_distance_impingement()
    assert imp_file.exists()
    lines = imp_file.read_text().strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["source"] == "affordance_pipeline.recency"
    assert payload["intent_family"] == "content.too-similar-recently"
    assert payload["content"]["metric"] == "preset_recency_cluster"
    assert payload["content"]["cluster_size"] == 5
    assert payload["content"]["cluster_similarity"] >= PERCEPTUAL_CLUSTER_THRESHOLD
    assert "narrative" in payload["content"]
    assert payload["type"] == "boredom"


def test_cooldown_blocks_back_to_back_emissions(
    pipeline: AffordancePipeline, imp_file: Path
) -> None:
    """Emitting within cooldown window writes only once."""
    for i in range(5):
        pipeline._recency.record_apply(f"x-{i}", [1.0, 0.0])
    pipeline._maybe_emit_perceptual_distance_impingement()
    pipeline._maybe_emit_perceptual_distance_impingement()
    pipeline._maybe_emit_perceptual_distance_impingement()
    lines = imp_file.read_text().strip().splitlines()
    assert len(lines) == 1


def test_cooldown_release_allows_next_emission(
    pipeline: AffordancePipeline, imp_file: Path
) -> None:
    """After cooldown elapses, a new emission is permitted."""
    for i in range(5):
        pipeline._recency.record_apply(f"x-{i}", [1.0, 0.0])
    pipeline._maybe_emit_perceptual_distance_impingement()
    pipeline._last_perceptual_emission_at = (
        pipeline._last_perceptual_emission_at - PERCEPTUAL_IMPINGEMENT_COOLDOWN_S - 1.0
    )
    pipeline._maybe_emit_perceptual_distance_impingement()
    lines = imp_file.read_text().strip().splitlines()
    assert len(lines) == 2


def test_strength_scales_with_cluster_similarity(
    pipeline: AffordancePipeline, imp_file: Path
) -> None:
    """Strength field reflects how clustered the window is."""
    for i in range(4):
        pipeline._recency.record_apply(f"x-{i}", [1.0, 0.0])
    pipeline._maybe_emit_perceptual_distance_impingement()
    payload = json.loads(imp_file.read_text().strip())
    assert payload["strength"] == pytest.approx(1.0, abs=1e-3)


def test_io_error_swallowed_does_not_raise(pipeline: AffordancePipeline, imp_file: Path) -> None:
    """Filesystem failure in the emission path must not raise into the
    select() hot path."""
    for i in range(5):
        pipeline._recency.record_apply(f"x-{i}", [1.0, 0.0])
    with patch.object(Path, "open", side_effect=OSError("disk full")):
        pipeline._maybe_emit_perceptual_distance_impingement()


def test_emission_idempotent_on_empty_window(pipeline: AffordancePipeline, imp_file: Path) -> None:
    """Empty / single-entry window → no emission attempt."""
    pipeline._maybe_emit_perceptual_distance_impingement()
    pipeline._recency.record_apply("only-one", [1.0, 0.0])
    pipeline._maybe_emit_perceptual_distance_impingement()
    assert not imp_file.exists() or imp_file.read_text() == ""
