"""Logos API — stream-mode endpoints (LRR Phase 6 §2)."""

from __future__ import annotations

from fastapi import APIRouter

from shared.stream_mode import get_stream_mode_or_off

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
