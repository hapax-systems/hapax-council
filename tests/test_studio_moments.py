"""Tests for studio_moments Qdrant collection config and helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_studio_moments_collection_constant():
    from shared.config import STUDIO_MOMENTS_COLLECTION

    assert STUDIO_MOMENTS_COLLECTION == "studio-moments"


def test_clap_embed_dimensions_constant():
    from shared.config import CLAP_EMBED_DIMENSIONS

    assert CLAP_EMBED_DIMENSIONS == 512


def test_audio_path_constants():
    from shared.config import AUDIO_ARCHIVE_DIR, AUDIO_RAG_DIR, AUDIO_RAW_DIR

    assert AUDIO_RAW_DIR.name == "raw"
    assert AUDIO_RAW_DIR.parent.name == "audio-recording"
    assert AUDIO_ARCHIVE_DIR.name == "archive"
    assert AUDIO_ARCHIVE_DIR.parent.name == "audio-recording"
    assert AUDIO_RAG_DIR.name == "audio"
    assert AUDIO_RAG_DIR.parent.name == "rag-sources"


def test_ensure_studio_moments_creates_collection():
    """ensure_studio_moments_collection creates collection when it doesn't exist."""
    mock_client = MagicMock()
    mock_collections = MagicMock()
    mock_collections.collections = []  # No existing collections
    mock_client.get_collections.return_value = mock_collections

    with patch("shared.config.get_qdrant", return_value=mock_client):
        from shared.config import ensure_studio_moments_collection

        ensure_studio_moments_collection()

    mock_client.create_collection.assert_called_once()
    call_kwargs = mock_client.create_collection.call_args
    assert call_kwargs[1]["collection_name"] == "studio-moments"


def test_ensure_studio_moments_idempotent():
    """ensure_studio_moments_collection is a no-op when collection exists."""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_collection.name = "studio-moments"
    mock_collections = MagicMock()
    mock_collections.collections = [mock_collection]
    mock_client.get_collections.return_value = mock_collections

    with patch("shared.config.get_qdrant", return_value=mock_client):
        from shared.config import ensure_studio_moments_collection

        ensure_studio_moments_collection()

    mock_client.create_collection.assert_not_called()
