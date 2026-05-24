"""Claims triage API — CRAFT-scored research claims for grounding prioritization."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/claims", tags=["claims"])


@router.get("/triage")
async def get_triaged_claims(
    category: str | None = Query(None, description="Filter by triage category: A/B/C/D"),
    claim_type: str | None = Query(None, description="Filter: epistemic or bridge"),
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    """Return CRAFT-scored claims sorted by grounding priority."""
    try:
        results = await asyncio.to_thread(_query_claims, category, claim_type, limit)
        return JSONResponse(content={"claims": results, "total": len(results)})
    except Exception:
        log.warning("Claims triage query failed", exc_info=True)
        return JSONResponse(content={"claims": [], "error": "query failed"})


def _query_claims(category: str | None, claim_type: str | None, limit: int) -> list[dict]:
    """Query Qdrant assertions collection for CRAFT-scored claims."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from shared.config import get_qdrant

    client = get_qdrant()

    must_conditions = [
        FieldCondition(key="source_type", match=MatchValue(value="claim")),
    ]

    category_map = {
        "A": "ground_personally",
        "B": "verify_cctv",
        "C": "trust_tests",
        "D": "already_owned",
    }
    if category and category.upper() in category_map:
        must_conditions.append(
            FieldCondition(
                key="craft_category",
                match=MatchValue(value=category_map[category.upper()]),
            )
        )

    if claim_type:
        must_conditions.append(
            FieldCondition(key="claim_category", match=MatchValue(value=claim_type))
        )

    results, _ = client.scroll(
        "assertions",
        scroll_filter=Filter(must=must_conditions),
        limit=limit,
        with_payload=True,
    )

    claims = []
    for point in results:
        p = point.payload or {}
        claims.append(
            {
                "text": p.get("text", ""),
                "source_path": p.get("source_path", ""),
                "line_number": p.get("line_number", 0),
                "verb": p.get("verb", ""),
                "claim_category": p.get("claim_category", ""),
                "craft_composite": p.get("craft_composite", 0.0),
                "craft_category": p.get("craft_category", ""),
                "grounding_status": p.get("grounding_status", "unexamined"),
                "craft_scores": {
                    "chi_centrality": p.get("craft_chi_centrality", 3),
                    "domain_distance": p.get("craft_domain_distance", 3),
                    "falsifiability_risk": p.get("craft_falsifiability_risk", 3),
                    "ai_provenance": p.get("craft_ai_provenance", 3),
                    "dependency_depth": p.get("craft_dependency_depth", 2),
                    "verification_status": p.get("craft_verification_status", 3),
                },
            }
        )

    claims.sort(key=lambda c: c["craft_composite"], reverse=True)
    return claims
