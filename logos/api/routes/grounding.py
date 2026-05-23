"""Grounding ledger API — tracks operator's claim-ownership state."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/grounding", tags=["grounding"])


class VerdictRequest(BaseModel):
    claim_id: str
    claim_text: str
    verdict: Literal[
        "unexamined",
        "cctv_queued",
        "cctv_complete",
        "personally_grounded",
        "owned_domain",
        "contested",
    ]
    craft_composite: float = 0.0
    craft_category: str = ""
    session_id: str | None = None
    open_questions: list[str] | None = None
    falsification_condition: str | None = None
    divergences: list[str] | None = None


@router.get("/progress")
async def get_progress() -> JSONResponse:
    """Summary stats: total claims, grounded count, deficit."""
    try:
        from shared.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        return JSONResponse(content=ledger.progress())
    except Exception:
        log.warning("Grounding progress query failed", exc_info=True)
        return JSONResponse(content={"error": "query failed"})


@router.get("/claims")
async def get_claims(
    state: str | None = Query(None, description="Filter by grounding state"),
    limit: int = Query(20, ge=1, le=100),
) -> JSONResponse:
    """List claims with grounding state."""
    try:
        from shared.grounding_ledger import GroundingLedger, GroundingState

        ledger = GroundingLedger()
        if state:
            try:
                gs = GroundingState(state)
                entries = ledger.entries_by_state(gs)
            except ValueError:
                entries = ledger.all_entries()
        else:
            entries = ledger.all_entries()

        entries.sort(key=lambda e: e.craft_composite, reverse=True)
        result = [e.model_dump(mode="json") for e in entries[:limit]]
        return JSONResponse(content={"claims": result, "total": len(result)})
    except Exception:
        log.warning("Grounding claims query failed", exc_info=True)
        return JSONResponse(content={"claims": [], "error": "query failed"})


@router.post("/verdict")
async def record_verdict(body: VerdictRequest) -> JSONResponse:
    """Record a grounding verdict from a livestream session."""
    try:
        from shared.grounding_ledger import GroundingLedger, GroundingState

        ledger = GroundingLedger()
        entry = ledger.record_verdict(
            claim_id=body.claim_id,
            claim_text=body.claim_text,
            state=GroundingState(body.verdict),
            craft_composite=body.craft_composite,
            craft_category=body.craft_category,
            session_id=body.session_id,
            open_questions=body.open_questions,
            falsification_condition=body.falsification_condition,
            divergences=body.divergences,
        )
        try:
            from shared.chronicle import emit_event

            emit_event(
                event_type="grounding.verdict",
                payload={
                    "claim_id": body.claim_id,
                    "verdict": entry.state,
                    "craft_composite": body.craft_composite,
                    "session_id": body.session_id,
                    "open_questions_count": len(body.open_questions or []),
                },
            )
        except Exception:
            log.debug("Chronicle emit failed for grounding verdict", exc_info=True)

        return JSONResponse(content={"status": "ok", "state": entry.state})
    except Exception:
        log.warning("Grounding verdict recording failed", exc_info=True)
        return JSONResponse(content={"status": "error"}, status_code=500)


@router.get("/timeline")
async def get_timeline(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    """Chronological view of grounding events for CHI supplementary material."""
    try:
        from shared.grounding_ledger import GroundingLedger

        ledger = GroundingLedger()
        entries = ledger.all_entries()
        entries.sort(key=lambda e: e.grounded_at or "", reverse=True)
        result = [e.model_dump(mode="json") for e in entries[:limit]]
        return JSONResponse(content={"timeline": result})
    except Exception:
        log.warning("Grounding timeline query failed", exc_info=True)
        return JSONResponse(content={"timeline": [], "error": "query failed"})
