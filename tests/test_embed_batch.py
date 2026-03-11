"""Tests for shared/config.py:embed_batch() — batch embedding helper."""
from unittest.mock import patch, MagicMock

import pytest

from shared.config import embed_batch, EMBEDDING_MODEL, EXPECTED_EMBED_DIMENSIONS

# Helper: valid 768-dim vector
_VEC = [0.1] * EXPECTED_EMBED_DIMENSIONS


def _mock_client(return_value=None, side_effect=None):
    """Create a mock ollama.Client whose .embed() is configured."""
    client = MagicMock()
    if side_effect is not None:
        client.embed.side_effect = side_effect
    elif return_value is not None:
        client.embed.return_value = return_value
    return client


def test_empty_input_returns_empty_list():
    """embed_batch([]) should return [] without calling Ollama."""
    mc = _mock_client(return_value={"embeddings": []})
    with patch("shared.config._get_ollama_client", return_value=mc):
        result = embed_batch([])
        assert result == []
        mc.embed.assert_not_called()


def test_single_text_returns_one_embedding():
    """embed_batch with one text returns a list with one embedding."""
    mc = _mock_client(return_value={"embeddings": [_VEC]})
    with patch("shared.config._get_ollama_client", return_value=mc):
        result = embed_batch(["hello world"])
        assert len(result) == 1
        assert len(result[0]) == EXPECTED_EMBED_DIMENSIONS
        mc.embed.assert_called_once()


def test_batch_returns_correct_count():
    """embed_batch with N texts returns N embeddings."""
    texts = ["one", "two", "three"]
    fake_embeddings = [[0.1] * 768, [0.2] * 768, [0.3] * 768]
    mc = _mock_client(return_value={"embeddings": fake_embeddings})
    with patch("shared.config._get_ollama_client", return_value=mc):
        result = embed_batch(texts)
        assert len(result) == 3


def test_prefix_application():
    """embed_batch applies prefix to each text."""
    mc = _mock_client(return_value={"embeddings": [_VEC]})
    with patch("shared.config._get_ollama_client", return_value=mc):
        embed_batch(["test"], prefix="search_document")
        call_kwargs = mc.embed.call_args[1]
        assert call_kwargs["input"] == ["search_document: test"]


def test_custom_prefix():
    """embed_batch applies custom prefix."""
    mc = _mock_client(return_value={"embeddings": [_VEC, _VEC]})
    with patch("shared.config._get_ollama_client", return_value=mc):
        embed_batch(["a", "b"], prefix="search_query")
        call_kwargs = mc.embed.call_args[1]
        assert call_kwargs["input"] == ["search_query: a", "search_query: b"]


def test_empty_prefix():
    """embed_batch with empty prefix passes raw text."""
    mc = _mock_client(return_value={"embeddings": [_VEC]})
    with patch("shared.config._get_ollama_client", return_value=mc):
        embed_batch(["test"], prefix="")
        call_kwargs = mc.embed.call_args[1]
        assert call_kwargs["input"] == ["test"]


def test_default_model():
    """embed_batch uses EMBEDDING_MODEL by default."""
    mc = _mock_client(return_value={"embeddings": [_VEC]})
    with patch("shared.config._get_ollama_client", return_value=mc):
        embed_batch(["test"])
        call_kwargs = mc.embed.call_args[1]
        assert call_kwargs["model"] == EMBEDDING_MODEL


def test_custom_model():
    """embed_batch uses custom model when specified."""
    mc = _mock_client(return_value={"embeddings": [_VEC]})
    with patch("shared.config._get_ollama_client", return_value=mc):
        embed_batch(["test"], model="custom-model")
        call_kwargs = mc.embed.call_args[1]
        assert call_kwargs["model"] == "custom-model"


def test_singleton_client_reused():
    """embed_batch reuses the singleton client across calls."""
    mc = _mock_client(return_value={"embeddings": [_VEC]})
    with patch("shared.config._get_ollama_client", return_value=mc):
        embed_batch(["test1"])
        embed_batch(["test2"])
        assert mc.embed.call_count == 2


def test_error_wrapping():
    """embed_batch wraps Ollama errors in RuntimeError."""
    mc = _mock_client(side_effect=ConnectionError("Ollama is down"))
    with patch("shared.config._get_ollama_client", return_value=mc):
        with pytest.raises(RuntimeError, match="Batch embedding failed"):
            embed_batch(["test"])


def test_error_preserves_cause():
    """embed_batch RuntimeError should chain to the original exception."""
    orig = ConnectionError("Ollama is down")
    mc = _mock_client(side_effect=orig)
    with patch("shared.config._get_ollama_client", return_value=mc):
        with pytest.raises(RuntimeError) as exc_info:
            embed_batch(["test"])
        assert exc_info.value.__cause__ is orig


def test_default_prefix_is_search_document():
    """embed_batch default prefix should be 'search_document'."""
    mc = _mock_client(return_value={"embeddings": [_VEC]})
    with patch("shared.config._get_ollama_client", return_value=mc):
        embed_batch(["test"])
        call_kwargs = mc.embed.call_args[1]
        assert call_kwargs["input"] == ["search_document: test"]


def test_dimension_validation_rejects_wrong_size():
    """embed_batch rejects vectors with wrong dimensions."""
    wrong_dim = [[0.1] * 512]  # 512 instead of 768
    mc = _mock_client(return_value={"embeddings": wrong_dim})
    with patch("shared.config._get_ollama_client", return_value=mc):
        with pytest.raises(RuntimeError, match="Expected 768-dim embedding at index 0, got 512"):
            embed_batch(["test"])


def test_dimension_validation_catches_mixed_dimensions():
    """embed_batch catches wrong dimensions even in middle of batch."""
    mixed = [[0.1] * 768, [0.2] * 512]  # Second vector wrong
    mc = _mock_client(return_value={"embeddings": mixed})
    with patch("shared.config._get_ollama_client", return_value=mc):
        with pytest.raises(RuntimeError, match="at index 1"):
            embed_batch(["a", "b"])
