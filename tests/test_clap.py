"""Tests for shared/clap.py — CLAP embedding and zero-shot classification.

All tests mock the CLAP model — no GPU or model download required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np


def _mock_clap_model(embed_dim=512):
    """Create a mock CLAP model that returns correct-shaped embeddings."""
    model = MagicMock()
    model.get_audio_embedding_from_data.return_value = np.random.randn(1, embed_dim).astype(
        np.float32
    )
    model.get_text_embedding.return_value = np.random.randn(1, embed_dim).astype(np.float32)
    return model


def test_embed_audio_returns_correct_dimensions():
    """embed_audio() returns a 512-dim vector."""
    from shared.clap import CLAP_EMBED_DIM, CLAP_SAMPLE_RATE

    mock_model = _mock_clap_model()

    with patch("shared.clap._get_model", return_value=mock_model):
        from shared.clap import embed_audio

        waveform = np.random.randn(CLAP_SAMPLE_RATE * 5).astype(np.float32)
        result = embed_audio(waveform, sr=CLAP_SAMPLE_RATE)

    assert result.shape == (CLAP_EMBED_DIM,)
    assert result.dtype == np.float32


def test_embed_text_returns_correct_dimensions():
    """embed_text() returns a 512-dim vector."""
    from shared.clap import CLAP_EMBED_DIM

    mock_model = _mock_clap_model()

    with patch("shared.clap._get_model", return_value=mock_model):
        from shared.clap import embed_text

        result = embed_text("jazzy piano loop with brass stabs")

    assert result.shape == (CLAP_EMBED_DIM,)
    mock_model.get_text_embedding.assert_called_once()


def test_classify_zero_shot_returns_probabilities():
    """classify_zero_shot() returns a dict with probabilities summing to 1.0."""
    from shared.clap import CLAP_SAMPLE_RATE

    mock_model = _mock_clap_model()
    # Make text embeddings different for each label
    call_count = 0

    def varying_text_emb(texts, **kwargs):
        nonlocal call_count
        call_count += 1
        np.random.seed(call_count)
        return np.random.randn(1, 512).astype(np.float32)

    mock_model.get_text_embedding.side_effect = varying_text_emb

    with patch("shared.clap._get_model", return_value=mock_model):
        from shared.clap import classify_zero_shot

        waveform = np.random.randn(CLAP_SAMPLE_RATE * 3).astype(np.float32)
        labels = ["hip hop beat", "jazz piano", "ambient noise", "speech"]
        result = classify_zero_shot(waveform, labels, sr=CLAP_SAMPLE_RATE)

    assert set(result.keys()) == set(labels)
    assert abs(sum(result.values()) - 1.0) < 1e-6
    assert all(0.0 <= v <= 1.0 for v in result.values())


def test_chunking_short_audio():
    """Audio shorter than CHUNK_SECONDS is padded to chunk length."""
    from shared.clap import CLAP_SAMPLE_RATE, _chunk_waveform

    short_audio = np.random.randn(CLAP_SAMPLE_RATE * 3).astype(np.float32)
    chunks = _chunk_waveform(short_audio, CLAP_SAMPLE_RATE)

    assert len(chunks) == 1
    assert len(chunks[0]) == int(10.0 * CLAP_SAMPLE_RATE)


def test_chunking_long_audio():
    """Audio longer than CHUNK_SECONDS is split into overlapping chunks."""
    from shared.clap import CHUNK_SECONDS, CLAP_SAMPLE_RATE, _chunk_waveform

    # 25 seconds of audio → chunks at 0, 5, 10, 15, 20 = 5 chunks
    long_audio = np.random.randn(CLAP_SAMPLE_RATE * 25).astype(np.float32)
    chunks = _chunk_waveform(long_audio, CLAP_SAMPLE_RATE)

    chunk_samples = int(CHUNK_SECONDS * CLAP_SAMPLE_RATE)
    assert len(chunks) == 5
    for chunk in chunks:
        assert len(chunk) == chunk_samples


def test_embed_audio_mean_pools_chunks():
    """Long audio is chunked and embeddings are mean-pooled."""
    from shared.clap import CLAP_EMBED_DIM, CLAP_SAMPLE_RATE

    call_count = 0

    def mock_audio_embed(x, use_tensor=False):
        nonlocal call_count
        call_count += 1
        return np.ones((1, CLAP_EMBED_DIM), dtype=np.float32) * call_count

    mock_model = _mock_clap_model()
    mock_model.get_audio_embedding_from_data.side_effect = mock_audio_embed

    with patch("shared.clap._get_model", return_value=mock_model):
        from shared.clap import embed_audio

        # 25s audio → 5 chunks (starts at 0, 5, 10, 15, 20)
        waveform = np.random.randn(CLAP_SAMPLE_RATE * 25).astype(np.float32)
        result = embed_audio(waveform, sr=CLAP_SAMPLE_RATE)

    assert call_count == 5
    # Mean of [1, 2, 3, 4, 5] = 3.0
    assert abs(result[0] - 3.0) < 1e-6
    assert result.shape == (CLAP_EMBED_DIM,)


def test_embed_audio_wrong_dimensions_raises():
    """RuntimeError if model returns wrong dimension count."""
    from shared.clap import CLAP_SAMPLE_RATE

    mock_model = _mock_clap_model(embed_dim=256)  # Wrong dims

    with patch("shared.clap._get_model", return_value=mock_model):
        from shared.clap import embed_audio

        waveform = np.random.randn(CLAP_SAMPLE_RATE * 5).astype(np.float32)
        try:
            embed_audio(waveform, sr=CLAP_SAMPLE_RATE)
            raise AssertionError("Should have raised RuntimeError")
        except RuntimeError as exc:
            assert "512" in str(exc)
