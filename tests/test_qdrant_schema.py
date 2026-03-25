"""Tests for shared/qdrant_schema.py — Qdrant collection schema assertions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from shared.qdrant_schema import EXPECTED_COLLECTIONS, verify_collections


def _make_collection_info(size: int = 768, distance: str = "Cosine"):
    """Build a mock collection info matching qdrant_client response shape."""
    vectors = SimpleNamespace(size=size, distance=SimpleNamespace(name=distance))
    params = SimpleNamespace(vectors=vectors)
    config = SimpleNamespace(params=params)
    return SimpleNamespace(config=config)


def _make_collection_list(names: list[str]):
    """Build a mock get_collections response."""
    collections = [SimpleNamespace(name=n) for n in names]
    return SimpleNamespace(collections=collections)


class TestExpectedCollections:
    def test_all_six_collections_defined(self):
        assert len(EXPECTED_COLLECTIONS) == 6

    def test_all_use_768_dimensions(self):
        for name, spec in EXPECTED_COLLECTIONS.items():
            assert spec["size"] == 768, f"{name} expected 768d"

    def test_all_use_cosine_distance(self):
        for name, spec in EXPECTED_COLLECTIONS.items():
            assert spec["distance"] == "Cosine", f"{name} expected Cosine"


class TestVerifyCollections:
    @pytest.fixture()
    def mock_qdrant(self):
        with patch("shared.config.get_qdrant") as mock:
            client = MagicMock()
            mock.return_value = client
            yield client

    async def test_all_present_correct(self, mock_qdrant):
        names = list(EXPECTED_COLLECTIONS.keys())
        mock_qdrant.get_collections.return_value = _make_collection_list(names)
        mock_qdrant.get_collection.side_effect = lambda n: _make_collection_info()

        issues = await verify_collections()
        assert issues == []

    async def test_missing_collection(self, mock_qdrant):
        names = list(EXPECTED_COLLECTIONS.keys())[:-1]  # drop last
        mock_qdrant.get_collections.return_value = _make_collection_list(names)
        mock_qdrant.get_collection.side_effect = lambda n: _make_collection_info()

        issues = await verify_collections()
        assert len(issues) == 1
        assert "missing" in issues[0].lower()

    async def test_wrong_dimensions(self, mock_qdrant):
        names = list(EXPECTED_COLLECTIONS.keys())
        mock_qdrant.get_collections.return_value = _make_collection_list(names)
        mock_qdrant.get_collection.side_effect = lambda n: _make_collection_info(size=384)

        issues = await verify_collections()
        assert len(issues) == 6
        assert all("768d" in i for i in issues)

    async def test_cosine_case_insensitive(self, mock_qdrant):
        """Qdrant client returns distance enum name as uppercase (COSINE)."""
        names = list(EXPECTED_COLLECTIONS.keys())
        mock_qdrant.get_collections.return_value = _make_collection_list(names)
        mock_qdrant.get_collection.side_effect = lambda n: _make_collection_info(distance="COSINE")

        issues = await verify_collections()
        assert issues == []

    async def test_wrong_distance(self, mock_qdrant):
        names = list(EXPECTED_COLLECTIONS.keys())
        mock_qdrant.get_collections.return_value = _make_collection_list(names)
        mock_qdrant.get_collection.side_effect = lambda n: _make_collection_info(distance="EUCLID")

        issues = await verify_collections()
        assert len(issues) == 6
        assert all("EUCLID" in i for i in issues)

    async def test_connection_failure(self, mock_qdrant):
        mock_qdrant.get_collections.side_effect = ConnectionError("refused")

        # get_qdrant returns the mock, but get_collections raises
        issues = await verify_collections()
        assert len(issues) == 1
        assert "Cannot connect" in issues[0]
