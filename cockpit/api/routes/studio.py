"""Studio ingestion endpoints — audio/video capture and classification data.

Serves cached studio snapshot data and provides CLAP-based semantic
search over the studio_moments Qdrant collection.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import StreamingResponse

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


VISUAL_LAYER_STATE_PATH = Path("/dev/shm/hapax-compositor/visual-layer-state.json")


@router.get("/studio/visual-layer")
async def get_visual_layer():
    """Current visual communication layer state."""
    if not VISUAL_LAYER_STATE_PATH.exists():
        return JSONResponse(
            {
                "display_state": "ambient",
                "signals": {},
                "zone_opacities": {},
                "aggregator": "offline",
            },
            headers=_NO_CACHE,
        )
    try:
        data = json.loads(VISUAL_LAYER_STATE_PATH.read_text())
        return JSONResponse(content=data, headers=_NO_CACHE)
    except (json.JSONDecodeError, OSError):
        return JSONResponse({"error": "read failed"}, status_code=503, headers=_NO_CACHE)


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


FX_SNAPSHOT_PATH = Path("/dev/shm/hapax-compositor/fx-snapshot.jpg")

MJPEG_BOUNDARY = "hapax-frame"


async def _mjpeg_generator(path: Path, fps: float = 12.0):  # noqa: ANN201
    interval = 1.0 / fps
    last_mtime_ns = 0
    while True:
        try:
            st = path.stat()
            if st.st_mtime_ns != last_mtime_ns:
                data = path.read_bytes()
                last_mtime_ns = st.st_mtime_ns
                if len(data) > 100:
                    yield (
                        (
                            f"--{MJPEG_BOUNDARY}\r\n"
                            f"Content-Type: image/jpeg\r\n"
                            f"Content-Length: {len(data)}\r\n"
                            f"\r\n"
                        ).encode()
                        + data
                        + b"\r\n"
                    )
        except OSError:
            pass
        await asyncio.sleep(interval)


@router.get("/studio/stream/live/{feed}")
async def mjpeg_stream(feed: str, fps: float = 12.0):
    """MJPEG multipart stream for any feed (composite, fx, or camera role)."""
    feed_paths = {
        "composite": SNAPSHOT_PATH,
        "fx": FX_SNAPSHOT_PATH,
    }
    path = feed_paths.get(feed)
    if path is None:
        path = Path(f"/dev/shm/hapax-compositor/{feed}.jpg")
    if not path.exists():
        return JSONResponse({"error": f"feed '{feed}' not available"}, status_code=404)
    fps = min(max(fps, 1.0), 30.0)
    return StreamingResponse(
        _mjpeg_generator(path, fps),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
    )


@router.get("/studio/stream/fx")
async def fx_snapshot():
    """Single JPEG snapshot of the GPU-effected compositor output."""
    if not FX_SNAPSHOT_PATH.exists():
        return JSONResponse({"error": "FX pipeline not running"}, status_code=503)
    try:
        data = FX_SNAPSHOT_PATH.read_bytes()
    except OSError:
        return JSONResponse({"error": "read failed"}, status_code=503)
    from starlette.responses import Response

    return Response(content=data, media_type="image/jpeg", headers=_NO_CACHE)


@router.get("/studio/effect/current")
async def get_current_effect():
    """Return the currently active visual effect preset name."""
    return {
        "preset": "clean",
        "available": [
            "ghost",
            "trails",
            "screwed",
            "datamosh",
            "vhs",
            "neon",
            "trap",
            "diff",
            "clean",
        ],
    }


class EffectSelectRequest(BaseModel):
    preset: str


@router.post("/studio/effect/select")
async def select_effect(req: EffectSelectRequest):
    """Request the compositor to switch to a different visual effect preset."""
    fx_request = Path("/dev/shm/hapax-compositor/fx-request.txt")
    try:
        fx_request.write_text(req.preset)
        return {"status": "requested", "preset": req.preset}
    except OSError:
        return JSONResponse({"error": "write failed"}, status_code=503)


@router.get("/studio/consent")
async def get_consent_status():
    """Current consent state for video recording."""
    import json

    status_file = Path.home() / ".cache" / "hapax-compositor" / "status.json"
    if not status_file.exists():
        return {"recording_allowed": True, "guest_present": False, "phase": "no_guest"}
    try:
        data = json.loads(status_file.read_text())
        return {
            "recording_allowed": data.get("consent_recording_allowed", True),
            "guest_present": data.get("guest_present", False),
            "phase": data.get("consent_phase", "no_guest"),
        }
    except (json.JSONDecodeError, OSError):
        return {"recording_allowed": True, "guest_present": False, "phase": "no_guest"}


STATUS_FILE = Path.home() / ".cache" / "hapax-compositor" / "status.json"
VIDEO_RECORDING_DIR = Path.home() / "video-recording"
RECORDING_CONTROL_FILE = Path("/dev/shm/hapax-compositor/recording-control.txt")


@router.get("/studio/compositor/live")
async def compositor_live():
    """Direct status.json read for low-latency polling."""
    if not STATUS_FILE.exists():
        return JSONResponse({"state": "unknown"}, status_code=503)
    try:
        data = json.loads(STATUS_FILE.read_text())
        return data
    except (json.JSONDecodeError, OSError):
        return JSONResponse({"error": "read failed"}, status_code=503)


@router.get("/studio/disk")
async def studio_disk():
    """Disk usage for ~/video-recording."""
    path = VIDEO_RECORDING_DIR
    if not path.exists():
        path = Path.home()
    usage = shutil.disk_usage(path)
    return {
        "path": str(VIDEO_RECORDING_DIR),
        "total_gb": round(usage.total / (1024**3), 1),
        "used_gb": round(usage.used / (1024**3), 1),
        "free_gb": round(usage.free / (1024**3), 1),
    }


@router.post("/studio/recording/enable")
async def enable_recording():
    """Request compositor to enable recording."""
    try:
        RECORDING_CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
        RECORDING_CONTROL_FILE.write_text("enable")
        return {"status": "requested", "command": "enable"}
    except OSError:
        return JSONResponse({"error": "write failed"}, status_code=503)


@router.post("/studio/recording/disable")
async def disable_recording():
    """Request compositor to disable recording."""
    try:
        RECORDING_CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
        RECORDING_CONTROL_FILE.write_text("disable")
        return {"status": "requested", "command": "disable"}
    except OSError:
        return JSONResponse({"error": "write failed"}, status_code=503)
