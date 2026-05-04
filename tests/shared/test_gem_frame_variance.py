"""Tests for shared.gem_frame_variance.

Pinned by parametrized boundary tests so the rating mapping stays
stable across refactors. The variance scorer is the load-bearing
piece behind ``QualityRating.vocal`` for outcome 1's substance
dimension; changes to thresholds need explicit test diffs.
"""

from __future__ import annotations

import pytest

from shared.gem_frame_variance import (
    ACCEPTABLE_FLOOR,
    EXCELLENT_FLOOR,
    GOOD_FLOOR,
    MIN_FRAMES_FOR_RATING,
    VarianceReport,
    score_variance,
)
from shared.segment_observability import QualityRating

# --- Schema invariants ------------------------------------------------------


class TestVarianceReportSchema:
    def test_returns_variance_report_dataclass(self):
        result = score_variance(["a", "b"])
        assert isinstance(result, VarianceReport)
        assert hasattr(result, "rating")
        assert hasattr(result, "variance")
        assert hasattr(result, "mean_similarity")
        assert hasattr(result, "n_frames")
        assert hasattr(result, "n_unique")
        assert hasattr(result, "note")

    def test_thresholds_are_ordered(self):
        # Spec invariant — ratings get harder going EXCELLENT > GOOD > ACCEPTABLE.
        assert ACCEPTABLE_FLOOR < GOOD_FLOOR < EXCELLENT_FLOOR


# --- Empty / minimum-input cases -------------------------------------------


class TestEmptyAndMinimum:
    def test_empty_list_is_poor(self):
        result = score_variance([])
        assert result.rating == QualityRating.POOR
        assert result.n_frames == 0
        assert "too few" in result.note

    def test_single_frame_is_poor(self):
        result = score_variance(["only one frame"])
        assert result.rating == QualityRating.POOR
        assert result.n_frames == 1

    def test_below_min_frames_is_poor_regardless_of_content(self):
        # Even highly varied content but only 1 frame ⇒ POOR.
        result = score_variance(["unique " * 10])
        assert result.rating == QualityRating.POOR

    def test_only_blank_inputs_is_poor(self):
        result = score_variance(["", "   ", "\t"])
        assert result.rating == QualityRating.POOR
        assert result.n_frames == 0

    def test_min_frames_threshold_constant(self):
        assert MIN_FRAMES_FOR_RATING == 2


# --- Rating boundaries ------------------------------------------------------


class TestRatingBoundaries:
    def test_identical_frames_is_poor(self):
        result = score_variance(["the doom of every album"] * 5)
        assert result.rating == QualityRating.POOR
        assert result.variance == pytest.approx(0.0)
        assert result.n_unique == 1

    def test_highly_varied_frames_is_excellent(self):
        # Different topics, different vocab, different lengths.
        frames = [
            "the brutal weight of doom records on tape",
            "Paris in 1968 was raw electric protest",
            "kombucha cultures grow exponentially when fed sugar",
            "compiler optimizations affect cache behavior",
            "echoes from the deep ocean trenches",
        ]
        result = score_variance(frames)
        assert result.rating == QualityRating.EXCELLENT
        assert result.variance > EXCELLENT_FLOOR

    def test_paraphrased_frames_skew_lower(self):
        # Same surface vocabulary, light variation — should land in
        # ACCEPTABLE / POOR, not EXCELLENT.
        frames = [
            "the doom of records on tape",
            "the doom of records on cd",
            "the doom of records on vinyl",
            "the doom of records on flac",
        ]
        result = score_variance(frames)
        assert result.rating in {QualityRating.POOR, QualityRating.ACCEPTABLE}

    def test_completely_disjoint_chars_high_variance(self):
        frames = ["aaaaaaaaaa", "zzzzzzzzzz", "qqqqqqqqqq", "kkkkkkkkkk"]
        result = score_variance(frames)
        assert result.variance > GOOD_FLOOR


# --- Note formatting --------------------------------------------------------


class TestNoteFormatting:
    def test_note_includes_metrics(self):
        frames = ["alpha", "beta", "gamma"]
        result = score_variance(frames)
        assert "variance=" in result.note
        assert "mean_similarity=" in result.note
        assert "n_frames=3" in result.note
        assert "n_unique=3" in result.note

    def test_note_marks_too_few_when_undersized(self):
        result = score_variance([])
        assert "too few" in result.note


# --- Filtering invariants ---------------------------------------------------


class TestFiltering:
    def test_blanks_dont_count_toward_n_frames(self):
        result = score_variance(["valid", "", "  ", "also valid"])
        assert result.n_frames == 2

    def test_non_string_inputs_filtered(self):
        result = score_variance(["valid", None, 42, "also valid"])  # type: ignore[list-item]
        assert result.n_frames == 2
