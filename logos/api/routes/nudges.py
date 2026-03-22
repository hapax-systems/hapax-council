"""Nudge action endpoints — act on or dismiss nudges."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from logos.api.cache import cache

router = APIRouter(prefix="/api/nudges", tags=["nudges"])


class NudgeActionResponse(BaseModel):
    status: str
    source_id: str
    action: str


@router.post("/{source_id}/act")
async def act_on_nudge(source_id: str) -> NudgeActionResponse:
    """Record that the operator executed a nudge's suggested action."""
    return _record(source_id, "executed")


@router.post("/{source_id}/dismiss")
async def dismiss_nudge(source_id: str) -> NudgeActionResponse:
    """Record that the operator dismissed a nudge."""
    return _record(source_id, "dismissed")


def _record(source_id: str, action: str) -> NudgeActionResponse:
    """Find the nudge and record the decision."""
    from logos.data.decisions import Decision, record_decision

    # Find matching nudge in cache
    nudge = None
    for n in cache.nudges or []:
        sid = n.source_id if hasattr(n, "source_id") else n.get("source_id", "")
        if sid == source_id:
            nudge = n
            break

    if nudge is None:
        raise HTTPException(status_code=404, detail=f"Nudge '{source_id}' not found")

    title = nudge.title if hasattr(nudge, "title") else nudge.get("title", source_id)
    category = nudge.category if hasattr(nudge, "category") else nudge.get("category", "unknown")

    record_decision(
        Decision(
            timestamp=datetime.now(UTC).isoformat(),
            nudge_title=title,
            nudge_category=category,
            action=action,
        )
    )

    return NudgeActionResponse(status="ok", source_id=source_id, action=action)
