"""Semantic trace query endpoints for the socio-linguistic tracing layer."""

from __future__ import annotations

import time

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from shared.chronicle import CHRONICLE_FILE, query

router = APIRouter(prefix="/api/semantic-trace", tags=["semantic-trace"])


@router.get("")
def get_semantic_trace(
    since: str = Query("-1h", description="Relative (-1h, -30m) or Unix timestamp"),
    until: str | None = Query(None, description="Upper bound; defaults to now"),
    source: str | None = Query(None, description="Filter by source (e.g. hapax_daimonion)"),
    event_type: str | None = Query(
        None,
        description="Filter by event_type (e.g. semantics.interpretation_decided)",
    ),
    limit: int = Query(100, ge=1, le=1000),
) -> JSONResponse:
    since_ts = _parse_relative(since)
    until_ts = _parse_relative(until) if until else None

    events = query(
        since=since_ts,
        until=until_ts,
        source=source,
        event_type=event_type,
        evidence_class="semantic_interpretation",
        limit=limit,
        path=CHRONICLE_FILE,
    )
    return JSONResponse(
        [
            {
                "event_id": ev.event_id,
                "ts": ev.ts,
                "source": ev.source,
                "event_type": ev.event_type,
                "payload": ev.payload,
                "trace_id": ev.trace_id,
                "span_id": ev.span_id,
                "public_scope": ev.public_scope,
            }
            for ev in events
        ]
    )


@router.get("/grounding-trajectory")
def get_grounding_trajectory(
    days: int = Query(7, ge=1, le=90, description="Lookback window in days"),
) -> JSONResponse:
    since = time.time() - (days * 86400)

    events = query(
        since=since,
        evidence_class="semantic_interpretation",
        limit=5000,
        path=CHRONICLE_FILE,
    )
    grounding = [
        {
            "event_id": ev.event_id,
            "ts": ev.ts,
            "event_type": ev.event_type,
            "payload": ev.payload,
        }
        for ev in events
        if ev.event_type in ("semantics.grounding_converged", "semantics.grounding_diverged")
    ]
    return JSONResponse(grounding)


def _parse_relative(s: str) -> float:
    from fastapi import HTTPException

    s = s.strip()
    if s.startswith("-"):
        body = s[1:]
        if not body:
            raise HTTPException(400, f"Invalid relative time: {s!r}")
        unit = body[-1]
        multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit)
        if multiplier is None:
            raise HTTPException(400, f"Unknown time unit {unit!r} in {s!r} (expected s/m/h/d)")
        try:
            n = float(body[:-1])
        except ValueError as e:
            raise HTTPException(400, f"Invalid relative time: {s!r}") from e
        return time.time() - n * multiplier
    try:
        return float(s)
    except ValueError as e:
        raise HTTPException(
            400, f"Cannot parse time: {s!r} (expected relative like -1h or Unix timestamp)"
        ) from e
