"""Tests for FINDING-R closure: get_qdrant() returns consent-gated client."""

from __future__ import annotations


def test_get_qdrant_returns_gated_client():
    """LRR Phase 6 §3 / FINDING-R — shared.config.get_qdrant() must return
    a ConsentGatedQdrant, not a raw QdrantClient. This closes the FINDING-R
    gap where 8 of 10 person-adjacent Qdrant collections bypassed consent
    on upsert by using the factory directly.
    """
    from shared.config import get_qdrant
    from shared.governance.qdrant_gate import ConsentGatedQdrant

    client = get_qdrant()
    assert isinstance(client, ConsentGatedQdrant)


def test_raw_is_still_accessible_for_bootstrap():
    """Schema bootstrapping + tests can reach the ungated client explicitly."""
    from qdrant_client import QdrantClient

    from shared.config import _get_qdrant_raw

    # _get_qdrant_raw is lru_cached; clear so earlier tests that ran
    # under a `patch("shared.config.QdrantClient")` (and called into
    # shared.config while the patch was active) don't bleed a cached
    # MagicMock into this assertion. Observed on full-suite CI runs.
    _get_qdrant_raw.cache_clear()
    raw = _get_qdrant_raw()
    assert isinstance(raw, QdrantClient)


def test_gated_client_proxies_non_upsert_methods():
    """Reads + admin methods pass through to the inner client."""
    from shared.config import get_qdrant

    client = get_qdrant()
    # These are all methods on QdrantClient; the proxy must expose them.
    for method in ("query_points", "scroll", "get_collections", "delete"):
        assert callable(getattr(client, method))
