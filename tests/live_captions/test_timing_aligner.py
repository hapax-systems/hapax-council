"""Tests for ``agents.live_captions.timing_aligner``.

Coverage:

- Construction: rejects window < 1; default window applied; explicit
  window respected (deque maxlen tracks the configured window).
- Empty state: ``has_estimate`` is ``False``, ``mean_offset`` is 0,
  ``align`` returns identity with ``had_estimate=False``.
- Single observation: mean equals the observed offset; ``align``
  applies it.
- Steady offset (multiple observations of the same pair): mean is
  exactly the offset; running sum stays clean.
- Drift: mean tracks observations within numerical tolerance.
- Window saturation: oldest sample is evicted; running sum stays
  consistent with ``mean_offset == sum(retained) / len(retained)``.
- Reset: clears samples and running sum.
- Non-finite input: ``nan`` and ``inf`` rejected with ``ValueError``.
"""

from __future__ import annotations

import math

import pytest

from agents.live_captions.timing_aligner import (
    DEFAULT_WINDOW_SIZE,
    AlignmentResult,
    TimingAligner,
)

# ── Construction ─────────────────────────────────────────────────────────


class TestConstruction:
    def test_default_window_is_thirty_two(self) -> None:
        aligner = TimingAligner()
        assert aligner.window == DEFAULT_WINDOW_SIZE
        assert aligner._offsets.maxlen == DEFAULT_WINDOW_SIZE

    def test_explicit_window_respected(self) -> None:
        aligner = TimingAligner(window=8)
        assert aligner.window == 8
        assert aligner._offsets.maxlen == 8

    @pytest.mark.parametrize("bad", [0, -1, -32])
    def test_window_must_be_positive(self, bad: int) -> None:
        with pytest.raises(ValueError, match="window must be >= 1"):
            TimingAligner(window=bad)


# ── Empty state ──────────────────────────────────────────────────────────


class TestEmptyState:
    def test_no_estimate_initially(self) -> None:
        aligner = TimingAligner()
        assert aligner.has_estimate is False
        assert aligner.sample_count == 0
        assert aligner.mean_offset == 0.0

    def test_align_is_identity_when_no_estimate(self) -> None:
        aligner = TimingAligner()
        result = aligner.align(audio_ts=12345.678)
        assert isinstance(result, AlignmentResult)
        assert result.had_estimate is False
        assert result.video_pts == 12345.678


# ── Recording observations ───────────────────────────────────────────────


class TestRecordPair:
    def test_single_pair_yields_offset(self) -> None:
        aligner = TimingAligner()
        aligner.record_pair(audio_ts=100.0, video_pts=99.0)
        assert aligner.has_estimate
        assert aligner.sample_count == 1
        assert aligner.mean_offset == pytest.approx(1.0)

    def test_align_applies_mean_offset(self) -> None:
        aligner = TimingAligner()
        aligner.record_pair(audio_ts=100.0, video_pts=99.0)
        result = aligner.align(audio_ts=200.0)
        assert result.had_estimate is True
        assert result.video_pts == pytest.approx(199.0)

    def test_steady_state_offset(self) -> None:
        """Repeated identical-offset observations yield exactly that offset."""
        aligner = TimingAligner()
        for i in range(10):
            aligner.record_pair(audio_ts=100.0 + i, video_pts=99.5 + i)
        assert aligner.mean_offset == pytest.approx(0.5)

    def test_drift_tracked_in_mean(self) -> None:
        """Increasing offsets shift the running mean."""
        aligner = TimingAligner(window=4)
        # First two pairs: offset 1.0 and 1.0 → mean 1.0
        aligner.record_pair(101.0, 100.0)
        aligner.record_pair(102.0, 101.0)
        assert aligner.mean_offset == pytest.approx(1.0)
        # Add two more at offset 2.0 → mean (1+1+2+2)/4 = 1.5
        aligner.record_pair(103.0, 101.0)
        aligner.record_pair(104.0, 102.0)
        assert aligner.mean_offset == pytest.approx(1.5)

    @pytest.mark.parametrize(
        "audio_ts,video_pts",
        [
            (math.nan, 100.0),
            (100.0, math.nan),
            (math.inf, 100.0),
            (100.0, -math.inf),
        ],
    )
    def test_rejects_non_finite(self, audio_ts: float, video_pts: float) -> None:
        aligner = TimingAligner()
        with pytest.raises(ValueError, match="not finite"):
            aligner.record_pair(audio_ts=audio_ts, video_pts=video_pts)
        # Aligner state untouched.
        assert not aligner.has_estimate


# ── Window saturation ────────────────────────────────────────────────────


class TestWindowSaturation:
    def test_evicts_oldest_when_full(self) -> None:
        aligner = TimingAligner(window=3)
        aligner.record_pair(101.0, 100.0)  # offset 1
        aligner.record_pair(102.0, 100.0)  # offset 2
        aligner.record_pair(103.0, 100.0)  # offset 3
        assert aligner.sample_count == 3
        assert aligner.mean_offset == pytest.approx(2.0)

        aligner.record_pair(104.0, 100.0)  # offset 4; evicts offset=1
        assert aligner.sample_count == 3  # window still 3
        # Retained offsets: 2, 3, 4 → mean 3.
        assert aligner.mean_offset == pytest.approx(3.0)

    def test_running_sum_matches_explicit_sum(self) -> None:
        """Walk a 100-pair sequence through a small window and confirm the
        running mean matches a fresh explicit sum at every step."""
        aligner = TimingAligner(window=8)
        offsets: list[float] = []
        for i in range(100):
            audio_ts = float(i) + 0.5  # 0.5s offset
            video_pts = float(i)
            aligner.record_pair(audio_ts, video_pts)
            offsets.append(audio_ts - video_pts)

            # Compare aligner's mean to the explicit window mean.
            window = offsets[-8:]
            explicit_mean = sum(window) / len(window)
            assert aligner.mean_offset == pytest.approx(explicit_mean), (
                f"mismatch at i={i}: {aligner.mean_offset} vs {explicit_mean}"
            )


# ── Reset ────────────────────────────────────────────────────────────────


class TestReset:
    def test_clears_observations_and_running_sum(self) -> None:
        aligner = TimingAligner(window=4)
        for i in range(4):
            aligner.record_pair(audio_ts=100.0 + i, video_pts=99.0 + i)
        assert aligner.has_estimate
        assert aligner.mean_offset == pytest.approx(1.0)

        aligner.reset()
        assert not aligner.has_estimate
        assert aligner.sample_count == 0
        assert aligner.mean_offset == 0.0

    def test_reset_then_record_starts_fresh(self) -> None:
        aligner = TimingAligner()
        aligner.record_pair(100.0, 99.0)  # offset 1.0
        aligner.reset()
        aligner.record_pair(200.0, 195.0)  # offset 5.0
        assert aligner.mean_offset == pytest.approx(5.0)


# ── AlignmentResult shape ────────────────────────────────────────────────


class TestAlignmentResult:
    def test_is_frozen_dataclass(self) -> None:
        result = AlignmentResult(video_pts=1.0, had_estimate=True)
        with pytest.raises(Exception):  # FrozenInstanceError
            result.video_pts = 2.0  # type: ignore[misc]

    def test_carries_estimate_flag(self) -> None:
        ok = AlignmentResult(video_pts=10.0, had_estimate=True)
        absent = AlignmentResult(video_pts=10.0, had_estimate=False)
        assert ok.had_estimate is True
        assert absent.had_estimate is False
