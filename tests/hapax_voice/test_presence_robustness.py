"""Robustness and edge-case tests for PresenceDetector.

Covers audio frame edge cases, VAD window pruning boundaries,
face decay boundaries, composite score matrix, and transition events.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch

from agents.hapax_voice.presence import PresenceDetector, SAMPLE_RATE


# ---------------------------------------------------------------------------
# Audio frame edge cases
# ---------------------------------------------------------------------------


class TestProcessAudioFrameEdgeCases:
    """Edge cases for process_audio_frame with unusual byte inputs."""

    def _make_detector_with_mock_model(self, return_prob: float = 0.5):
        """Return a detector whose load_model returns a callable mock model."""
        detector = PresenceDetector()
        mock_model = MagicMock()
        mock_model.return_value.item.return_value = return_prob
        detector._vad_model = mock_model
        return detector

    def test_process_audio_frame_wrong_byte_length(self):
        """101 bytes is not a multiple of 2 (int16 = 2 bytes).
        np.frombuffer raises ValueError — the code does not guard against this,
        so callers must ensure even byte lengths."""
        detector = self._make_detector_with_mock_model(return_prob=0.5)
        with pytest.raises(ValueError, match="buffer size must be a multiple of element size"):
            detector.process_audio_frame(b"\x00" * 101)

    def test_process_audio_frame_empty_bytes(self):
        """Empty audio chunk → model receives a zero-length tensor.
        The mock model will still return a value; verify no crash."""
        detector = self._make_detector_with_mock_model(return_prob=0.1)
        result = detector.process_audio_frame(b"")
        assert isinstance(result, float)

    def test_process_audio_frame_exact_frame_size(self):
        """960 bytes = 480 samples * 2 bytes. Standard 30ms frame."""
        detector = self._make_detector_with_mock_model(return_prob=0.8)
        audio = b"\x00" * 960
        result = detector.process_audio_frame(audio)
        assert result == 0.8
        # Model should have been called with a tensor of 480 samples
        call_args = detector._vad_model.call_args
        tensor_arg = call_args[0][0]
        assert tensor_arg.shape == (480,)
        assert call_args[0][1] == SAMPLE_RATE

    def test_process_audio_frame_oversized(self):
        """9600 bytes = 4800 samples (10x normal). Should not crash."""
        detector = self._make_detector_with_mock_model(return_prob=0.6)
        audio = b"\x00" * 9600
        result = detector.process_audio_frame(audio)
        assert result == 0.6
        tensor_arg = detector._vad_model.call_args[0][0]
        assert tensor_arg.shape == (4800,)


# ---------------------------------------------------------------------------
# VAD event window pruning
# ---------------------------------------------------------------------------


class TestVADEventWindow:
    """Sliding-window pruning and threshold boundary tests."""

    def test_window_prune_removes_old_events(self):
        """Events older than window_minutes are pruned on score access."""
        detector = PresenceDetector(window_minutes=1, vad_threshold=0.4)
        base = 1000.0
        with patch("agents.hapax_voice.presence.time") as mock_time:
            # Record events at t=1000
            mock_time.monotonic.return_value = base
            for _ in range(5):
                detector.record_vad_event(0.9)
            assert len(detector._events) == 5

            # Advance past 1-minute window (61 seconds)
            mock_time.monotonic.return_value = base + 61.0
            _ = detector.score  # triggers _prune_old_events
            assert len(detector._events) == 0

    def test_window_boundary_exact_cutoff(self):
        """Event exactly at cutoff boundary is NOT pruned (< cutoff, not <=)."""
        detector = PresenceDetector(window_minutes=1, vad_threshold=0.4)
        base = 1000.0
        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = base
            detector.record_vad_event(0.9)

            # At exactly base + 60s, cutoff = (base+60) - 60 = base
            # Event at base is NOT < base, so not pruned
            mock_time.monotonic.return_value = base + 60.0
            _ = detector.score
            assert len(detector._events) == 1

            # At base + 60.001, cutoff = base + 0.001
            # Event at base IS < base + 0.001, so pruned
            mock_time.monotonic.return_value = base + 60.001
            _ = detector.score
            assert len(detector._events) == 0

    def test_below_threshold_events_not_recorded(self):
        """Confidence below threshold → event NOT recorded."""
        detector = PresenceDetector(vad_threshold=0.4)
        detector.record_vad_event(0.3)
        assert len(detector._events) == 0

    def test_at_threshold_events_recorded(self):
        """Confidence exactly at threshold → IS recorded (< threshold, not <=)."""
        detector = PresenceDetector(vad_threshold=0.4)
        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            detector.record_vad_event(0.4)
        # 0.4 is NOT < 0.4, so it passes the guard and IS recorded
        assert len(detector._events) == 1

    def test_above_threshold_recorded(self):
        """Confidence above threshold → recorded."""
        detector = PresenceDetector(vad_threshold=0.4)
        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            detector.record_vad_event(0.41)
        assert len(detector._events) == 1


# ---------------------------------------------------------------------------
# Face detection decay
# ---------------------------------------------------------------------------


class TestFaceDetectionDecay:
    """Face detection decay window boundary tests."""

    def test_face_decay_exact_boundary(self):
        """At exactly _face_decay_s after detection → NOT decayed (> not >=)."""
        detector = PresenceDetector()
        base = 1000.0
        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = base
            detector.record_face_event(detected=True, count=1)

            # Exactly at decay boundary: elapsed == _face_decay_s (30s)
            # (30.0) > 30.0 is False → still detected
            mock_time.monotonic.return_value = base + detector._face_decay_s
            assert detector.face_detected is True

    def test_face_decay_just_after_boundary(self):
        """Just past decay window → decayed."""
        detector = PresenceDetector()
        base = 1000.0
        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = base
            detector.record_face_event(detected=True, count=1)

            mock_time.monotonic.return_value = base + detector._face_decay_s + 0.001
            assert detector.face_detected is False

    def test_face_decay_just_before_boundary(self):
        """Just inside decay window → still detected."""
        detector = PresenceDetector()
        base = 1000.0
        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = base
            detector.record_face_event(detected=True, count=1)

            mock_time.monotonic.return_value = base + detector._face_decay_s - 0.001
            assert detector.face_detected is True

    def test_face_count_resets_on_not_detected(self):
        """record_face_event(detected=False) → face_count becomes 0."""
        detector = PresenceDetector()
        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            detector.record_face_event(detected=True, count=3)
            assert detector.face_count == 3

            detector.record_face_event(detected=False, count=5)
            assert detector._face_count == 0
            assert detector.face_count == 0


# ---------------------------------------------------------------------------
# Composite score matrix
# ---------------------------------------------------------------------------


class TestCompositeScoreMatrix:
    """Exhaustive composite score tests for all VAD count × face combinations."""

    def _detector_with_events(self, vad_count: int, face: bool) -> PresenceDetector:
        """Build a detector with the given number of VAD events and face state."""
        detector = PresenceDetector(window_minutes=5, vad_threshold=0.4)
        base = 1000.0
        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = base
            for _ in range(vad_count):
                detector.record_vad_event(0.9)
            if face:
                detector.record_face_event(detected=True, count=1)
        # Patch time for score access too (keep events within window)
        self._base = base
        return detector

    def _score_at(self, detector: PresenceDetector, t: float) -> str:
        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = t
            return detector.score

    def test_score_definitely_present(self):
        """5+ VAD events + face → definitely_present."""
        detector = self._detector_with_events(5, face=True)
        assert self._score_at(detector, self._base + 1.0) == "definitely_present"

    def test_score_likely_present_vad_only(self):
        """5+ VAD events, no face → likely_present."""
        detector = self._detector_with_events(6, face=False)
        assert self._score_at(detector, self._base + 1.0) == "likely_present"

    def test_score_uncertain(self):
        """2-4 VAD events, no face → uncertain."""
        for count in (2, 3, 4):
            detector = self._detector_with_events(count, face=False)
            assert self._score_at(detector, self._base + 1.0) == "uncertain", (
                f"Expected uncertain for {count} events"
            )

    def test_score_likely_present_face_only(self):
        """0-1 VAD events + face → likely_present."""
        for count in (0, 1):
            detector = self._detector_with_events(count, face=True)
            assert self._score_at(detector, self._base + 1.0) == "likely_present", (
                f"Expected likely_present for {count} events + face"
            )

    def test_score_likely_absent(self):
        """0-1 VAD events, no face → likely_absent."""
        for count in (0, 1):
            detector = self._detector_with_events(count, face=False)
            assert self._score_at(detector, self._base + 1.0) == "likely_absent", (
                f"Expected likely_absent for {count} events, no face"
            )

    def test_score_uncertain_with_face_becomes_likely_present(self):
        """2-4 VAD events + face → likely_present (not uncertain)."""
        detector = self._detector_with_events(3, face=True)
        assert self._score_at(detector, self._base + 1.0) == "likely_present"


# ---------------------------------------------------------------------------
# Transition events
# ---------------------------------------------------------------------------


class TestTransitionEvents:
    """Verify presence_transition event emission on score changes."""

    def test_transition_event_on_score_change(self):
        """Score changing from likely_absent → likely_present emits event."""
        detector = PresenceDetector(window_minutes=5, vad_threshold=0.4)
        mock_log = MagicMock()
        detector.set_event_log(mock_log)

        base = 1000.0
        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = base
            # Start at likely_absent (default)
            _ = detector.score
            mock_log.emit.assert_not_called()

            # Add enough events for likely_present (5+)
            for _ in range(5):
                detector.record_vad_event(0.9)

            mock_time.monotonic.return_value = base + 1.0
            result = detector.score

        assert result == "likely_present"
        mock_log.emit.assert_called_once_with(
            "presence_transition",
            **{"from": "likely_absent", "to": "likely_present", "vad_count": 5, "face_detected": False},
        )

    def test_no_transition_event_on_same_score(self):
        """Score staying likely_absent across multiple reads → no event."""
        detector = PresenceDetector(window_minutes=5, vad_threshold=0.4)
        mock_log = MagicMock()
        detector.set_event_log(mock_log)

        with patch("agents.hapax_voice.presence.time") as mock_time:
            mock_time.monotonic.return_value = 1000.0
            _ = detector.score
            _ = detector.score
            _ = detector.score

        mock_log.emit.assert_not_called()
