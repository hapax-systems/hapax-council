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


@router.get("/system_degraded")
async def system_degraded_status(request: Request):
    """Phase 6d-i.B SystemDegradedEngine posterior + state.

    Returns the Bayesian meta-claim posterior and discrete state
    derived from the live observation stream (currently
    queue_depth_observation; drift / gpu / director_cadence wire in
    subsequent PRs). State is one of DEGRADED / UNCERTAIN / HEALTHY.
    """
    sde = getattr(request.app.state, "system_degraded_engine", None)
    if sde is None:
        return JSONResponse({"error": "SystemDegradedEngine not initialized"}, status_code=503)
    return {"posterior": sde.posterior, "state": sde.state}


@router.get("/operator_activity")
async def operator_activity_status(request: Request):
    """Phase 6a-i.B OperatorActivityEngine posterior + state.

    Returns the Bayesian activity-claim posterior and discrete state
    derived from the live perception-state observation stream
    (keyboard_active, desk_active, desktop_focus_changed_recent,
    midi_clock_active, watch_movement). State is one of
    ACTIVE / UNCERTAIN / IDLE.
    """
    oae = getattr(request.app.state, "operator_activity_engine", None)
    if oae is None:
        return JSONResponse({"error": "OperatorActivityEngine not initialized"}, status_code=503)
    return {"posterior": oae.posterior, "state": oae.state}


@router.get("/mood_arousal")
async def mood_arousal_status(request: Request):
    """Phase 6b-i MoodArousalEngine posterior + state.

    Returns the Bayesian mood-arousal posterior and discrete state.
    Signal accessors on ``LogosStimmungBridge`` (ambient_audio_rms_high,
    contact_mic_onset_rate_high, midi_clock_bpm_high, hr_bpm_above_baseline)
    are live and return ``None`` only when the source is missing, stale, or
    the rolling baseline is still warming. The engine treats ``None`` as
    skip-this-signal.
    State is one of AROUSED / UNCERTAIN / CALM.
    """
    mae = getattr(request.app.state, "mood_arousal_engine", None)
    if mae is None:
        return JSONResponse({"error": "MoodArousalEngine not initialized"}, status_code=503)
    return {"posterior": mae.posterior, "state": mae.state}


@router.get("/mood_valence")
async def mood_valence_status(request: Request):
    """Phase 6b-ii MoodValenceEngine posterior + state.

    Returns the Bayesian mood-valence posterior and discrete state.
    Signal accessors on ``LogosMoodValenceBridge`` (hrv_below_baseline,
    skin_temp_drop, sleep_debt_high, voice_pitch_elevated) are live and
    return ``None`` only when the source is missing, stale, or warming.
    State is one of NEGATIVE / UNCERTAIN / POSITIVE.
    """
    mve = getattr(request.app.state, "mood_valence_engine", None)
    if mve is None:
        return JSONResponse({"error": "MoodValenceEngine not initialized"}, status_code=503)
    return {"posterior": mve.posterior, "state": mve.state}


@router.get("/mood_coherence")
async def mood_coherence_status(request: Request):
    """Phase 6b-iii MoodCoherenceEngine posterior + state.

    Returns the Bayesian mood-coherence posterior and discrete state.
    Signal accessors on ``LogosMoodCoherenceBridge`` (hrv_variability_high,
    respiration_irregular, movement_jitter_high, skin_temp_volatility_high)
    are live and return ``None`` only when the source is missing, stale, or
    warming. State is one of INCOHERENT / UNCERTAIN / COHERENT.
    """
    mce = getattr(request.app.state, "mood_coherence_engine", None)
    if mce is None:
        return JSONResponse({"error": "MoodCoherenceEngine not initialized"}, status_code=503)
    return {"posterior": mce.posterior, "state": mce.state}


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

    from logos.api.routes._config import PROFILES_DIR

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
