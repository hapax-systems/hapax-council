"""Tests for shared/hsemotion.py — HSEmotion facial expression analysis."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from shared.hsemotion import EMOTION_LABELS, EmotionResult, analyze_face, analyze_frame, available


def test_emotion_labels_count():
    assert len(EMOTION_LABELS) == 8


def test_emotion_result_frozen():
    result = EmotionResult(
        top_emotion="happy",
        emotion_scores={"happy": 0.8, "neutral": 0.2},
        valence=0.5,
        arousal=0.6,
    )
    assert result.top_emotion == "happy"
    assert result.valence == 0.5


def test_available_when_installed():
    with patch.dict("sys.modules", {"hsemotion_onnx": MagicMock()}):
        assert available() is True


def test_available_when_not_installed():
    import sys

    with patch.dict(sys.modules, {"hsemotion_onnx": None}):
        # Force ImportError
        assert available() is False


def test_analyze_face():
    mock_model = MagicMock()
    scores = np.array([0.1, 0.05, 0.05, 0.05, 0.6, 0.1, 0.03, 0.02])
    mock_model.predict_emotions.return_value = ("happy", scores)
    mock_model.last_valence = 0.7
    mock_model.last_arousal = 0.5

    face = np.random.randint(0, 255, (224, 224, 3), dtype=np.uint8)

    with patch("shared.hsemotion._get_model", return_value=mock_model):
        result = analyze_face(face)

    assert result.top_emotion == "happy"
    assert result.emotion_scores["happy"] == 0.6
    assert result.valence == 0.7
    assert result.arousal == 0.5


def test_analyze_frame_with_boxes():
    mock_model = MagicMock()
    scores = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.9, 0.05, 0.05])
    mock_model.predict_emotions.return_value = ("neutral", scores)
    mock_model.last_valence = 0.0
    mock_model.last_arousal = 0.1

    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    boxes = [(100, 100, 200, 200), (300, 100, 400, 200)]

    with patch("shared.hsemotion._get_model", return_value=mock_model):
        results = analyze_frame(frame, face_boxes=boxes)

    assert len(results) == 2
    assert all(r.top_emotion == "neutral" for r in results)


def test_analyze_frame_no_boxes():
    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    results = analyze_frame(frame, face_boxes=None)
    assert results == []


def test_analyze_frame_invalid_box():
    mock_model = MagicMock()
    scores = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.9, 0.05, 0.05])
    mock_model.predict_emotions.return_value = ("neutral", scores)
    mock_model.last_valence = 0.0
    mock_model.last_arousal = 0.1

    frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
    # Invalid box: x2 < x1
    boxes = [(200, 100, 100, 200)]

    with patch("shared.hsemotion._get_model", return_value=mock_model):
        results = analyze_frame(frame, face_boxes=boxes)

    assert len(results) == 0
