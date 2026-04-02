"""Chronicle API endpoints — structured query and LLM narrative synthesis."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from shared.chronicle import CHRONICLE_FILE, ChronicleEvent, query

router = APIRouter(prefix="/api/chronicle", tags=["chronicle"])

_SYSTEM_PROMPT = """\
You are an observability analyst for Hapax, a personal operating environment with five
circulatory systems:

- **engine**: Reactive rules engine. Watches filesystem changes, fires cascading actions.
- **stimmung**: Affective state layer. Aggregates 11 dimensions (intensity, tension, depth,
  coherence, spectral_color, temporal_distortion, degradation, pitch_displacement, diffusion,
  arousal, valence) into operator-facing mood signal.
- **visual**: Shader graph pipeline (wgpu, 8 passes). Temporal feedback loops, reaction-
  diffusion, content compositing. Writes uniforms to /dev/shm.
- **perception**: Multi-modal sensor fusion. IR Pi fleet, contact mic, biometrics, gaze.
  Writes to perception-state.json.
- **voice**: Hapax Daimonion voice daemon. Cognitive loops, tool recruitment, utterance
  generation, TTS pipeline.

**trace_id** (32-hex) links causally related events across systems — follow it to reconstruct
an impingement cascade from initial trigger through all downstream activations.

**span_id** / **parent_span_id** give fine-grained parent-child structure within a trace.

**Snapshots** are periodic state captures (event_type ending in `.snapshot`); distinguish
them from edge-triggered events.

Use US Central timezone when expressing times. Be specific about event sequences and causal
chains. Answer the operator's question directly and concisely.
"""


def _parse_time(s: str) -> float:
    """Parse a relative (-1h, -30m, -6h) or ISO 8601 string to a Unix timestamp."""
    s = s.strip()
    if s.startswith("-"):
        body = s[1:]
        unit = body[-1]
        try:
            n = float(body[:-1])
        except ValueError as exc:
            raise ValueError(f"Invalid relative time: {s!r}") from exc
        multipliers = {"s": 1, "m": 60, "h": 3600}
        if unit not in multipliers:
            raise ValueError(f"Unknown unit {unit!r} in {s!r}; use s/m/h")
        return time.time() - n * multipliers[unit]
    # ISO 8601
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.timestamp()


def _event_to_dict(ev: ChronicleEvent) -> dict:
    return {
        "ts": ev.ts,
        "trace_id": ev.trace_id,
        "span_id": ev.span_id,
        "parent_span_id": ev.parent_span_id,
        "source": ev.source,
        "event_type": ev.event_type,
        "payload": ev.payload,
    }


def _get_narration_agent():
    """Return a pydantic-ai Agent for chronicle narration. Extracted for test mocking."""
    from pydantic_ai import Agent

    from shared.config import get_model

    return Agent(get_model("balanced"), system_prompt=_SYSTEM_PROMPT, output_type=str)


@router.get("")
async def chronicle_query(
    since: str = Query(..., description="Relative (-1h, -30m) or ISO 8601 lower bound"),
    until: str | None = Query(None, description="Relative or ISO 8601 upper bound"),
    source: str | None = Query(None, description="Filter by circulatory system"),
    event_type: str | None = Query(None, description="Filter by event type"),
    trace_id: str | None = Query(None, description="Follow causal chain by trace ID"),
    limit: int = Query(500, ge=1, le=5000, description="Max events to return"),
) -> JSONResponse:
    """Return chronicle events matching the given filters, newest-first."""
    try:
        since_ts = _parse_time(since)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    until_ts: float | None = None
    if until is not None:
        try:
            until_ts = _parse_time(until)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)

    events = query(
        since=since_ts,
        until=until_ts,
        source=source,
        event_type=event_type,
        trace_id=trace_id,
        limit=limit,
        path=CHRONICLE_FILE,
    )
    return JSONResponse([_event_to_dict(ev) for ev in events])


@router.get("/narrate")
async def chronicle_narrate(
    question: str = Query(..., description="Question for the LLM to answer about the events"),
    since: str = Query(..., description="Relative (-1h, -30m) or ISO 8601 lower bound"),
    until: str | None = Query(None, description="Relative or ISO 8601 upper bound"),
    source: str | None = Query(None, description="Filter by circulatory system"),
    event_type: str | None = Query(None, description="Filter by event type"),
    trace_id: str | None = Query(None, description="Follow causal chain by trace ID"),
    limit: int = Query(500, ge=1, le=5000, description="Max events to return"),
) -> JSONResponse:
    """Synthesise a narrative answer about chronicle events using an LLM."""
    try:
        since_ts = _parse_time(since)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)

    until_ts: float | None = None
    if until is not None:
        try:
            until_ts = _parse_time(until)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)

    events = query(
        since=since_ts,
        until=until_ts,
        source=source,
        event_type=event_type,
        trace_id=trace_id,
        limit=limit,
        path=CHRONICLE_FILE,
    )

    lines: list[str] = []
    for ev in reversed(events):  # chronological order for the LLM
        iso = datetime.fromtimestamp(ev.ts, tz=UTC).isoformat()
        trace_short = ev.trace_id[:8] + "..."
        lines.append(f"[{iso}] {ev.source}/{ev.event_type} trace={trace_short} {ev.payload}")

    event_text = "\n".join(lines) if lines else "(no events)"
    prompt = f"Events:\n{event_text}\n\nQuestion: {question}"

    agent = _get_narration_agent()
    result = agent.run_sync(prompt)
    return JSONResponse({"narrative": result.output, "event_count": len(events)})
