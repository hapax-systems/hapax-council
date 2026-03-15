"""shared/hsemotion.py — HSEmotion facial expression analysis.

Wraps the HSEmotion ONNX model for 7-class emotion classification
with valence/arousal output. CPU-only (~50MB model, ~20ms per face).

Model: enet_b0_8_va_mtl (8 emotions + valence/arousal regression).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np  # noqa: TC002 — used at runtime

log = logging.getLogger(__name__)

# 7+1 emotion classes (8 total including "other")
EMOTION_LABELS = [
    "angry",
    "contempt",
    "disgust",
    "fear",
    "happy",
    "neutral",
    "sad",
    "surprise",
]

_model = None


@dataclass(frozen=True)
class EmotionResult:
    """Result from HSEmotion analysis of a single face crop."""

    top_emotion: str
    emotion_scores: dict[str, float]
    valence: float  # -1.0 (negative) to 1.0 (positive)
    arousal: float  # 0.0 (calm) to 1.0 (excited)


def _get_model():
    """Load the HSEmotion ONNX model on first call."""
    global _model
    if _model is not None:
        return _model

    from hsemotion_onnx import HSEmotionRecognizer

    log.info("Loading HSEmotion ONNX model")
    _model = HSEmotionRecognizer(model_name="enet_b0_8_va_mtl")
    log.info("HSEmotion model loaded")
    return _model


def available() -> bool:
    """Check if HSEmotion ONNX is importable."""
    try:
        import hsemotion_onnx  # noqa: F401

        return True
    except ImportError:
        return False


def analyze_face(face_crop: np.ndarray) -> EmotionResult:
    """Analyze emotion from a face crop (BGR numpy array).

    Args:
        face_crop: BGR image of a cropped face, any resolution
                   (will be resized internally by HSEmotion).

    Returns:
        EmotionResult with top emotion, scores, valence, and arousal.
    """
    from shared.color_utils import normalize_color

    model = _get_model()
    normalized = normalize_color(face_crop)

    emotion, scores = model.predict_emotions(normalized, logits=False)
    emotion_dict = dict(zip(EMOTION_LABELS, scores.tolist(), strict=True))

    # HSEmotion returns valence/arousal as additional outputs
    valence = float(getattr(model, "last_valence", 0.0))
    arousal = float(getattr(model, "last_arousal", 0.0))

    return EmotionResult(
        top_emotion=emotion,
        emotion_scores=emotion_dict,
        valence=valence,
        arousal=arousal,
    )


def analyze_frame(
    frame: np.ndarray,
    face_boxes: list[tuple[int, int, int, int]] | None = None,
) -> list[EmotionResult]:
    """Analyze emotions for all faces in a frame.

    Args:
        frame: Full BGR image.
        face_boxes: Optional list of (x1, y1, x2, y2) face bounding boxes.
                    If None, attempts to detect faces via FaceDetector.

    Returns:
        List of EmotionResult, one per detected face.
    """
    if face_boxes is None:
        return []

    results = []
    for x1, y1, x2, y2 in face_boxes:
        x1, y1 = max(0, x1), max(0, y1)
        x2 = min(frame.shape[1], x2)
        y2 = min(frame.shape[0], y2)
        if x2 <= x1 or y2 <= y1:
            continue
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        try:
            result = analyze_face(crop)
            results.append(result)
        except Exception as exc:
            log.debug("HSEmotion analysis failed for face at (%d,%d): %s", x1, y1, exc)

    return results
