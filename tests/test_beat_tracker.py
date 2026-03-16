"""Tests for shared/beat_tracker.py — beat tracking via beat_this."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from shared.beat_tracker import BeatGrid, estimate_bpm


class TestEstimateBpm:
    def test_120bpm(self):
        # 120 BPM = 0.5s per beat
        beats = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
        bpm = estimate_bpm(beats)
        assert bpm == pytest.approx(120.0)

    def test_90bpm(self):
        # 90 BPM = 0.667s per beat
        interval = 60.0 / 90.0
        beats = np.array([i * interval for i in range(8)])
        bpm = estimate_bpm(beats)
        assert bpm == pytest.approx(90.0, rel=0.01)

    def test_empty(self):
        assert estimate_bpm(np.array([])) == 0.0

    def test_single_beat(self):
        assert estimate_bpm(np.array([1.0])) == 0.0

    def test_two_beats(self):
        beats = np.array([0.0, 0.5])
        assert estimate_bpm(beats) == pytest.approx(120.0)

    def test_robust_to_outlier(self):
        """Median-based estimation is robust to one bad interval."""
        # 120 BPM with one double-length gap
        beats = np.array([0.0, 0.5, 1.0, 2.0, 2.5, 3.0, 3.5])
        bpm = estimate_bpm(beats)
        assert bpm == pytest.approx(120.0)  # Median is still 0.5


class TestBeatGrid:
    def test_properties(self):
        beats = np.array([0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5])
        downbeats = np.array([0.0, 2.0])
        grid = BeatGrid(beats=beats, downbeats=downbeats, bpm=120.0, duration=4.0)

        assert grid.beat_count == 8
        assert grid.downbeat_count == 2
        assert grid.bpm == 120.0
        assert grid.duration == 4.0

    def test_time_signature_4_4(self):
        beats = np.arange(0, 4, 0.5)  # 8 beats
        downbeats = np.array([0.0, 2.0])  # 2 downbeats → 4 beats/bar
        grid = BeatGrid(beats=beats, downbeats=downbeats, bpm=120.0, duration=4.0)
        assert grid.time_signature_guess == 4

    def test_time_signature_3_4(self):
        beats = np.arange(0, 3, 0.5)  # 6 beats
        downbeats = np.array([0.0, 1.5])  # 2 downbeats → 3 beats/bar
        grid = BeatGrid(beats=beats, downbeats=downbeats, bpm=120.0, duration=3.0)
        assert grid.time_signature_guess == 3

    def test_time_signature_default(self):
        grid = BeatGrid(beats=np.array([0.0]), downbeats=np.array([]), bpm=0.0, duration=1.0)
        assert grid.time_signature_guess == 4


class TestTrackBeats:
    def test_track_beats_calls_model(self):
        mock_model = MagicMock()
        mock_model.return_value = (
            np.array([0.0, 0.5, 1.0, 1.5]),
            np.array([0.0, 1.0]),
        )

        mock_info = MagicMock()
        mock_info.num_frames = 48000
        mock_info.sample_rate = 48000

        mock_torchaudio = MagicMock()
        mock_torchaudio.info.return_value = mock_info

        with (
            patch("shared.beat_tracker._get_model", return_value=mock_model),
            patch.dict("sys.modules", {"torchaudio": mock_torchaudio}),
        ):
            from shared.beat_tracker import track_beats

            result = track_beats("/tmp/test.wav")

        assert result.bpm == pytest.approx(120.0)
        assert result.beat_count == 4
        assert result.downbeat_count == 2
        assert result.duration == 1.0

    def test_track_beats_failure(self):
        mock_model = MagicMock()
        mock_model.side_effect = RuntimeError("GPU error")

        mock_torchaudio = MagicMock()

        with (
            patch("shared.beat_tracker._get_model", return_value=mock_model),
            patch.dict("sys.modules", {"torchaudio": mock_torchaudio}),
        ):
            from shared.beat_tracker import track_beats

            with pytest.raises(RuntimeError, match="Beat tracking failed"):
                track_beats("/tmp/test.wav")
