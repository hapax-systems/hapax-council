"""Data endpoints — serve cached collector results.

All endpoints return the latest cached data from the background
refresh loop. Clients poll at matching cadence (30s fast, 5min slow).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from logos.api.cache import cache

router = APIRouter(prefix="/api", tags=["data"])


def _dict_factory(fields: list[tuple]) -> dict:
    """Custom dict factory for asdict() that handles Path objects."""
    return {k: str(v) if isinstance(v, Path) else v for k, v in fields}


def _to_dict(obj: Any) -> Any:
    """Convert a dataclass (or list of dataclasses) to a dict."""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj, dict_factory=_dict_factory)
    return obj


def _fast_response(data: Any) -> JSONResponse:
    """Return JSON response with X-Cache-Age from fast refresh cadence."""
    return JSONResponse(content=data, headers={"X-Cache-Age": str(cache.fast_cache_age())})


def _slow_response(data: Any) -> JSONResponse:
    """Return JSON response with X-Cache-Age from slow refresh cadence."""
    return JSONResponse(content=data, headers={"X-Cache-Age": str(cache.slow_cache_age())})


# ── Fast cadence (30s) ───────────────────────────────────────────────────


@router.get("/health")
async def get_health():
    return _fast_response(_to_dict(cache.health))


@router.get("/health/history")
async def get_health_history():
    import asyncio

    from logos.data.health import collect_health_history

    history = await asyncio.to_thread(collect_health_history)
    return _to_dict(history)


@router.get("/gpu")
async def get_gpu():
    return _fast_response(_to_dict(cache.gpu))


@router.get("/infrastructure")
async def get_infrastructure():
    return _fast_response(
        {
            "containers": _to_dict(cache.containers),
            "timers": _to_dict(cache.timers),
        }
    )


# ── Slow cadence (5min) ──────────────────────────────────────────────────


@router.get("/briefing")
async def get_briefing():
    return _slow_response(_to_dict(cache.briefing))


@router.get("/scout")
async def get_scout():
    return _slow_response(_to_dict(cache.scout))


@router.get("/drift")
async def get_drift():
    return _slow_response(_to_dict(cache.drift))


@router.get("/cost")
async def get_cost():
    return _slow_response(_to_dict(cache.cost))


@router.get("/goals")
async def get_goals():
    return _slow_response(_to_dict(cache.goals))


@router.get("/readiness")
async def get_readiness():
    return _slow_response(_to_dict(cache.readiness))


@router.get("/nudges")
async def get_nudges():
    return _slow_response(_to_dict(cache.nudges))


@router.get("/agents")
async def get_agents():
    return _slow_response(_to_dict(cache.agents))


@router.get("/accommodations")
async def get_accommodations():
    return _slow_response(_to_dict(cache.accommodations))


@router.get("/management")
async def get_management():
    """Management snapshot — team state, coaching, feedback.

    Council doesn't own management data (that's officium), so this
    returns an empty structure to prevent frontend 404s.
    """
    return _slow_response({"people": [], "coaching": [], "feedback": []})


@router.get("/workspace")
async def workspace():
    """Latest workspace analysis (screen + camera + hardware state)."""
    state_path = Path.home() / ".local" / "share" / "hapax-daimonion" / "workspace_state.json"
    try:
        if state_path.exists():
            data = json.loads(state_path.read_text())
            return _fast_response(data)
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        pass
    return _fast_response({})


@router.get("/manual")
async def get_manual():
    """Return operations-manual.md content.

    Tries canonical hapaxromana version first, then profiles/ copy,
    then generates from agent registry as last resort.
    """
    import asyncio

    from fastapi.responses import JSONResponse

    # Docker mount at /app/hapaxromana, or host path for local dev
    canonical_path = Path("/app/hapaxromana/operations-manual.md")
    if not canonical_path.exists():
        canonical_path = Path.home() / "projects" / "hapaxromana" / "operations-manual.md"
    profiles_path = Path(__file__).parent.parent.parent.parent / "profiles" / "operations-manual.md"

    def _read():
        for path in (canonical_path, profiles_path):
            if path.is_file():
                return path.read_text(), path.stat().st_mtime
        # Last resort: generate from agent registry
        from logos.manual import generate_manual

        return generate_manual(), None

    result = await asyncio.to_thread(_read)
    content, mtime = result
    if content is None:
        return JSONResponse(status_code=404, content={"error": "operations manual not found"})
    from datetime import datetime

    resp: dict = {"content": content}
    if mtime is not None:
        resp["updated_at"] = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
    return resp
