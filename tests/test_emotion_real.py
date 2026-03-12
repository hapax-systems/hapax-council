"""Tests for the real EmotionBackend — camera discovery, frame reader, emotion inference.

All tests mock OpenCV, MediaPipe, and hsemotion — no real cameras, GPU, or
models needed in CI.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import numpy as np

from agents.hapax_voice.backends.emotion import (
    EMOTION_CATEGORIES,
    EmotionBackend,
    _EmotionInference,
    _FrameReader,
    discover_camera,
)
from agents.hapax_voice.primitives import Behavior

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bgr_frame(h: int = 480, w: int = 640) -> np.ndarray:
    """Create a synthetic BGR frame."""
    return np.random.default_rng(42).integers(0, 255, (h, w, 3), dtype=np.uint8)


def _make_gray_frame(h: int = 480, w: int = 640) -> np.ndarray:
    """Create a synthetic grayscale frame."""
    return np.random.default_rng(42).integers(0, 255, (h, w), dtype=np.uint8)


def _mock_face_mesh_results(has_face: bool = True, h: int = 480, w: int = 640):
    """Build a mock MediaPipe FaceMesh result."""
    result = MagicMock()
    if not has_face:
        result.multi_face_landmarks = None
        return result

    # Create landmarks that define a face region (center of frame)
    rng = np.random.default_rng(42)
    landmarks = []
    for _ in range(478):
        lm = MagicMock()
        lm.x = 0.3 + 0.4 * rng.random()  # 30-70% of width
        lm.y = 0.2 + 0.6 * rng.random()  # 20-80% of height
        landmarks.append(lm)
    face = MagicMock()
    face.landmark = landmarks
    result.multi_face_landmarks = [face]
    return result


# ===========================================================================
# Camera discovery
# ===========================================================================


class TestDiscoverCamera:
    @patch("agents.hapax_voice.backends.emotion.cv2")
    def test_find_by_direct_path(self, mock_cv2):
        """Direct /dev/video0 path that opens successfully."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cv2.VideoCapture.return_value = mock_cap
        assert discover_camera("/dev/video0") == "/dev/video0"
        mock_cap.release.assert_called_once()

    @patch("agents.hapax_voice.backends.emotion.os.path.realpath", return_value="/dev/video0")
    @patch(
        "agents.hapax_voice.backends.emotion.os.listdir",
        return_value=["usb-Logitech_C920-video-index0"],
    )
    @patch("agents.hapax_voice.backends.emotion.os.path.isdir", return_value=True)
    @patch("agents.hapax_voice.backends.emotion.cv2")
    def test_find_by_id_substring(self, mock_cv2, mock_isdir, mock_listdir, mock_realpath):
        """Substring 'Logitech' matches a by-id symlink."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cv2.VideoCapture.return_value = mock_cap
        result = discover_camera("Logitech")
        assert result == "/dev/video0"

    @patch("agents.hapax_voice.backends.emotion.os.path.isdir", return_value=False)
    def test_not_found_returns_none(self, mock_isdir):
        """No match anywhere returns None."""
        assert discover_camera("nonexistent_camera") is None

    @patch("agents.hapax_voice.backends.emotion.cv2")
    def test_device_not_openable_returns_none(self, mock_cv2):
        """Path exists but VideoCapture can't open it."""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False
        mock_cv2.VideoCapture.return_value = mock_cap
        assert discover_camera("/dev/video99") is None


# ===========================================================================
# Frame reader
# ===========================================================================


class TestFrameReader:
    def test_get_frame_returns_none_before_start(self):
        reader = _FrameReader("/dev/video0")
        assert reader.get_frame() is None

    def test_stop_releases_capture(self):
        reader = _FrameReader("/dev/video0")
        mock_cap = MagicMock()
        reader._cap = mock_cap
        reader._running = False
        reader.stop()
        mock_cap.release.assert_called_once()
        assert reader._cap is None

    @patch("agents.hapax_voice.backends.emotion.cv2")
    def test_frame_shape_matches_resolution(self, mock_cv2):
        """Verify that a frame stored by the reader has the expected shape."""
        reader = _FrameReader("/dev/video0")
        frame = _make_bgr_frame(480, 640)
        reader._frame = frame
        got = reader.get_frame()
        assert got is not None
        assert got.shape == (480, 640, 3)


# ===========================================================================
# Emotion inference
# ===========================================================================


