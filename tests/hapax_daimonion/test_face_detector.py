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


class TestInsightFaceInitFailures:
    """Tests for InsightFace initialization failure handling."""

    def test_insightface_import_failure(self):
        """ImportError on insightface → _get_app returns None, detect returns FaceResult(False, 0)."""
        detector = FaceDetector()

        with patch.dict("sys.modules", {"insightface": None, "insightface.app": None}):
            result = detector._get_app()
            assert result is None
            assert detector._init_failed is True

            detect_result = detector.detect(np.zeros((240, 320, 3), dtype=np.uint8))
            assert detect_result.detected is False
            assert detect_result.count == 0

    def test_insightface_init_exception(self):
        """FaceAnalysis raises RuntimeError → _get_app returns None, _init_failed set."""
        mock_insight = MagicMock()
        mock_insight_app = MagicMock()
        mock_insight_app.FaceAnalysis.side_effect = RuntimeError("GPU not available")

        detector = FaceDetector()

        with patch.dict(
            "sys.modules",
            {"insightface": mock_insight, "insightface.app": mock_insight_app},
        ):
            result = detector._get_app()
            assert result is None
            assert detector._init_failed is True

    def test_detect_graceful_without_model(self):
        """When _get_app returns None, detect returns FaceResult(False, 0)."""
        detector = FaceDetector()
        detector._init_failed = True  # simulate failed init

        result = detector.detect(np.zeros((240, 320, 3), dtype=np.uint8))
        assert result.detected is False
        assert result.count == 0


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

    def test_detector_caches_after_init(self):
        """_get_app() called twice → InsightFace init happens only once."""
        mock_insight_app = MagicMock()
        mock_app_instance = MagicMock()
        mock_insight_app.FaceAnalysis.return_value = mock_app_instance

        detector = FaceDetector()

        with patch.dict(
            "sys.modules",
            {"insightface": MagicMock(), "insightface.app": mock_insight_app},
        ):
            first = detector._get_app()
            second = detector._get_app()

        assert first is mock_app_instance
        assert second is mock_app_instance
        mock_insight_app.FaceAnalysis.assert_called_once()

    def test_detector_stays_none_after_failed_init(self):
        """After failed init, _get_app() should not retry (_init_failed guards)."""
        mock_insight_app = MagicMock()
        mock_insight_app.FaceAnalysis.side_effect = RuntimeError("Init failed")

        detector = FaceDetector()

        with patch.dict(
            "sys.modules",
            {"insightface": MagicMock(), "insightface.app": mock_insight_app},
        ):
            first = detector._get_app()
            second = detector._get_app()

        assert first is None
        assert second is None
        # Should have tried only once since _init_failed is set
        mock_insight_app.FaceAnalysis.assert_called_once()
