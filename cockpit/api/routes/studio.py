"""Studio ingestion endpoints — audio/video capture and classification data.

Serves cached studio snapshot data and provides CLAP-based semantic
search over the studio_moments Qdrant collection.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cockpit.api.cache import cache

router = APIRouter(prefix="/api", tags=["studio"])


def _dict_factory(fields: list[tuple]) -> dict:
    result = {}
    for k, v in fields:
        if isinstance(v, Path):
            result[k] = str(v)
        elif isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def _to_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj, dict_factory=_dict_factory)
    return obj


def _slow_response(data: Any) -> JSONResponse:
    return JSONResponse(content=data, headers={"X-Cache-Age": str(cache.slow_cache_age())})


@router.get("/studio")
async def get_studio():
    """Combined studio ingestion snapshot."""
    return _slow_response(_to_dict(cache.studio))


@router.get("/studio/stream/info")
async def get_stream_info():
    """Stream availability info."""
    hls_dir = Path.home() / ".cache" / "hapax-compositor" / "hls"
    playlist = hls_dir / "stream.m3u8"
    snapshot = SNAPSHOT_PATH
    return {
        "hls_url": "/api/studio/hls/stream.m3u8",
        "hls_enabled": playlist.exists(),
        "mjpeg_url": "/api/studio/stream/snapshot",
        "mjpeg_enabled": snapshot.exists(),
        "enabled": playlist.exists() or snapshot.exists(),
    }


SNAPSHOT_PATH = Path("/dev/shm/hapax-compositor/snapshot.jpg")


_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


@router.get("/studio/stream/snapshot")
async def snapshot():
    """Single JPEG snapshot of the composited output."""
    if not SNAPSHOT_PATH.exists():
        return JSONResponse({"error": "compositor not running"}, status_code=503)
    try:
        data = SNAPSHOT_PATH.read_bytes()
    except OSError:
        return JSONResponse({"error": "read failed"}, status_code=503)
    from starlette.responses import Response

    return Response(content=data, media_type="image/jpeg", headers=_NO_CACHE)


@router.get("/studio/stream/camera/{role}")
async def camera_snapshot(role: str):
    """Single JPEG snapshot of an individual camera feed."""
    cam_path = Path(f"/dev/shm/hapax-compositor/{role}.jpg")
    if not cam_path.exists():
        return JSONResponse({"error": f"camera {role} not available"}, status_code=404)
    try:
        data = cam_path.read_bytes()
    except OSError:
        return JSONResponse({"error": "read failed"}, status_code=503)
    from starlette.responses import Response

    return Response(content=data, media_type="image/jpeg", headers=_NO_CACHE)


class MomentSearchRequest(BaseModel):
    query: str
    limit: int = 10


@router.post("/studio/moments/search")
async def search_moments(req: MomentSearchRequest):
    """Semantic search over studio_moments via CLAP text embedding.

    Accepts natural language queries like "jazzy piano loop with horns"
    and returns ranked audio moments from Qdrant.
    """

    results = await asyncio.to_thread(_search_moments_sync, req.query, req.limit)
    return JSONResponse(content=results)


def _search_moments_sync(query: str, limit: int) -> list[dict]:
    """Synchronous CLAP search against Qdrant studio_moments."""
    try:
        from shared.clap import embed_text
        from shared.config import STUDIO_MOMENTS_COLLECTION, get_qdrant
    except ImportError:
        return []

    try:
        text_embedding = embed_text(query)
        client = get_qdrant()
        results = client.search(
            collection_name=STUDIO_MOMENTS_COLLECTION,
            query_vector=text_embedding.tolist(),
            limit=limit,
        )
        return [
            {
                "id": str(r.id),
                "score": round(r.score, 4),
                "payload": r.payload,
            }
            for r in results
        ]
    except (ValueError, KeyError, TypeError, RuntimeError, OSError):
        return []
