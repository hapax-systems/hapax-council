"""Tests for hapax_voice ambient audio classifier."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agents.hapax_voice import ambient_classifier
from agents.hapax_voice.ambient_classifier import (
    PANNS_SAMPLE_RATE,
    _build_label_index,
    classify,
    reset,
)


@pytest.fixture(autouse=True)
def _reset_model_state():
    """Reset the lazy-loaded model state before and after each test."""
    reset()
    yield
    reset()


# ---------------------------------------------------------------------------
# Label index tests
# ---------------------------------------------------------------------------


def test_build_label_index_finds_block_labels() -> None:
    labels = ["Music", "Silence", "Speech", "Dog bark", "Guitar"]
    block_idx, allow_idx = _build_label_index(labels)
    assert 0 in block_idx  # Music
    assert 2 in block_idx  # Speech
    assert 4 in block_idx  # Guitar
    assert 3 not in block_idx  # Dog bark


def test_build_label_index_finds_allow_labels() -> None:
    labels = ["Music", "Silence", "Typing", "Dog bark"]
    block_idx, allow_idx = _build_label_index(labels)
    assert 1 in allow_idx  # Silence
    assert 2 in allow_idx  # Typing
    assert 0 not in allow_idx  # Music


def test_build_label_index_case_insensitive() -> None:
    labels = ["music", "SPEECH", "Keyboard (Musical)"]
    block_idx, _ = _build_label_index(labels)
    assert 0 in block_idx
    assert 1 in block_idx
    # "Keyboard (Musical)" contains "Musical instrument" substring? No, but it contains "Music"
    # Actually it doesn't match "Musical instrument" but it matches via substring of "Music"
    assert 2 in block_idx


# ---------------------------------------------------------------------------
# Classification tests with mocked model
# ---------------------------------------------------------------------------


def _make_fake_labels() -> list[str]:
    """Create a minimal set of labels for testing."""
    return [
        "Speech",  # 0 - block
        "Music",  # 1 - block
        "Silence",  # 2 - allow
        "Dog bark",  # 3 - neutral
        "Typing",  # 4 - allow
        "Guitar",  # 5 - block
        "Car horn",  # 6 - neutral
        "Singing",  # 7 - block
        "White noise",  # 8 - allow
        "Conversation",  # 9 - block
    ]


def _mock_model_with_probs(probs: np.ndarray) -> MagicMock:
    """Create a mock PANNs model that returns given probabilities."""
    model = MagicMock()
    model.inference.return_value = (probs[np.newaxis, :], None)
    return model


def test_classify_blocks_on_music() -> None:
    """Classifies as non-interruptible when music probability is high."""
    labels = _make_fake_labels()
    probs = np.zeros(len(labels), dtype=np.float32)
    probs[1] = 0.8  # Music

    with (
        patch.object(ambient_classifier, "_model", _mock_model_with_probs(probs)),
        patch.object(ambient_classifier, "_labels", labels),
        patch.object(ambient_classifier, "_load_attempted", True),
    ):
        audio = np.zeros(PANNS_SAMPLE_RATE * 3, dtype=np.float32)
        result = classify(audio=audio)

    assert not result.interruptible
    assert "Music" in result.reason


def test_classify_blocks_on_speech() -> None:
    """Classifies as non-interruptible when speech probability is high."""
    labels = _make_fake_labels()
    probs = np.zeros(len(labels), dtype=np.float32)
    probs[0] = 0.6  # Speech

    with (
        patch.object(ambient_classifier, "_model", _mock_model_with_probs(probs)),
        patch.object(ambient_classifier, "_labels", labels),
        patch.object(ambient_classifier, "_load_attempted", True),
    ):
        audio = np.zeros(PANNS_SAMPLE_RATE * 3, dtype=np.float32)
        result = classify(audio=audio)

    assert not result.interruptible
    assert "Speech" in result.reason


def test_classify_allows_silence() -> None:
    """Classifies as interruptible when only silence/typing detected."""
    labels = _make_fake_labels()
    probs = np.zeros(len(labels), dtype=np.float32)
    probs[2] = 0.9  # Silence
    probs[4] = 0.3  # Typing

    with (
        patch.object(ambient_classifier, "_model", _mock_model_with_probs(probs)),
        patch.object(ambient_classifier, "_labels", labels),
        patch.object(ambient_classifier, "_load_attempted", True),
    ):
        audio = np.zeros(PANNS_SAMPLE_RATE * 3, dtype=np.float32)
        result = classify(audio=audio)

    assert result.interruptible


def test_classify_blocks_combined_low_probs() -> None:
    """Blocks when individual block probs are low but sum exceeds threshold."""
    labels = _make_fake_labels()
    probs = np.zeros(len(labels), dtype=np.float32)
    probs[0] = 0.05  # Speech
    probs[1] = 0.05  # Music
    probs[5] = 0.03  # Guitar
    probs[7] = 0.03  # Singing
    # Total block = 0.16 > 0.15 threshold

    with (
        patch.object(ambient_classifier, "_model", _mock_model_with_probs(probs)),
        patch.object(ambient_classifier, "_labels", labels),
        patch.object(ambient_classifier, "_load_attempted", True),
    ):
        audio = np.zeros(PANNS_SAMPLE_RATE * 3, dtype=np.float32)
        result = classify(audio=audio)

    assert not result.interruptible


def test_classify_allows_below_threshold() -> None:
    """Allows when block probs sum is below threshold."""
    labels = _make_fake_labels()
    probs = np.zeros(len(labels), dtype=np.float32)
    probs[0] = 0.03  # Speech
    probs[1] = 0.02  # Music
    probs[2] = 0.8  # Silence
    # Total block < 0.15

    with (
        patch.object(ambient_classifier, "_model", _mock_model_with_probs(probs)),
        patch.object(ambient_classifier, "_labels", labels),
        patch.object(ambient_classifier, "_load_attempted", True),
    ):
        audio = np.zeros(PANNS_SAMPLE_RATE * 3, dtype=np.float32)
        result = classify(audio=audio)

    assert result.interruptible


def test_classify_returns_top_labels() -> None:
    """Verify top_labels are populated in the result."""
    labels = _make_fake_labels()
    probs = np.zeros(len(labels), dtype=np.float32)
    probs[2] = 0.9  # Silence
    probs[4] = 0.3  # Typing

    with (
        patch.object(ambient_classifier, "_model", _mock_model_with_probs(probs)),
        patch.object(ambient_classifier, "_labels", labels),
        patch.object(ambient_classifier, "_load_attempted", True),
    ):
        audio = np.zeros(PANNS_SAMPLE_RATE * 3, dtype=np.float32)
        result = classify(audio=audio)

    assert len(result.top_labels) > 0
    # Top label should be Silence
    assert result.top_labels[0][0] == "Silence"


# ---------------------------------------------------------------------------
# Fail-closed behaviour
# ---------------------------------------------------------------------------


def test_classify_fail_closed_no_model() -> None:
    """Blocks when the model fails to load (fail-closed)."""
    with (
        patch.object(ambient_classifier, "_model", None),
        patch.object(ambient_classifier, "_load_attempted", True),
    ):
        result = classify(audio=np.zeros(PANNS_SAMPLE_RATE * 3, dtype=np.float32))

    assert not result.interruptible
    assert "unavailable" in result.reason.lower()


def test_classify_fail_closed_import_error() -> None:
    """Blocks when panns_inference is not installed (fail-closed)."""
    # reset() already called by fixture, so _load_attempted is False
    with patch.dict("sys.modules", {"panns_inference": None}):
        # _load_model will try to import and fail
        result = classify(audio=np.zeros(PANNS_SAMPLE_RATE * 3, dtype=np.float32))

    assert not result.interruptible
    assert "unavailable" in result.reason.lower()


def test_classify_fail_closed_inference_error() -> None:
    """Blocks when PANNs inference raises an exception."""
    labels = _make_fake_labels()
    model = MagicMock()
    model.inference.side_effect = RuntimeError("ONNX error")

    with (
        patch.object(ambient_classifier, "_model", model),
        patch.object(ambient_classifier, "_labels", labels),
        patch.object(ambient_classifier, "_load_attempted", True),
    ):
        audio = np.zeros(PANNS_SAMPLE_RATE * 3, dtype=np.float32)
        result = classify(audio=audio)

    assert not result.interruptible
    assert "fail-closed" in result.reason.lower()


def test_classify_fail_closed_no_audio() -> None:
    """Blocks when audio capture returns None (fail-closed)."""
    labels = _make_fake_labels()
    model = MagicMock()

    with (
        patch.object(ambient_classifier, "_model", model),
        patch.object(ambient_classifier, "_labels", labels),
        patch.object(ambient_classifier, "_load_attempted", True),
        patch("agents.hapax_voice.ambient_classifier._capture_audio_pipewire", return_value=None),
    ):
        # Call without audio= so it tries to capture
        result = classify()

    assert not result.interruptible
    assert "capture failed" in result.reason.lower()


# ---------------------------------------------------------------------------
# Audio input handling
# ---------------------------------------------------------------------------


def test_classify_accepts_1d_audio() -> None:
    """1D audio arrays are reshaped to (1, samples) for PANNs."""
    labels = _make_fake_labels()
    probs = np.zeros(len(labels), dtype=np.float32)
    probs[2] = 0.9  # Silence

    model = MagicMock()
    model.inference.return_value = (probs[np.newaxis, :], None)

    with (
        patch.object(ambient_classifier, "_model", model),
        patch.object(ambient_classifier, "_labels", labels),
        patch.object(ambient_classifier, "_load_attempted", True),
    ):
        audio = np.zeros(PANNS_SAMPLE_RATE * 3, dtype=np.float32)
        classify(audio=audio)

    # Verify inference was called with 2D array
    call_args = model.inference.call_args[0][0]
    assert call_args.ndim == 2
    assert call_args.shape[0] == 1
