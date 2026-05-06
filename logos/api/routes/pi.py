"""logos/api/routes/pi.py — Receiver for Pi fleet: IR detections + heartbeats."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from agents.hapax_daimonion.ir_signals import IR_STATE_DIR
from logos._ir_models import IrDetectionReport
from logos.api.routes._config import HAPAX_HOME

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pi", tags=["pi-noir"])

EDGE_STATE_DIR = HAPAX_HOME / "hapax-state" / "edge"

_VALID_ROLES = {"desk", "room", "overhead"}
_VALID_CAM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_last_post_time: dict[str, float] = {}
# #143 — HOT-cadence Pis post at 0.5s; tighten the rate limit to accommodate.
_RATE_LIMIT_S = 0.4


@router.post("/{role}/ir")
async def receive_ir_detection(
    role: str, report: IrDetectionReport, request: Request
) -> JSONResponse:
    """Receive IR detection report from a Pi NoIR edge daemon."""
    if role not in _VALID_ROLES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid role: {role}. Must be one of {_VALID_ROLES}",
        )
    cam_id = _safe_cam_id(getattr(report, "cam_id", "primary"))

    now = time.monotonic()
    rate_key = f"{role}:{cam_id}"
    last = _last_post_time.get(rate_key, 0.0)
    if now - last < _RATE_LIMIT_S:
        return JSONResponse({"status": "throttled"}, status_code=429)
    _last_post_time[rate_key] = now

    state_dir = IR_STATE_DIR
    state_dir.mkdir(parents=True, exist_ok=True)
    try:
        if cam_id == "primary":
            _write_json_atomic(state_dir / f"{role}.json", report.model_dump_json())
        _write_json_atomic(state_dir / f"{role}-{cam_id}.json", report.model_dump_json())
    except OSError as exc:
        log.warning("Failed to write IR state for role=%s cam_id=%s", role, cam_id, exc_info=True)
        raise HTTPException(status_code=500, detail="State file write failed") from exc

    # #143 — persist a compact cadence snapshot so dashboards and fusion
    # code can read the Pi's current cadence without parsing the whole report.
    try:
        cadence_payload = json.dumps(
            {
                "role": role,
                "cam_id": cam_id,
                "cadence_state": getattr(report, "cadence_state", "IDLE"),
                "cadence_interval_s": getattr(report, "cadence_interval_s", 3.0),
                "ts": report.ts,
            }
        )
        if cam_id == "primary":
            _write_json_atomic(state_dir / f"{role}-cadence.json", cadence_payload)
        _write_json_atomic(state_dir / f"{role}-{cam_id}-cadence.json", cadence_payload)
    except OSError:
        log.debug("cadence snapshot write failed", exc_info=True)

    bus = getattr(request.app.state, "event_bus", None)
    if bus:
        from logos.event_bus import FlowEvent

        bus.emit(
            FlowEvent(
                kind="pi.detection", source="pi_fleet", target="ir_perception", label=f"ir/{role}"
            )
        )

    return JSONResponse({"status": "ok", "role": role, "cam_id": cam_id})


def _safe_cam_id(raw: object) -> str:
    cam_id = str(raw or "primary").strip().lower()
    if _VALID_CAM_ID_RE.fullmatch(cam_id):
        return cam_id
    return "primary"


def _write_json_atomic(path: Path, body: str) -> None:
    tmp_file = path.with_suffix(path.suffix + ".tmp")
    tmp_file.write_text(body)
    tmp_file.rename(path)


@router.post("/{hostname}/heartbeat")
async def receive_heartbeat(hostname: str, request: Request) -> JSONResponse:
    """Receive heartbeat from a Pi edge device."""
    if not hostname.startswith("hapax-pi"):
        raise HTTPException(status_code=422, detail="Invalid hostname")

    body = await request.json()
    EDGE_STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = EDGE_STATE_DIR / f"{hostname}.json"
    tmp_file = state_file.with_suffix(".tmp")
    try:
        tmp_file.write_text(json.dumps(body))
        tmp_file.rename(state_file)
    except OSError as exc:
        log.warning("Failed to write heartbeat for %s", hostname, exc_info=True)
        raise HTTPException(status_code=500, detail="Write failed") from exc

    # #143 — heartbeat may carry a cadence snapshot (`cadence_state`,
    # `cadence_interval_s`, `role`). Persist it alongside the IR cadence file
    # so a Pi whose IR POST has been stale can still keep its cadence state
    # visible to the server.
    if isinstance(body, dict):
        role = body.get("role")
        if role in _VALID_ROLES and "cadence_state" in body:
            try:
                IR_STATE_DIR.mkdir(parents=True, exist_ok=True)
                cadence_file = IR_STATE_DIR / f"{role}-cadence.json"
                cadence_tmp = cadence_file.with_suffix(".tmp")
                cadence_tmp.write_text(
                    json.dumps(
                        {
                            "role": role,
                            "cadence_state": body.get("cadence_state", "IDLE"),
                            "cadence_interval_s": body.get("cadence_interval_s", 3.0),
                            "source": "heartbeat",
                            "hostname": hostname,
                        }
                    )
                )
                cadence_tmp.rename(cadence_file)
            except OSError:
                log.debug("heartbeat cadence snapshot failed", exc_info=True)

    return JSONResponse({"status": "ok"})


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
