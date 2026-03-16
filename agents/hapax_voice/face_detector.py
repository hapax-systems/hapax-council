"""Lightweight face detection using MediaPipe BlazeFace (CPU-only)."""

from __future__ import annotations

import base64
import logging
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

_MODEL_DIR = Path.home() / ".local" / "share" / "hapax-voice"
_MODEL_PATH = _MODEL_DIR / "blaze_face_short_range.tflite"
_MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"


@dataclass(frozen=True)
class FaceResult:
    detected: bool
    count: int


def _normalize_color(image: np.ndarray) -> np.ndarray:
    """Gray world color normalization — delegates to shared.color_utils."""
    from shared.color_utils import normalize_color

    return normalize_color(image)


class FaceDetector:
    """Detects faces in images using MediaPipe BlazeFace.

    Runs entirely on CPU (<5ms per frame). No face recognition —
    only answers "is someone there?" and "how many?".
    """

    def __init__(self, min_confidence: float = 0.5) -> None:
        self._min_confidence = min_confidence
        self._detector = None

    def _ensure_model(self) -> Path | None:
        """Download BlazeFace model if not present."""
        if _MODEL_PATH.exists():
            return _MODEL_PATH
        try:
            _MODEL_DIR.mkdir(parents=True, exist_ok=True)
            log.info("Downloading BlazeFace model...")
            urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
            log.info("BlazeFace model downloaded to %s", _MODEL_PATH)
            return _MODEL_PATH
        except Exception as exc:
            log.warning("Failed to download BlazeFace model: %s", exc)
            return None

    def _get_detector(self):
        """Lazily initialize MediaPipe face detector."""
        if self._detector is None:
            try:
                model_path = self._ensure_model()
                if model_path is None:
                    return None
                import mediapipe as mp

                base_options = mp.tasks.BaseOptions(model_asset_path=str(model_path))
                options = mp.tasks.vision.FaceDetectorOptions(
                    base_options=base_options,
                    min_detection_confidence=self._min_confidence,
                )
                self._detector = mp.tasks.vision.FaceDetector.create_from_options(options)
            except Exception as exc:
                log.warning("Failed to initialize MediaPipe: %s", exc)
        return self._detector

    def detect(self, image: np.ndarray | None) -> FaceResult:
        """Detect faces in a numpy BGR image array.

        Returns FaceResult with detected=True if at least one face found.
        """
        if image is None or image.size == 0:
            return FaceResult(detected=False, count=0)

        detector = self._get_detector()
        if detector is None:
            return FaceResult(detected=False, count=0)

        try:
            import mediapipe as mp

            normalized = _normalize_color(image)
            rgb = cv2.cvtColor(normalized, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            results = detector.detect(mp_image)
            if results.detections:
                count = len(results.detections)
                return FaceResult(detected=True, count=count)
            return FaceResult(detected=False, count=0)
        except Exception as exc:
            log.debug("Face detection failed: %s", exc)
            return FaceResult(detected=False, count=0)

    def detect_from_base64(self, image_b64: str | None) -> FaceResult:
        """Detect faces from a base64-encoded JPEG/PNG image."""
        if not image_b64:
            return FaceResult(detected=False, count=0)
        try:
            raw = base64.b64decode(image_b64)
            arr = np.frombuffer(raw, dtype=np.uint8)
            image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if image is None:
                return FaceResult(detected=False, count=0)
            return self.detect(image)
        except Exception as exc:
            log.debug("Base64 face detection failed: %s", exc)
            return FaceResult(detected=False, count=0)
