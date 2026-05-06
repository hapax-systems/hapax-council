"""shared/profile_store.py — Profile fact vector store and digest access.

Provides semantic search over operator profile facts via Qdrant, and
access to pre-computed profile digests. Used by context tools to give
agents on-demand access to profile data without bloating system prompts.

Usage:
    from shared.profile_store import ProfileStore

    store = ProfileStore()
    store.ensure_collection()
    store.index_profile(profile)
    results = store.search("preferred tools", dimension="workflow")
    digest = store.get_digest()
"""

from __future__ import annotations

import json
import logging
import uuid

from opentelemetry import trace

from shared.config import PROFILES_DIR

log = logging.getLogger("shared.profile_store")
_rag_tracer = trace.get_tracer("hapax.rag")

COLLECTION = "profile-facts"
from shared.config import EXPECTED_EMBED_DIMENSIONS as VECTOR_DIM


class ProfileStore:
    """Qdrant-backed semantic search over profile facts + digest access."""

    def __init__(self) -> None:
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from shared.config import get_qdrant

            self._client = get_qdrant()
        return self._client

    def ensure_collection(self) -> None:
        """Create the profile-facts collection if it doesn't exist."""
        from qdrant_client.models import Distance, VectorParams

        collections = [c.name for c in self.client.get_collections().collections]
        if COLLECTION not in collections:
            self.client.create_collection(
                COLLECTION,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            log.info("Created Qdrant collection: %s", COLLECTION)

    def index_profile(self, profile) -> int:
        """Embed and upsert all profile facts into Qdrant.

        Each fact becomes a point with deterministic ID based on dimension+key.
        Returns the number of points upserted.
        """
        with _rag_tracer.start_as_current_span("rag.index") as span:
            from qdrant_client.models import PointStruct

            from shared.config import embed_batch

            texts: list[str] = []
            metadata: list[dict] = []

            for dim in profile.dimensions:
                for fact in dim.facts:
                    text = f"{fact.dimension}/{fact.key}: {fact.value}"
                    texts.append(text)
                    metadata.append(
                        {
                            "dimension": fact.dimension,
                            "key": fact.key,
                            "value": fact.value,
                            "confidence": fact.confidence,
                            "source": fact.source,
                            "text": text,
                            "profile_version": profile.version,
                        }
                    )

            if not texts:
                log.info("No facts to index")
                span.set_attribute("rag.index.count", 0)
                return 0

            # Batch embed (uses search_document prefix for indexing)
            try:
                vectors = embed_batch(texts, prefix="search_document")
            except Exception as e:
                log.error("Failed to embed profile facts: %s", e)
                span.set_attribute("rag.index.count", 0)
                return 0

            # Build points with deterministic IDs
            points: list[PointStruct] = []
            for _i, (vec, meta) in enumerate(zip(vectors, metadata, strict=False)):
                point_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"profile-fact-{meta['dimension']}-{meta['key']}",
                    )
                )
                points.append(PointStruct(id=point_id, vector=vec, payload=meta))

            # Upsert in batches of 100
            batch_size = 100
            for start in range(0, len(points), batch_size):
                batch = points[start : start + batch_size]
                self.client.upsert(COLLECTION, batch)

            log.info("Indexed %d profile facts into %s", len(points), COLLECTION)
            span.set_attribute("rag.index.count", len(points))

            # Clean up stale points whose (dimension, key) no longer exists
            current_keys = {(m["dimension"], m["key"]) for m in metadata}
            self._cleanup_stale_points(current_keys)

            return len(points)

    def _cleanup_stale_points(self, current_keys: set[tuple[str, str]]) -> int:
        """Remove points whose (dimension, key) is no longer in the profile."""
        stale_ids = []
        offset = None
        while True:
            results = self.client.scroll(
                COLLECTION,
                limit=100,
                offset=offset,
                with_payload=["dimension", "key"],
                with_vectors=False,
            )
            points, next_offset = results
            for pt in points:
                pt_payload = pt.payload or {}
                dim = pt_payload.get("dimension", "")
                key = pt_payload.get("key", "")
                if (dim, key) not in current_keys:
                    stale_ids.append(pt.id)
            if next_offset is None:
                break
            offset = next_offset
        if stale_ids:
            from qdrant_client.models import PointIdsList

            self.client.delete(COLLECTION, points_selector=PointIdsList(points=stale_ids))
            log.info("Removed %d stale profile-facts points", len(stale_ids))
        return len(stale_ids)

    def search(
        self,
        query: str,
        *,
        dimension: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Semantic search over profile facts.

        Args:
            query: Natural language query.
            dimension: Optional dimension filter (e.g., "workflow").
            limit: Max results to return.

        Returns:
            List of dicts with keys: dimension, key, value, confidence, score.
        """
        with _rag_tracer.start_as_current_span("rag.search") as span:
            span.set_attribute("rag.query", query[:200])
            span.set_attribute("rag.collection", COLLECTION)
            span.set_attribute("rag.top_k", limit)

            from shared.config import embed

            query_vec = embed(query, prefix="search_query")

            query_filter = None
            if dimension:
                from qdrant_client.models import FieldCondition, Filter, MatchValue

                query_filter = Filter(
                    must=[
                        FieldCondition(key="dimension", match=MatchValue(value=dimension)),
                    ]
                )

            results = self.client.query_points(
                COLLECTION,
                query=query_vec,
                query_filter=query_filter,
                limit=limit,
            )

            result_list = [
                {
                    "dimension": (p.payload or {}).get("dimension", ""),
                    "key": (p.payload or {}).get("key", ""),
                    "value": (p.payload or {}).get("value", ""),
                    "confidence": (p.payload or {}).get("confidence", 0.0),
                    "score": p.score,
                }
                for p in results.points
            ]

            span.set_attribute("rag.result_count", len(result_list))
            if result_list:
                span.set_attribute("rag.top_score", result_list[0]["score"])

            return result_list

    def get_digest(self) -> dict | None:
        """Load the pre-computed profile digest from disk.

        Returns None if the digest file doesn't exist.

        Validates the JSON root is a mapping. Callers
        (``get_dimension_summary``) immediately call ``digest.get(\"dimensions\",
        {}).get(dimension)`` and ``dim_data.get(\"summary\")`` on the
        returned value — a writer producing valid JSON whose root is
        null, a list, a string, or a number previously raised
        AttributeError out of profile-summary lookups. Same shape as
        the other recent SHM-read fixes.
        """
        digest_path = PROFILES_DIR / "operator-digest.json"
        if not digest_path.exists():
            return None
        try:
            data = json.loads(digest_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            log.warning("Failed to load digest: %s", e)
            return None
        if not isinstance(data, dict):
            log.warning(
                "Digest root is %s, expected mapping",
                type(data).__name__,
            )
            return None
        return data

    def get_dimension_summary(self, dimension: str) -> str | None:
        """Get the pre-computed summary for a specific dimension.

        Returns None if digest missing or dimension not found.
        Coerces the chained ``digest.get(\"dimensions\", {})`` intermediary
        to {} when non-dict so a malformed dimensions field can't crash
        the lookup.
        """
        digest = self.get_digest()
        if not digest:
            return None
        dimensions = digest.get("dimensions", {})
        if not isinstance(dimensions, dict):
            return None
        dim_data = dimensions.get(dimension)
        if not isinstance(dim_data, dict):
            return None
        return dim_data.get("summary")
