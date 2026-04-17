"""Orientation API route."""

import math
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from logos.api.cache import cache
from logos.api.deps.stream_redaction import is_publicly_visible, pii_redact

router = APIRouter(prefix="/api", tags=["orientation"])


def _sanitize_floats(obj: Any) -> Any:
    """Replace inf/nan floats with None for JSON compliance."""
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_floats(v) for v in obj]
    return obj


def _to_dict(obj: object) -> object:
    """Convert dataclasses to JSON-safe dicts."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return _sanitize_floats(asdict(obj))
    return obj


def _redact_for_stream(data: Any) -> Any:
    """LRR Phase 6 §4.A: strip P0-stale goals and PII-redact next_action.

    Operates on the serialized-dict form (post dataclass→dict). Modifies
    in place and returns the same dict for chaining.
    """
    if not isinstance(data, dict):
        return data
    for domain in data.get("domains", []) or []:
        if not isinstance(domain, dict):
            continue
        # Omit P0-priority stale goals — these are the highest-signal
        # dropped-ball moments and the least appropriate for broadcast
        top_goal = domain.get("top_goal")
        if (
            isinstance(top_goal, dict)
            and top_goal.get("priority") == "P0"
            and top_goal.get("stale") is True
        ):
            domain["top_goal"] = None
        # PII-regex redact next_action (email, phone, SSN, credit-card)
        next_action = domain.get("next_action")
        if isinstance(next_action, str) and next_action:
            domain["next_action"] = pii_redact(next_action)
    return data


@router.get("/orientation")
async def get_orientation() -> JSONResponse:
    data = _to_dict(cache.orientation) if cache.orientation else {}
    if is_publicly_visible():
        data = _redact_for_stream(data)
    age = cache.slow_cache_age()
    return JSONResponse(content=data, headers={"X-Cache-Age": str(age)})
