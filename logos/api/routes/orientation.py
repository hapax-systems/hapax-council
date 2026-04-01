"""Orientation API route."""

from dataclasses import asdict, is_dataclass

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from logos.api.cache import cache

router = APIRouter(prefix="/api", tags=["orientation"])


def _to_dict(obj: object) -> object:
    """Recursively convert dataclasses to dicts for JSON serialization."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    return obj


@router.get("/orientation")
async def get_orientation() -> JSONResponse:
    data = _to_dict(cache.orientation) if cache.orientation else {}
    age = cache.slow_cache_age()
    return JSONResponse(content=data, headers={"X-Cache-Age": str(age)})
