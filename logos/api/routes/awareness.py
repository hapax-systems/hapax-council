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

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

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

# SSE polling cadence — mtime check on a tmpfs file is sub-microsecond,
# so 1Hz is plenty cheap. Heartbeat at 30s by industry convention
# (covers most TCP-keepalive intervals so dead-connection detection
# happens within a single heartbeat window).
_SSE_POLL_INTERVAL_S = 1.0
_SSE_HEARTBEAT_INTERVAL_S = 30.0

# Per-endpoint request counter. Optional: route serves traffic even
# without prometheus_client (minimal test environments).
hapax_awareness_api_requests_total: Any = None
hapax_awareness_sse_subscribers: Any = None
hapax_awareness_sse_events_total: Any = None
try:
    from prometheus_client import Counter as _APICounter
    from prometheus_client import Gauge as _APIGauge

    hapax_awareness_api_requests_total = _APICounter(
        "hapax_awareness_api_requests_total",
        "Awareness REST endpoint request outcomes.",
        ["endpoint", "status"],
    )
    hapax_awareness_sse_subscribers = _APIGauge(
        "hapax_awareness_sse_subscribers",
        "Currently-connected SSE subscribers on /api/awareness/stream.",
    )
    hapax_awareness_sse_events_total = _APICounter(
        "hapax_awareness_sse_events_total",
        "SSE events emitted by the awareness stream, per event type.",
        ["type"],
    )
except Exception:
    pass


def _record_sse_event(event_type: str) -> None:
    if hapax_awareness_sse_events_total is None:
        return
    try:
        hapax_awareness_sse_events_total.labels(type=event_type).inc()
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


async def _awareness_sse_generator(
    *,
    public: bool,
    poll_interval_s: float = _SSE_POLL_INTERVAL_S,
    heartbeat_interval_s: float = _SSE_HEARTBEAT_INTERVAL_S,
    state_path: Path | None = None,
    iter_limit: int | None = None,
    sleep_fn: Any = None,
) -> AsyncIterator[dict[str, str]]:
    """Generate the SSE event stream for awareness state.

    Three event types:

    * ``state`` — full ``AwarenessState`` JSON (or its public-filtered
      view); fired on first observation and on every state-file
      mtime change thereafter.
    * ``stale`` — fired once when the file's age crosses the TTL,
      and again whenever the next ``state`` resolves the staleness.
    * ``heartbeat`` — fired every ``heartbeat_interval_s`` seconds
      so clients can detect dead connections in absence of state
      changes.

    Pure async generator with all I/O bound to the arguments — tests
    inject ``state_path`` + ``iter_limit`` + ``sleep_fn`` to drive
    deterministic exercises.
    """
    path = state_path if state_path is not None else DEFAULT_STATE_PATH
    sleep = sleep_fn or asyncio.sleep
    last_mtime = -1.0
    # Seed the emission clock to "now" so the first heartbeat fires
    # one full ``heartbeat_interval_s`` after the generator starts —
    # not immediately on iteration 1 (which would happen if seeded
    # to 0.0, since wall-clock seconds-since-epoch dwarfs any sane
    # heartbeat interval).
    last_emit_ts = time.time()
    last_was_stale = False
    iters = 0

    while True:
        if iter_limit is not None and iters >= iter_limit:
            return
        iters += 1
        now = time.time()

        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None

        if mtime is not None and mtime != last_mtime:
            last_mtime = mtime
            try:
                raw = path.read_text(encoding="utf-8")
                state = AwarenessState.model_validate_json(raw)
            except Exception:
                log.warning("awareness SSE: state unreadable", exc_info=True)
                state = None

            if state is not None:
                age_s = now - mtime
                stale = age_s > state.ttl_seconds
                payload = public_filter(state) if public else state
                yield {
                    "event": "state",
                    "data": payload.model_dump_json(),
                }
                _record_sse_event("state")
                last_emit_ts = now
                if stale and not last_was_stale:
                    yield {
                        "event": "stale",
                        "data": json.dumps({"age_s": age_s}),
                    }
                    _record_sse_event("stale")
                    last_was_stale = True
                elif not stale and last_was_stale:
                    last_was_stale = False
        elif now - last_emit_ts >= heartbeat_interval_s:
            yield {
                "event": "heartbeat",
                "data": json.dumps({"ts": now}),
            }
            _record_sse_event("heartbeat")
            last_emit_ts = now

        await sleep(poll_interval_s)


@router.get("/awareness/stream")
async def stream_awareness(public: bool = _PUBLIC_QUERY) -> EventSourceResponse:
    """Server-sent event stream of awareness state changes.

    Single-operator design: the consumer set is small (Logos sidebar,
    Tauri webview, occasional weekly-review job). The server doesn't
    multicast — each subscriber gets its own generator, polls the
    same tmpfs file, and emits independently. mtime poll is sub-µs
    so 0..N concurrent subscribers cost effectively nothing.

    On connection: emits the current ``state`` event immediately.
    Subsequent ``state`` events fire on file-mtime change.
    ``heartbeat`` every 30s so dead connections are detectable
    inside one window.
    """

    async def _stream() -> AsyncIterator[dict[str, str]]:
        if hapax_awareness_sse_subscribers is not None:
            try:
                hapax_awareness_sse_subscribers.inc()
            except Exception:
                pass
        try:
            async for event in _awareness_sse_generator(public=public):
                yield event
        finally:
            if hapax_awareness_sse_subscribers is not None:
                try:
                    hapax_awareness_sse_subscribers.dec()
                except Exception:
                    pass

    return EventSourceResponse(_stream())


__all__ = ["router"]
