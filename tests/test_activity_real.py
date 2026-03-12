"""Tests for the ActivityBackend — optical flow activity detection.

All tests mock OpenCV — no real cameras needed in CI.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np

from agents.hapax_voice.backends.activity import (
    ActivityBackend,
    _OpticalFlowAnalyzer,
)
from agents.hapax_voice.backends.emotion import _FrameReader
from agents.hapax_voice.primitives import Behavior

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gray_frame(h: int = 480, w: int = 640, seed: int = 42) -> np.ndarray:
    """Create a synthetic grayscale frame."""
    return np.random.default_rng(seed).integers(0, 255, (h, w), dtype=np.uint8)


def _make_shifted_frame(base: np.ndarray, dx: int = 10) -> np.ndarray:
    """Create a frame shifted horizontally (simulates motion)."""
    shifted = np.zeros_like(base)
    if dx > 0:
        shifted[:, dx:] = base[:, :-dx]
    return shifted


# ===========================================================================
# Optical flow analyzer
# ===========================================================================


class TestOpticalFlowAnalyzer:
    @patch("agents.hapax_voice.backends.activity.cv2")
    def test_identical_frames_zero_activity(self, mock_cv2):
        """No motion between identical frames → activity ≈ 0."""
        # Mock optical flow returning zero vectors
        h, w = 480, 640
        mock_cv2.calcOpticalFlowFarneback.return_value = np.zeros((h, w, 2), dtype=np.float32)

        reader = MagicMock(spec=_FrameReader)
        analyzer = _OpticalFlowAnalyzer(reader)

        gray = _make_gray_frame()
        analyzer._process_frame_pair(gray, gray)

        assert analyzer.activity_level == 0.0

    @patch("agents.hapax_voice.backends.activity.cv2")
    def test_shifted_frame_positive_activity(self, mock_cv2):
        """Motion between frames → activity > 0."""
        h, w = 480, 640
        # Simulate flow vectors with some magnitude
        flow = np.ones((h, w, 2), dtype=np.float32) * 5.0
        mock_cv2.calcOpticalFlowFarneback.return_value = flow

        reader = MagicMock(spec=_FrameReader)
        analyzer = _OpticalFlowAnalyzer(reader)

        gray1 = _make_gray_frame(seed=1)
        gray2 = _make_gray_frame(seed=2)
        analyzer._process_frame_pair(gray1, gray2)

        assert analyzer.activity_level > 0.0

    @patch("agents.hapax_voice.backends.activity.cv2")
    def test_activity_always_in_range(self, mock_cv2):
        """activity_level stays 0.0-1.0 for various flow magnitudes."""
        h, w = 480, 640
        reader = MagicMock(spec=_FrameReader)
        gray = _make_gray_frame()

        for magnitude in [0.0, 0.1, 1.0, 10.0, 100.0]:
            analyzer = _OpticalFlowAnalyzer(reader)
            flow = np.ones((h, w, 2), dtype=np.float32) * magnitude
            mock_cv2.calcOpticalFlowFarneback.return_value = flow
            analyzer._process_frame_pair(gray, gray)
            assert 0.0 <= analyzer.activity_level <= 1.0, (
                f"activity out of range for magnitude={magnitude}"
            )

    @patch("agents.hapax_voice.backends.activity.cv2")
    def test_multiple_frames_converge(self, mock_cv2):
        """EMA converges after multiple consistent frames."""
        h, w = 480, 640
        flow = np.ones((h, w, 2), dtype=np.float32) * 3.0
        mock_cv2.calcOpticalFlowFarneback.return_value = flow

        reader = MagicMock(spec=_FrameReader)
        analyzer = _OpticalFlowAnalyzer(reader)

        gray = _make_gray_frame()
        for _ in range(50):
            analyzer._process_frame_pair(gray, gray)

        # After many consistent frames, should be close to 1.0 (normalized)
        assert analyzer.activity_level > 0.8

    @patch("agents.hapax_voice.backends.activity.cv2")
    def test_last_update_advances(self, mock_cv2):
        """Timestamps advance monotonically."""
        h, w = 480, 640
        mock_cv2.calcOpticalFlowFarneback.return_value = np.zeros((h, w, 2), dtype=np.float32)

        reader = MagicMock(spec=_FrameReader)
        analyzer = _OpticalFlowAnalyzer(reader)

        assert analyzer.last_update == 0.0
        gray = _make_gray_frame()
        prev = 0.0
        for _ in range(5):
            analyzer._process_frame_pair(gray, gray)
            assert analyzer.last_update >= prev
            prev = analyzer.last_update


# ===========================================================================
# ActivityBackend — availability
# ===========================================================================


class TestActivityBackendAvailability:
    def test_no_target_unavailable(self):
        b = ActivityBackend("overhead_gear")
        assert b.available() is False

    @patch("agents.hapax_voice.backends.activity.discover_camera", return_value=None)
    def test_device_not_found_unavailable(self, mock_discover):
        b = ActivityBackend("overhead_gear", target="nonexistent")
        assert b.available() is False

    @patch("agents.hapax_voice.backends.activity.discover_camera", return_value="/dev/video2")
    def test_all_present_available(self, mock_discover):
        b = ActivityBackend("overhead_gear", target="/dev/video2")
        assert b.available() is True
        assert b._device_path == "/dev/video2"


# ===========================================================================
# ActivityBackend — contribute()
# ===========================================================================


class TestActivityBackendContribute:
    def test_contribute_writes_source_qualified_behaviors(self):
        b = ActivityBackend("overhead_gear", target="/dev/video2")
        b._analyzer = MagicMock()
        b._analyzer.activity_level = 0.65
        b._analyzer.last_update = time.monotonic()
        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)
        assert "activity_level:overhead_gear" in behaviors
        assert behaviors["activity_level:overhead_gear"].value == 0.65

    def test_contribute_writes_unqualified_when_no_source_id(self):
        b = ActivityBackend(target="/dev/video2")
        b._analyzer = MagicMock()
        b._analyzer.activity_level = 0.4
        b._analyzer.last_update = time.monotonic()
        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)
        assert "activity_level" in behaviors

    def test_contribute_skips_when_no_data_yet(self):
        b = ActivityBackend("overhead_gear", target="/dev/video2")
        b._analyzer = MagicMock()
        b._analyzer.last_update = 0.0
        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)
        assert len(behaviors) == 0


# ===========================================================================
# ActivityBackend — lifecycle
# ===========================================================================


class TestActivityBackendLifecycle:
    def test_stop_cleans_up(self):
        b = ActivityBackend("overhead_gear", target="/dev/video2")
        mock_analyzer = MagicMock()
        mock_reader = MagicMock()
        b._analyzer = mock_analyzer
        b._frame_reader = mock_reader
        b.stop()
        mock_analyzer.stop.assert_called_once()
        mock_reader.stop.assert_called_once()
        assert b._analyzer is None
        assert b._frame_reader is None
