"""Orientation API route."""

import math
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from logos.api.cache import cache

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


@router.get("/orientation")
async def get_orientation() -> JSONResponse:
    data = _to_dict(cache.orientation) if cache.orientation else {}
    age = cache.slow_cache_age()
    return JSONResponse(content=data, headers={"X-Cache-Age": str(age)})
