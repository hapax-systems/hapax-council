"""Vault-related API routes — related notes via embedding similarity."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/vault", tags=["vault"])


@router.get("/related")
async def get_related_notes(
    q: str = Query(..., description="Query text (note title + excerpt)"),
    limit: int = Query(5, ge=1, le=20),
) -> JSONResponse:
    """Return vault notes most similar to the query via embedding search."""
    import asyncio

    try:
        results = await asyncio.to_thread(_search_related, q, limit)
        return JSONResponse(content={"results": results})
    except Exception as e:
        log.warning("Related notes search failed: %s", e)
        return JSONResponse(content={"results": [], "error": str(e)})


def _search_related(query: str, limit: int) -> list[dict]:
    """Synchronous embedding search against Qdrant documents collection."""
    from shared.config import embed_safe, get_qdrant

    vector = embed_safe(query, prefix="search_query")
    if not vector:
        return []

    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = get_qdrant()
    response = client.query_points(
        collection_name="documents",
        query=vector,
        query_filter=Filter(
            must=[FieldCondition(key="source_service", match=MatchValue(value="obsidian"))]
        ),
        limit=limit * 2,  # over-fetch to dedupe by filename
        with_payload=True,
        score_threshold=0.3,
    )
    results = response.points

    # Dedupe by filename (multiple chunks per note)
    seen: set[str] = set()
    deduplicated: list[dict] = []
    for hit in results:
        payload = hit.payload or {}
        filename = payload.get("filename", "")
        if filename in seen:
            continue
        seen.add(filename)

        # Build obsidian:// URI from source path
        source = payload.get("source", "")
        vault_rel = ""
        marker = "/rag-sources/obsidian/"
        if marker in source:
            vault_rel = source.split(marker, 1)[1]
            # Strip .md for obsidian URI
            if vault_rel.endswith(".md"):
                vault_rel = vault_rel[:-3]

        deduplicated.append(
            {
                "filename": filename,
                "score": round(hit.score, 3),
                "excerpt": (payload.get("text", ""))[:200],
                "obsidian_uri": f"obsidian://open?vault=Personal&file={vault_rel}"
                if vault_rel
                else "",
            }
        )

        if len(deduplicated) >= limit:
            break

    return deduplicated
