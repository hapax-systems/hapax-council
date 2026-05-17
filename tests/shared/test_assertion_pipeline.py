"""Tests for assertions pipeline activation."""

from __future__ import annotations


def test_assertions_collection_in_schema() -> None:
    """assertions must be declared in EXPECTED_COLLECTIONS."""
    from shared.qdrant_schema import EXPECTED_COLLECTIONS

    assert "assertions" in EXPECTED_COLLECTIONS
    assert EXPECTED_COLLECTIONS["assertions"]["distance"] == "Cosine"
