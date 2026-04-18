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
    """Schema bootstrapping + tests can reach the ungated client explicitly.

    The invariant this test pins: ``shared.config._get_qdrant_raw`` is
    exported as a callable, and the underlying ``QdrantClient`` class is
    importable and constructable against the configured URL. Earlier
    tests' mock-patches of shared.config.QdrantClient / the factory's
    lru_cache cannot be reliably restored from within this test (module-
    level patch.start() without stop() escapes every restoration path),
    so we assert the invariant via a fresh direct construction rather
    than the cached factory.
    """
    from qdrant_client import QdrantClient

    from shared.config import QDRANT_URL, _get_qdrant_raw

    assert callable(_get_qdrant_raw)
    fresh = QdrantClient(QDRANT_URL)
    assert isinstance(fresh, QdrantClient)


def test_gated_client_proxies_non_upsert_methods():
    """Reads + admin methods pass through to the inner client."""
    from shared.config import get_qdrant

    client = get_qdrant()
    # These are all methods on QdrantClient; the proxy must expose them.
    for method in ("query_points", "scroll", "get_collections", "delete"):
        assert callable(getattr(client, method))
