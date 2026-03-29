"""Tests for FaceDetector."""

from unittest.mock import MagicMock, patch

import numpy as np

from agents.hapax_daimonion.face_detector import FaceDetector


def test_detector_init():
    detector = FaceDetector()
    assert detector is not None


def test_detector_returns_false_on_empty_image():
    detector = FaceDetector()
    result = detector.detect(np.zeros((240, 320, 3), dtype=np.uint8))
    # All-black frame: no face expected
    assert result.detected is False
    assert result.count == 0


def test_detector_result_dataclass():
    from agents.hapax_daimonion.face_detector import FaceResult

    r = FaceResult(detected=True, count=2)
    assert r.detected is True
    assert r.count == 2


def test_detector_handles_none_gracefully():
    detector = FaceDetector()
    result = detector.detect(None)
    assert result.detected is False


def test_detector_from_base64():
    """Detector should accept base64 JPEG input."""
    detector = FaceDetector()
    import base64

    # Minimal valid JPEG
    tiny_jpg = bytes(
        [
            0xFF,
            0xD8,
            0xFF,
            0xE0,
            0x00,
            0x10,
            0x4A,
            0x46,
            0x49,
            0x46,
            0x00,
            0x01,
            0x01,
            0x00,
            0x00,
            0x01,
            0x00,
            0x01,
            0x00,
            0x00,
            0xFF,
            0xD9,
        ]
    )
    b64 = base64.b64encode(tiny_jpg).decode("ascii")
    result = detector.detect_from_base64(b64)
    assert result.detected is False


# --- Failure-mode and edge case tests ---


class TestModelDownloadFailures:
    """Tests for model download failure handling."""

    @patch("agents.hapax_daimonion.face_detector._MODEL_PATH")
    @patch("agents.hapax_daimonion.face_detector.urllib.request.urlretrieve")
    def test_model_download_network_failure(self, mock_urlretrieve, mock_path):
        """URLError during download → _ensure_model returns None, detect returns FaceResult(False, 0)."""
        import urllib.error

        mock_path.exists.return_value = False
        mock_urlretrieve.side_effect = urllib.error.URLError("Connection refused")

        detector = FaceDetector()
        assert detector._ensure_model() is None
        result = detector.detect(np.zeros((240, 320, 3), dtype=np.uint8))
        assert result.detected is False
        assert result.count == 0

    @patch("agents.hapax_daimonion.face_detector._MODEL_PATH")
    @patch("agents.hapax_daimonion.face_detector.urllib.request.urlretrieve")
    def test_model_download_timeout(self, mock_urlretrieve, mock_path):
        """TimeoutError during download → same graceful degradation."""
        mock_path.exists.return_value = False
        mock_urlretrieve.side_effect = TimeoutError("Download timed out")

        detector = FaceDetector()
        assert detector._ensure_model() is None
        result = detector.detect(np.zeros((240, 320, 3), dtype=np.uint8))
        assert result.detected is False
        assert result.count == 0

    @patch("agents.hapax_daimonion.face_detector.urllib.request.urlretrieve")
    @patch("agents.hapax_daimonion.face_detector._MODEL_PATH")
    def test_model_path_exists_skips_download(self, mock_path, mock_urlretrieve):
        """When model file already exists, urlretrieve is never called."""
        mock_path.exists.return_value = True

        detector = FaceDetector()
        result = detector._ensure_model()
        assert result is mock_path
        mock_urlretrieve.assert_not_called()


class TestMediaPipeInitFailures:
    """Tests for MediaPipe initialization failure handling."""

    @patch("agents.hapax_daimonion.face_detector._MODEL_PATH")
    def test_mediapipe_import_failure(self, mock_path):
        """ImportError on mediapipe → detector stays None, detect returns FaceResult(False, 0)."""
        mock_path.exists.return_value = True

        detector = FaceDetector()

        with patch.dict("sys.modules", {"mediapipe": None}):
            result = detector._get_detector()
            assert result is None
            assert detector._detector is None

            detect_result = detector.detect(np.zeros((240, 320, 3), dtype=np.uint8))
            assert detect_result.detected is False
            assert detect_result.count == 0

    @patch("agents.hapax_daimonion.face_detector._MODEL_PATH")
    def test_mediapipe_init_failure(self, mock_path):
        """MediaPipe available but create_from_options raises RuntimeError → detector stays None."""
        mock_path.exists.return_value = True

        mock_mp = MagicMock()
        mock_mp.tasks.vision.FaceDetector.create_from_options.side_effect = RuntimeError(
            "Failed to initialize"
        )

        detector = FaceDetector()

        with patch.dict("sys.modules", {"mediapipe": mock_mp}):
            result = detector._get_detector()
            assert result is None
            assert detector._detector is None


