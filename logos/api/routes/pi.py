"""logos/api/routes/pi.py — Receiver for Pi NoIR edge detection reports."""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from agents.hapax_daimonion.ir_signals import IR_STATE_DIR
from shared.ir_models import IrDetectionReport

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pi", tags=["pi-noir"])

_VALID_ROLES = {"desk", "room", "overhead"}
_last_post_time: dict[str, float] = {}
_RATE_LIMIT_S = 1.0


@router.post("/{role}/ir")
async def receive_ir_detection(role: str, report: IrDetectionReport) -> JSONResponse:
    """Receive IR detection report from a Pi NoIR edge daemon."""
    if role not in _VALID_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role: {role}. Must be one of {_VALID_ROLES}",
        )

    now = time.monotonic()
    last = _last_post_time.get(role, 0.0)
    if now - last < _RATE_LIMIT_S:
        return JSONResponse({"status": "throttled"}, status_code=429)
    _last_post_time[role] = now

    state_dir = IR_STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / f"{role}.json"
    tmp_file = state_file.with_suffix(".tmp")
    try:
        tmp_file.write_text(report.model_dump_json())
        tmp_file.rename(state_file)
    except OSError as exc:
        log.warning("Failed to write IR state for role=%s", role, exc_info=True)
        raise HTTPException(status_code=500, detail="State file write failed") from exc

    return JSONResponse({"status": "ok", "role": role})


@router.get("/status")
async def pi_status() -> JSONResponse:
    """Return status of all Pi NoIR nodes."""
    status: dict[str, dict] = {}
    for role in sorted(_VALID_ROLES):
        state_file = IR_STATE_DIR / f"{role}.json"
        if state_file.exists():
            try:
                mtime = state_file.stat().st_mtime
                age = time.time() - mtime
                status[role] = {
                    "online": age < 15.0,
                    "last_seen_seconds_ago": round(age, 1),
                }
            except OSError:
                status[role] = {"online": False, "error": "stat failed"}
        else:
            status[role] = {"online": False}
    return JSONResponse(status)