class TestEmotionInference:
    def _make_inference(self) -> _EmotionInference:
        reader = MagicMock(spec=_FrameReader)
        reader.get_frame.return_value = _make_bgr_frame()
        inf = _EmotionInference(reader)
        return inf

    @patch("agents.hapax_voice.backends.emotion.cv2")
    def test_process_frame_with_face(self, mock_cv2):
        """Frame with a detected face produces valid outputs."""
        mock_cv2.cvtColor.return_value = _make_bgr_frame()  # RGB conversion
        inf = self._make_inference()

        # Mock face mesh
        inf._face_mesh = MagicMock()
        inf._face_mesh.process.return_value = _mock_face_mesh_results(has_face=True)

        # Mock emotion model
        inf._emotion_model = MagicMock()
        inf._emotion_model.predict_emotions.return_value = (
            "happy",
            {"valence": 0.6, "arousal": 0.4},
        )

        frame = _make_bgr_frame()
        inf._process_frame(frame)

        assert 0.0 <= inf.valence <= 1.0
        assert 0.0 <= inf.arousal <= 1.0
        assert inf.dominant in EMOTION_CATEGORIES
        assert inf.last_update > 0.0

    @patch("agents.hapax_voice.backends.emotion.cv2")
    def test_process_frame_no_face(self, mock_cv2):
        """Blank image with no face — values unchanged."""
        mock_cv2.cvtColor.return_value = _make_bgr_frame()
        inf = self._make_inference()

        inf._face_mesh = MagicMock()
        inf._face_mesh.process.return_value = _mock_face_mesh_results(has_face=False)

        original_valence = inf.valence
        original_arousal = inf.arousal
        inf._process_frame(_make_bgr_frame())

        assert inf.valence == original_valence
        assert inf.arousal == original_arousal
        assert inf.last_update == 0.0  # not advanced

    @patch("agents.hapax_voice.backends.emotion.cv2")
    def test_valence_always_in_range(self, mock_cv2):
        """Valence stays 0.0-1.0 for extreme model outputs."""
        mock_cv2.cvtColor.return_value = _make_bgr_frame()
        inf = self._make_inference()
        inf._face_mesh = MagicMock()
        inf._face_mesh.process.return_value = _mock_face_mesh_results(has_face=True)

        for v in [-2.0, -1.0, 0.0, 1.0, 2.0]:
            inf._emotion_model = MagicMock()
            inf._emotion_model.predict_emotions.return_value = (
                "neutral",
                {"valence": v, "arousal": 0.0},
            )
            inf._process_frame(_make_bgr_frame())
            assert 0.0 <= inf.valence <= 1.0, f"valence out of range for raw={v}"

    @patch("agents.hapax_voice.backends.emotion.cv2")
    def test_arousal_always_in_range(self, mock_cv2):
        """Arousal stays 0.0-1.0 for extreme model outputs."""
        mock_cv2.cvtColor.return_value = _make_bgr_frame()
        inf = self._make_inference()
        inf._face_mesh = MagicMock()
        inf._face_mesh.process.return_value = _mock_face_mesh_results(has_face=True)

        for a in [-2.0, -1.0, 0.0, 1.0, 2.0]:
            inf._emotion_model = MagicMock()
            inf._emotion_model.predict_emotions.return_value = (
                "neutral",
                {"valence": 0.0, "arousal": a},
            )
            inf._process_frame(_make_bgr_frame())
            assert 0.0 <= inf.arousal <= 1.0, f"arousal out of range for raw={a}"

    @patch("agents.hapax_voice.backends.emotion.cv2")
    def test_dominant_always_valid_category(self, mock_cv2):
        """Dominant is always one of the 8 valid categories."""
        mock_cv2.cvtColor.return_value = _make_bgr_frame()
        inf = self._make_inference()
        inf._face_mesh = MagicMock()
        inf._face_mesh.process.return_value = _mock_face_mesh_results(has_face=True)

        for emotion in list(EMOTION_CATEGORIES) + ["unknown_junk"]:
            inf._emotion_model = MagicMock()
            inf._emotion_model.predict_emotions.return_value = (
                emotion,
                {"valence": 0.0, "arousal": 0.0},
            )
            inf._process_frame(_make_bgr_frame())
            assert inf.dominant in EMOTION_CATEGORIES

    @patch("agents.hapax_voice.backends.emotion.cv2")
    def test_last_update_advances(self, mock_cv2):
        """Timestamps advance monotonically on successful detection."""
        mock_cv2.cvtColor.return_value = _make_bgr_frame()
        inf = self._make_inference()
        inf._face_mesh = MagicMock()
        inf._face_mesh.process.return_value = _mock_face_mesh_results(has_face=True)
        inf._emotion_model = MagicMock()
        inf._emotion_model.predict_emotions.return_value = (
            "neutral",
            {"valence": 0.0, "arousal": 0.0},
        )

        prev = 0.0
        for _ in range(5):
            inf._process_frame(_make_bgr_frame())
            assert inf.last_update >= prev
            prev = inf.last_update


