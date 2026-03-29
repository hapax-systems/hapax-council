"""Hardware integration tests for hapax_daimonion.

These tests exercise real hardware and services. They are marked with
@pytest.mark.hardware and skip automatically when hardware isn't available
(see conftest.py pytest_collection_modifyitems).
"""

import pytest


@pytest.mark.hardware
class TestScreenCaptureHardware:
    """Tests that exercise real screen capture. Skip if no display."""

    @pytest.mark.xfail(reason="grim may timeout under GPU load", strict=False)
    def test_screen_capture_produces_valid_base64(self):
        """Capture actual screen and verify base64 is decodable."""
        from agents.hapax_daimonion.screen_capturer import ScreenCapturer

        capturer = ScreenCapturer(cooldown_s=0)
        result = capturer.capture()
        assert result is not None, "Screen capture returned None — is grim available?"
        # Verify it's valid base64 that decodes to PNG
        import base64

        data = base64.b64decode(result)
        assert data[:4] == b"\x89PNG", "Captured data is not PNG format"
        assert len(data) > 1000, "Captured PNG is suspiciously small"

    def test_screen_capture_respects_cooldown(self):
        """Two rapid captures — second should be None due to cooldown."""
        from agents.hapax_daimonion.screen_capturer import ScreenCapturer

        capturer = ScreenCapturer(cooldown_s=60)
        first = capturer.capture()
        second = capturer.capture()
        assert first is not None
        assert second is None


@pytest.mark.hardware
class TestWebcamCaptureHardware:
    """Tests that exercise real webcam capture via ffmpeg."""

    @pytest.mark.xfail(reason="Camera may be in use by studio compositor", strict=False)
    def test_webcam_capture_produces_valid_base64(self):
        """Capture frame from first available camera."""
        import glob

        from agents.hapax_daimonion.screen_models import CameraConfig
        from agents.hapax_daimonion.webcam_capturer import WebcamCapturer

        # Find first video device
        devices = sorted(glob.glob("/dev/video*"))
        if not devices:
            pytest.skip("No video devices found")

        cam = CameraConfig(
            role="test", device=devices[0], width=640, height=480, input_format="mjpeg"
        )
        capturer = WebcamCapturer(cameras=[cam], cooldown_s=0)
        result = capturer.capture("test")
        assert result is not None, f"Webcam capture returned None for {devices[0]}"

        import base64

        data = base64.b64decode(result)
        # JPEG starts with FF D8
        assert data[:2] == b"\xff\xd8", "Captured data is not JPEG format"
        assert len(data) > 500, "Captured JPEG is suspiciously small"


@pytest.mark.hardware
class TestFaceDetectorHardware:
    """Tests that exercise real MediaPipe face detection."""

    def test_face_detector_with_synthetic_image(self):
        """Run face detector on a blank image — should detect 0 faces."""
        import numpy as np

        from agents.hapax_daimonion.face_detector import FaceDetector

        detector = FaceDetector(min_confidence=0.5)
        blank = np.zeros((480, 640, 3), dtype=np.uint8)
        result = detector.detect(blank)
        assert result.detected is False
        assert result.count == 0

    def test_face_detector_insightface_init(self):
        """Verify InsightFace model can be loaded (downloads if needed)."""
        from agents.hapax_daimonion.face_detector import FaceDetector

        detector = FaceDetector(min_confidence=0.5)
        # _get_app should initialize InsightFace or set _init_failed
        app = detector._get_app()
        if app is None:
            # InsightFace not installed or init failed — acceptable in test env
            assert detector._init_failed is True
        else:
            assert detector._app is app

    def test_face_detector_with_webcam_frame(self):
        """Capture from webcam and run face detection (may or may not find faces)."""
        import glob

        from agents.hapax_daimonion.face_detector import FaceDetector
        from agents.hapax_daimonion.screen_models import CameraConfig
        from agents.hapax_daimonion.webcam_capturer import WebcamCapturer

        devices = sorted(glob.glob("/dev/video*"))
        if not devices:
            pytest.skip("No video devices found")

        cam = CameraConfig(
            role="test", device=devices[0], width=640, height=480, input_format="mjpeg"
        )
        capturer = WebcamCapturer(cameras=[cam], cooldown_s=0)
        frame_b64 = capturer.capture("test")
        if frame_b64 is None:
            pytest.skip("Could not capture frame from webcam")

        detector = FaceDetector(min_confidence=0.3)
        result = detector.detect_from_base64(frame_b64)
        # Don't assert detection — just verify no crash and valid result type
        assert isinstance(result.detected, bool)
        assert isinstance(result.count, int)
        assert result.count >= 0
