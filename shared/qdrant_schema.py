"""shared/qdrant_schema.py — Qdrant collection configuration assertions.

Verifies at startup that all expected collections exist with correct vector
dimensions and distance metrics. Reports issues as warnings (non-fatal).
"""

from __future__ import annotations

import logging

from shared.config import EXPECTED_EMBED_DIMENSIONS

_log = logging.getLogger(__name__)

EXPECTED_COLLECTIONS: dict[str, dict[str, object]] = {
    "profile-facts": {"size": EXPECTED_EMBED_DIMENSIONS, "distance": "Cosine"},
    "documents": {"size": EXPECTED_EMBED_DIMENSIONS, "distance": "Cosine"},
    "axiom-precedents": {"size": EXPECTED_EMBED_DIMENSIONS, "distance": "Cosine"},
    "operator-episodes": {"size": EXPECTED_EMBED_DIMENSIONS, "distance": "Cosine"},
    "studio-moments": {"size": EXPECTED_EMBED_DIMENSIONS, "distance": "Cosine"},
    "operator-corrections": {"size": EXPECTED_EMBED_DIMENSIONS, "distance": "Cosine"},
    "affordances": {"size": EXPECTED_EMBED_DIMENSIONS, "distance": "Cosine"},
    "stream-reactions": {"size": EXPECTED_EMBED_DIMENSIONS, "distance": "Cosine"},
}


async def verify_collections() -> list[str]:
    """Verify all expected Qdrant collections exist with correct config.

    Returns a list of issue descriptions (empty = all good).
    Non-fatal — caller should log issues but not prevent startup.
    """
    from shared.config import get_qdrant

    issues: list[str] = []
    try:
        client = get_qdrant()
        existing = {c.name for c in client.get_collections().collections}
    except Exception as e:
        issues.append(f"Cannot connect to Qdrant: {e}")
        return issues

    for name, expected in EXPECTED_COLLECTIONS.items():
        if name not in existing:
            issues.append(f"Collection '{name}' missing")
            continue

        try:
            info = client.get_collection(name)
            vectors_config = info.config.params.vectors
            # vectors_config can be a VectorParams or a dict of named vectors
            if hasattr(vectors_config, "size"):
                actual_size = vectors_config.size
                actual_distance = vectors_config.distance.name if vectors_config.distance else None
            else:
                issues.append(f"Collection '{name}': unexpected vectors config type")
                continue

            if actual_size != expected["size"]:
                issues.append(
                    f"Collection '{name}': expected {expected['size']}d vectors, got {actual_size}d"
                )
            if actual_distance and actual_distance.upper() != str(expected["distance"]).upper():
                issues.append(
                    f"Collection '{name}': expected {expected['distance']} distance, got {actual_distance}"
                )
        except Exception as e:
            issues.append(f"Collection '{name}': cannot read config: {e}")

    return issues


async def log_collection_issues() -> None:
    """Run verification and log any issues as warnings."""
    issues = await verify_collections()
    if issues:
        for issue in issues:
            _log.warning("Qdrant schema: %s", issue)
        _log.warning("Qdrant schema: %d issue(s) found — health may report degraded", len(issues))
    else:
        _log.info("Qdrant schema: all %d collections verified", len(EXPECTED_COLLECTIONS))
