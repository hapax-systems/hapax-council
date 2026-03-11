"""Tests for hapax_voice speaker identification."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

import agents.hapax_voice.speaker_id as speaker_id_mod
from agents.hapax_voice.speaker_id import (
    SpeakerIdentifier,
    SpeakerResult,
    _cosine_similarity,
)


def test_no_enrollment_returns_uncertain() -> None:
    ident = SpeakerIdentifier(enrollment_path=None)
    embedding = np.random.randn(192).astype(np.float32)
    result = ident.identify(embedding)
    assert result.label == "uncertain"


def test_high_similarity_returns_ryan(tmp_path) -> None:
    enrollment = np.random.randn(192).astype(np.float32)
    save_path = tmp_path / "ryan.npy"
    ident = SpeakerIdentifier(enrollment_path=None)
    ident.enroll(enrollment, save_path)

    # Reload from file
    ident2 = SpeakerIdentifier(enrollment_path=save_path)
    # Use the same embedding — cosine similarity should be 1.0
    result = ident2.identify(enrollment)
    assert result.label == "ryan"
    assert result.confidence >= 0.75


def test_low_similarity_returns_not_ryan(tmp_path) -> None:
    enrollment = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    save_path = tmp_path / "ryan.npy"
    ident = SpeakerIdentifier(enrollment_path=None)
    ident.enroll(enrollment, save_path)

    ident2 = SpeakerIdentifier(enrollment_path=save_path)
    # Orthogonal vector — cosine similarity near 0
    other = np.array([0.0, 0.0, 1.0, 0.0], dtype=np.float32)
    result = ident2.identify(other)
    assert result.label == "not_ryan"
    assert result.confidence < 0.4


def test_cosine_similarity_math() -> None:
    a = np.array([1.0, 0.0, 0.0])
    b = np.array([1.0, 0.0, 0.0])
    assert abs(_cosine_similarity(a, b) - 1.0) < 1e-6

    c = np.array([0.0, 1.0, 0.0])
    assert abs(_cosine_similarity(a, c)) < 1e-6

    d = np.array([-1.0, 0.0, 0.0])
    assert abs(_cosine_similarity(a, d) - (-1.0)) < 1e-6


def _reset_pyannote_state():
    """Reset the module-level lazy-load state between tests."""
    speaker_id_mod._pyannote_inference = None
    speaker_id_mod._pyannote_load_attempted = False


def test_extract_embedding_no_hf_token(monkeypatch) -> None:
    _reset_pyannote_state()
    monkeypatch.delenv("HF_TOKEN", raising=False)
    ident = SpeakerIdentifier(enrollment_path=None)
    audio = np.random.randn(16000).astype(np.float32)
    result = ident.extract_embedding(audio)
    assert result is None
    _reset_pyannote_state()


def test_extract_embedding_with_mocked_inference() -> None:
    """extract_embedding returns embedding when pyannote inference is available."""
    _reset_pyannote_state()

    fake_embedding = np.random.randn(192).astype(np.float32)
    mock_inference = MagicMock(side_effect=lambda x: fake_embedding)
    speaker_id_mod._pyannote_inference = mock_inference
    speaker_id_mod._pyannote_load_attempted = True

    ident = SpeakerIdentifier(enrollment_path=None)
    audio = np.random.randn(16000).astype(np.float32)
    result = ident.extract_embedding(audio)

    assert result is not None
    np.testing.assert_array_equal(result, fake_embedding)
    # Verify inference was called with correct structure
    call_args = mock_inference.call_args[0][0]
    assert "waveform" in call_args
    assert call_args["sample_rate"] == 16000
    _reset_pyannote_state()


def test_extract_embedding_converts_int16() -> None:
    """Verify int16 audio is converted to float32 before processing."""
    _reset_pyannote_state()
    # Pre-set inference to a mock so we can inspect the call
    fake_embedding = np.random.randn(192).astype(np.float32)
    mock_inference = MagicMock(side_effect=lambda x: fake_embedding)
    speaker_id_mod._pyannote_inference = mock_inference
    speaker_id_mod._pyannote_load_attempted = True

    ident = SpeakerIdentifier(enrollment_path=None)
    audio_int16 = (np.random.randn(16000) * 32767).astype(np.int16)
    result = ident.extract_embedding(audio_int16)

    assert result is not None
    # Check that the waveform passed is float32 (torch tensor or numpy)
    call_args = mock_inference.call_args[0][0]
    waveform = call_args["waveform"]
    if hasattr(waveform, "is_floating_point"):
        # torch Tensor
        assert waveform.is_floating_point()
    else:
        # numpy fallback
        assert waveform.dtype == np.float32
    assert call_args["sample_rate"] == 16000
    _reset_pyannote_state()


def test_identify_audio_with_enrollment(tmp_path) -> None:
    """End-to-end: identify_audio returns ryan when embedding matches."""
    _reset_pyannote_state()

    enrollment = np.random.randn(192).astype(np.float32)
    enrollment = enrollment / np.linalg.norm(enrollment)

    # Mock pyannote to return the enrollment embedding (perfect match)
    mock_inference = MagicMock(side_effect=lambda x: enrollment.copy())
    speaker_id_mod._pyannote_inference = mock_inference
    speaker_id_mod._pyannote_load_attempted = True

    save_path = tmp_path / "ryan.npy"
    ident = SpeakerIdentifier(enrollment_path=None)
    ident.enroll(enrollment, save_path)

    audio = np.random.randn(16000).astype(np.float32)
    result = ident.identify_audio(audio)
    assert result.label == "ryan"
    assert result.confidence >= 0.75
    _reset_pyannote_state()


def test_identify_audio_no_model() -> None:
    """identify_audio returns uncertain when pyannote model unavailable."""
    _reset_pyannote_state()
    speaker_id_mod._pyannote_inference = None
    speaker_id_mod._pyannote_load_attempted = True

    ident = SpeakerIdentifier(enrollment_path=None)
    audio = np.random.randn(16000).astype(np.float32)
    result = ident.identify_audio(audio)
    assert result.label == "uncertain"
    assert result.confidence == 0.0
    _reset_pyannote_state()
