"""Awareness REST endpoints — read-only consumer surface.

Three endpoints expose the canonical operator-awareness state and
refusal log to pull-mode consumers (Wear OS TileService, omg.lol
fanout, weekly-review job, the awareness-tauri-sse-bridge initial
fetch). Push-mode lives in the SSE companion (separate task).

Read-only by design: no POST/PUT/DELETE here, ever. The constitutional
``feedback_full_automation_or_no_engagement`` precludes mutation
affordances on awareness state — there is no operator ack/dismiss
surface, by axiom.

Stale-state semantics: when ``state.json`` mtime is older than the
file's declared ``ttl_seconds``, ``GET /api/awareness`` returns 503
with header ``X-Awareness-State-Stale: true``. Surfaces interpret
503 as "dim, not error".
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from agents.operator_awareness.public_filter import public_filter
from agents.operator_awareness.state import AwarenessState

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["awareness"])

DEFAULT_STATE_PATH = Path("/dev/shm/hapax-awareness/state.json")
DEFAULT_REFUSALS_PATH = Path("/dev/shm/hapax-refusals/log.jsonl")

# Refusals tail default. The full log lives on tmpfs and rotates at
# midnight UTC (per ``agents/refusal_brief/rotator.py``); this endpoint
# returns the live tail only — historical archives are out of scope.
DEFAULT_REFUSALS_LIMIT = 50

# Per-endpoint request counter. Optional: route serves traffic even
# without prometheus_client (minimal test environments).
hapax_awareness_api_requests_total: Any = None
try:
    from prometheus_client import Counter as _APICounter

    hapax_awareness_api_requests_total = _APICounter(
        "hapax_awareness_api_requests_total",
        "Awareness REST endpoint request outcomes.",
        ["endpoint", "status"],
    )
except Exception:
    pass


def _record(endpoint: str, status: int) -> None:
    if hapax_awareness_api_requests_total is None:
        return
    try:
        hapax_awareness_api_requests_total.labels(endpoint=endpoint, status=str(status)).inc()
    except Exception:
        pass


def _read_state(path: Path | None = None) -> tuple[AwarenessState | None, bool]:
    """Return ``(state, stale)``.

    Path defaults to the module-level ``DEFAULT_STATE_PATH`` looked
    up at call time so tests can monkeypatch the module attribute
    without rebinding default args.

    ``state`` is None when the file is absent or unparseable;
    ``stale`` is True when the file is older than its declared TTL
    (consumer dims rather than errors). The endpoint surfaces this
    distinction via response status (503 when state is None or
    stale, with the ``X-Awareness-State-Stale`` header so the client
    can treat both as "dim").
    """
    p = path if path is not None else DEFAULT_STATE_PATH
    if not p.exists():
        return None, True
    try:
        raw = p.read_text(encoding="utf-8")
        state = AwarenessState.model_validate_json(raw)
    except Exception:
        log.warning("awareness state unreadable at %s", p, exc_info=True)
        return None, True
    age_s = time.time() - p.stat().st_mtime
    return state, age_s > state.ttl_seconds


_PUBLIC_QUERY = Query(False, description="Apply public-safe filter (omg.lol, etc.)")
_SINCE_QUERY = Query(None, description="Filter to refusals timestamp > since (ISO-8601 UTC)")
_LIMIT_QUERY = Query(DEFAULT_REFUSALS_LIMIT, ge=1, le=500)


@router.get("/awareness", response_model=AwarenessState)
async def get_awareness(public: bool = _PUBLIC_QUERY) -> JSONResponse:
    """Single-shot read of the canonical awareness state.

    Returns 200 with the full state when fresh; 503 with the
    ``X-Awareness-State-Stale`` header when the file is missing,
    unreadable, or past its TTL. The 503 body still carries the
    last parseable payload when one exists, so consumers can
    render-with-dim rather than blank.
    """
    state, stale = _read_state()
    if state is None:
        _record("awareness", 503)
        return JSONResponse(
            status_code=503,
            content={"detail": "awareness state unavailable", "stale": True},
            headers={"X-Awareness-State-Stale": "true"},
        )
    if stale:
        _record("awareness", 503)
        return JSONResponse(
            status_code=503,
            content=json.loads(state.model_dump_json()),
            headers={"X-Awareness-State-Stale": "true"},
        )
    payload = public_filter(state) if public else state
    _record("awareness", 200)
    return JSONResponse(
        status_code=200,
        content=json.loads(payload.model_dump_json()),
    )


@router.get("/awareness/watch-summary")
async def get_watch_summary() -> JSONResponse:
    """Compact tile-friendly view (~256 bytes target).

    Wear OS TileService reads this on every tile refresh. The
    payload shape stays narrow on purpose — adding fields here
    costs every tile-render across the operator's day. The three
    decision-critical fields are stance / live / stale; the
    timestamp is included so the tile can render its own ``Ns ago``.
    """
    state, stale = _read_state()
    if state is None:
        _record("awareness_watch_summary", 503)
        return JSONResponse(
            status_code=503,
            content={"stance": "unknown", "live": False, "stale": True},
            headers={"X-Awareness-State-Stale": "true"},
        )
    payload = {
        "stance": state.daimonion_voice.stance,
        "live": bool(state.stream.live),
        "stale": stale,
        "timestamp": state.timestamp.isoformat(),
    }
    _record("awareness_watch_summary", 200)
    headers = {"X-Awareness-State-Stale": "true"} if stale else {}
    return JSONResponse(
        status_code=503 if stale else 200,
        content=payload,
        headers=headers,
    )


@router.get("/refusals")
async def get_refusals(
    since: datetime | None = _SINCE_QUERY,
    limit: int = _LIMIT_QUERY,
) -> Any:
    """Raw refusal-log tail.

    NEVER aggregated — constitutional load-bearing per
    ``feedback_full_automation_or_no_engagement``. The aggregate
    surface ``awareness-refused-aggregate-summary-api`` is itself a
    REFUSED cc-task; aggregating here would defeat the point.
    """
    path = DEFAULT_REFUSALS_PATH  # re-evaluated per request for test monkeypatching
    if not path.exists():
        _record("refusals", 200)
        return {"refusals": [], "total_in_window": 0}

    entries: list[dict[str, Any]] = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            text = raw.strip()
            if not text:
                continue
            try:
                ev = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            entries.append(ev)
    except OSError:
        log.warning("refusal log unreadable at %s", path, exc_info=True)
        _record("refusals", 503)
        return JSONResponse(status_code=503, content={"refusals": [], "total_in_window": 0})

    if since is not None:
        cutoff = since if since.tzinfo else since.replace(tzinfo=UTC)
        kept: list[dict[str, Any]] = []
        for ev in entries:
            ts_raw = ev.get("timestamp")
            if not isinstance(ts_raw, str):
                continue
            try:
                ts = datetime.fromisoformat(ts_raw)
            except ValueError:
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts > cutoff:
                kept.append(ev)
        entries = kept

    _record("refusals", 200)
    return {
        "refusals": entries[-limit:],
        "total_in_window": len(entries),
    }


__all__ = ["router"]
