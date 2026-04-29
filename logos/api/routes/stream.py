"""Logos API — stream-mode endpoints (LRR Phase 6 §2)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from shared.stream_mode import StreamMode, get_stream_mode_or_off, set_stream_mode

router = APIRouter(prefix="/api/stream", tags=["stream"])


@router.get("/mode")
def get_mode() -> dict[str, str]:
    """Return the current livestream broadcast posture.

    Uses the or-off fail-mode: missing-file defaults to ``off`` for the
    diagnostic endpoint. Broadcast-gating callers that need fail-closed
    semantics must go through ``shared.stream_mode.get_stream_mode()``
    directly.
    """
    return {"mode": get_stream_mode_or_off().value}


class StreamModeRequest(BaseModel):
    mode: StreamMode


@router.put("/mode")
def put_mode(req: StreamModeRequest) -> dict[str, str]:
    """Set the livestream broadcast posture through the central Logos API."""

    set_stream_mode(req.mode)
    return {"mode": get_stream_mode_or_off().value}


# Keep decorator-registered route handlers statically visible to vulture.
_FASTAPI_ROUTE_HANDLERS = (get_mode, put_mode)