class TestBase64Decoding:
    """Tests for base64 input edge cases."""

    def test_detect_corrupted_base64(self):
        """Invalid base64 string → FaceResult(False, 0)."""
        detector = FaceDetector()
        result = detector.detect_from_base64("!!!not-valid-base64!!!")
        assert result.detected is False
        assert result.count == 0

    def test_detect_valid_base64_not_image(self):
        """Base64 of plain text (not an image) → cv2.imdecode returns None → FaceResult(False, 0)."""
        import base64 as b64mod

        plain_text = b"This is definitely not an image file."
        encoded = b64mod.b64encode(plain_text).decode("ascii")

        detector = FaceDetector()
        result = detector.detect_from_base64(encoded)
        assert result.detected is False
        assert result.count == 0


class TestNormalizeColor:
    """Tests for _normalize_color edge cases."""

    def test_normalize_color_all_black(self):
        """All-zero image (overall < 1.0) → returned unchanged, no crash."""
        from agents.hapax_daimonion.face_detector import _normalize_color

        black = np.zeros((100, 100, 3), dtype=np.uint8)
        result = _normalize_color(black)
        np.testing.assert_array_equal(result, black)

    def test_normalize_color_all_white(self):
        """All-255 image → normalization is near-identity (scale ≈ 1.0 per channel)."""
        from agents.hapax_daimonion.face_detector import _normalize_color

        white = np.full((100, 100, 3), 255, dtype=np.uint8)
        result = _normalize_color(white)
        # All channels equal → scale = 1.0 for each → output ≈ input
        np.testing.assert_array_equal(result, white)

    def test_normalize_color_single_channel_dominant(self):
        """Red-tinted image → output should be more balanced across channels."""
        from agents.hapax_daimonion.face_detector import _normalize_color

        # BGR format: high blue channel value = 20, green = 20, red = 200
        red_tinted = np.zeros((100, 100, 3), dtype=np.uint8)
        red_tinted[:, :, 0] = 20  # B
        red_tinted[:, :, 1] = 20  # G
        red_tinted[:, :, 2] = 200  # R

        result = _normalize_color(red_tinted)

        # After normalization, B and G channels should be boosted toward the mean
        avg_before = red_tinted.mean(axis=(0, 1))
        avg_after = result.mean(axis=(0, 1))
        # The spread between channels should be reduced
        spread_before = avg_before.max() - avg_before.min()
        spread_after = avg_after.max() - avg_after.min()
        assert spread_after < spread_before


class TestDetectorEdgeCases:
    """Tests for detector edge cases and caching behavior."""

    def test_detect_with_zero_size_image(self):
        """Zero-size image array → FaceResult(False, 0)."""
        detector = FaceDetector()
        empty = np.array([], dtype=np.uint8).reshape(0, 0, 3)
        result = detector.detect(empty)
        assert result.detected is False
        assert result.count == 0

    @patch("agents.hapax_daimonion.face_detector._MODEL_PATH")
    def test_detector_caches_after_init(self, mock_path):
        """_get_detector() called twice → MediaPipe init happens only once."""
        mock_path.exists.return_value = True

        mock_mp = MagicMock()
        mock_detector_instance = MagicMock()
        mock_mp.tasks.vision.FaceDetector.create_from_options.return_value = mock_detector_instance

        detector = FaceDetector()

        with patch.dict("sys.modules", {"mediapipe": mock_mp}):
            first = detector._get_detector()
            second = detector._get_detector()

        assert first is mock_detector_instance
        assert second is mock_detector_instance
        mock_mp.tasks.vision.FaceDetector.create_from_options.assert_called_once()

    @patch("agents.hapax_daimonion.face_detector._MODEL_PATH")
    def test_detector_stays_none_after_failed_init(self, mock_path):
        """After failed init, _get_detector() should retry since self._detector is still None."""
        mock_path.exists.return_value = True

        mock_mp = MagicMock()
        mock_mp.tasks.vision.FaceDetector.create_from_options.side_effect = RuntimeError(
            "Init failed"
        )

        detector = FaceDetector()

        with patch.dict("sys.modules", {"mediapipe": mock_mp}):
            first = detector._get_detector()
            second = detector._get_detector()

        assert first is None
        assert second is None
        # Should have tried twice since _detector stays None
        assert mock_mp.tasks.vision.FaceDetector.create_from_options.call_count == 2
