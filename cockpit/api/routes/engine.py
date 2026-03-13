"""Engine endpoints — reactive engine status, rules, and history."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/engine", tags=["engine"])


def _get_engine(request: Request):
    """Get engine from app state, or None if not started."""
    return getattr(request.app.state, "engine", None)


@router.get("/status")
async def engine_status(request: Request):
    """Current engine status: running, paused, uptime, counters."""
    engine = _get_engine(request)
    if engine is None:
        return JSONResponse({"error": "Engine not initialized"}, status_code=503)
    return engine.status


@router.get("/rules")
async def engine_rules(request: Request):
    """List registered rules with metadata."""
    engine = _get_engine(request)
    if engine is None:
        return JSONResponse({"error": "Engine not initialized"}, status_code=503)
    rules = []
    for rule in engine.registry:
        rules.append(
            {
                "name": rule.name,
                "description": rule.description,
                "phase": rule.phase,
                "cooldown_s": rule.cooldown_s,
            }
        )
    return rules


@router.get("/history")
async def engine_history(request: Request, limit: int = 50):
    """Recent event processing history."""
    engine = _get_engine(request)
    if engine is None:
        return JSONResponse({"error": "Engine not initialized"}, status_code=503)
    entries = engine.history[:limit]
    return [
        {
            "timestamp": e.timestamp.isoformat(),
            "event_path": e.event_path,
            "doc_type": e.doc_type,
            "rules_matched": e.rules_matched,
            "actions": e.actions,
            "errors": e.errors,
        }
        for e in entries
    ]