# ===========================================================================
# EmotionBackend — availability
# ===========================================================================


class TestEmotionBackendAvailability:
    def test_no_target_unavailable(self):
        b = EmotionBackend("face_cam")
        assert b.available() is False

    @patch("agents.hapax_voice.backends.emotion.discover_camera", return_value=None)
    def test_device_not_found_unavailable(self, mock_discover):
        b = EmotionBackend("face_cam", target="nonexistent")
        assert b.available() is False

    @patch("agents.hapax_voice.backends.emotion.discover_camera", return_value="/dev/video0")
    def test_mediapipe_missing_unavailable(self, mock_discover):
        """When mediapipe can't be imported, available() returns False."""
        import sys

        # Temporarily remove mediapipe from sys.modules and add a None entry
        # which causes import to raise ImportError
        saved = sys.modules.pop("mediapipe", "NOT_SET")
        sys.modules["mediapipe"] = None  # type: ignore[assignment]
        try:
            b = EmotionBackend("face_cam", target="/dev/video0")
            assert b.available() is False
        finally:
            del sys.modules["mediapipe"]
            if saved != "NOT_SET":
                sys.modules["mediapipe"] = saved

    @patch("agents.hapax_voice.backends.emotion.discover_camera", return_value="/dev/video0")
    def test_all_present_available(self, mock_discover):
        b = EmotionBackend("face_cam", target="/dev/video0")
        with (
            patch.dict("sys.modules", {"mediapipe": MagicMock(), "hsemotion_onnx": MagicMock()}),
        ):
            assert b.available() is True
            assert b._device_path == "/dev/video0"


# ===========================================================================
# EmotionBackend — contribute()
# ===========================================================================


class TestEmotionBackendContribute:
    def test_contribute_without_inference_is_noop(self):
        b = EmotionBackend("face_cam", target="/dev/video0")
        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)
        assert len(behaviors) == 0

    def test_contribute_writes_source_qualified_behaviors(self):
        b = EmotionBackend("face_cam", target="/dev/video0")
        b._inference = MagicMock()
        b._inference.valence = 0.7
        b._inference.arousal = 0.5
        b._inference.dominant = "happy"
        b._inference.last_update = time.monotonic()
        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)
        assert "emotion_valence:face_cam" in behaviors
        assert "emotion_arousal:face_cam" in behaviors
        assert "emotion_dominant:face_cam" in behaviors
        assert behaviors["emotion_valence:face_cam"].value == 0.7
        assert behaviors["emotion_arousal:face_cam"].value == 0.5
        assert behaviors["emotion_dominant:face_cam"].value == "happy"

    def test_contribute_writes_unqualified_when_no_source_id(self):
        b = EmotionBackend(target="/dev/video0")
        b._inference = MagicMock()
        b._inference.valence = 0.3
        b._inference.arousal = 0.8
        b._inference.dominant = "neutral"
        b._inference.last_update = time.monotonic()
        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)
        assert "emotion_valence" in behaviors
        assert "emotion_arousal" in behaviors
        assert "emotion_dominant" in behaviors

    def test_contribute_skips_when_no_data_yet(self):
        b = EmotionBackend("face_cam", target="/dev/video0")
        b._inference = MagicMock()
        b._inference.last_update = 0.0  # no data yet
        behaviors: dict[str, Behavior] = {}
        b.contribute(behaviors)
        assert len(behaviors) == 0


# ===========================================================================
# EmotionBackend — lifecycle
# ===========================================================================


class TestEmotionBackendLifecycle:
    def test_stop_cleans_up(self):
        b = EmotionBackend("face_cam", target="/dev/video0")
        mock_inference = MagicMock()
        mock_reader = MagicMock()
        b._inference = mock_inference
        b._frame_reader = mock_reader
        b.stop()
        mock_inference.stop.assert_called_once()
        mock_reader.stop.assert_called_once()
        assert b._inference is None
        assert b._frame_reader is None
