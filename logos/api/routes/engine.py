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
    """Recent event processing history (from in-memory ring buffer)."""
    engine = _get_engine(request)
    if engine is None:
        return JSONResponse({"error": "Engine not initialized"}, status_code=503)
    entries = engine.history[:limit]
    return [
        {
            "timestamp": e.timestamp.isoformat(),
            "event_path": e.event_path,
            "event_type": e.event_type,
            "doc_type": e.doc_type,
            "rules_matched": e.rules_matched,
            "actions": e.actions,
            "errors": e.errors,
        }
        for e in entries
    ]


@router.get("/audit")
async def engine_audit(request: Request, date: str = "", limit: int = 200):
    """Query persistent audit trail (JSONL on disk).

    Args:
        date: ISO date string (YYYY-MM-DD). Defaults to today.
        limit: Max entries to return (newest first).
    """
    import datetime as dt
    import json

    from shared.config import PROFILES_DIR

    audit_dir = PROFILES_DIR / "engine-audit"
    target_date = date or dt.date.today().isoformat()
    audit_file = audit_dir / f"engine-audit-{target_date}.jsonl"

    if not audit_file.exists():
        return []

    try:
        lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
        entries = [json.loads(line) for line in lines[-limit:]]
        entries.reverse()  # newest first
        return entries
    except Exception:
        return JSONResponse({"error": "Failed to read audit log"}, status_code=500)
