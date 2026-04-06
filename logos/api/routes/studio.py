"""Studio ingestion endpoints — audio/video capture and classification data.

Serves cached studio snapshot data and provides CLAP-based semantic
search over the studio_moments Qdrant collection.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter

if TYPE_CHECKING:
    from agents.effect_graph.registry import ShaderRegistry
    from agents.effect_graph.runtime import GraphRuntime
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from logos.api.cache import cache

_graph_runtime: GraphRuntime | None = None
_shader_registry: ShaderRegistry | None = None


def set_graph_runtime(runtime: GraphRuntime) -> None:
    global _graph_runtime
    _graph_runtime = runtime


def set_shader_registry(registry: ShaderRegistry) -> None:
    global _shader_registry
    _shader_registry = registry


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


def _to_dict(obj: object) -> object:
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_to_dict(item) for item in obj]
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "__dataclass_fields__"):
        return asdict(obj, dict_factory=_dict_factory)  # type: ignore[arg-type]
    return obj


def _slow_response(data: object) -> JSONResponse:
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
RECORDING_CONTROL = Path("/dev/shm/hapax-compositor/recording-control.txt")


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


_OFFLINE_PLACEHOLDER = Path(__file__).parent.parent / "static" / "camera-offline.jpg"


_COMPOSITOR_DIR = Path("/dev/shm/hapax-compositor")


def _safe_compositor_path(name: str) -> Path | None:
    """Resolve a camera/feed name to a compositor path, rejecting traversal."""
    candidate = (_COMPOSITOR_DIR / f"{name}.jpg").resolve()
    if not candidate.is_relative_to(_COMPOSITOR_DIR):
        return None
    return candidate


@router.get("/studio/stream/camera/{role}")
async def camera_snapshot(role: str):
    """Single JPEG snapshot of an individual camera feed.

    Returns an 'OFFLINE' placeholder image (200) instead of 404 when
    the camera snapshot file doesn't exist, so the frontend always gets
    a valid image and can display a clear offline state.
    """
    cam_path = _safe_compositor_path(role)
    if cam_path is None:
        return JSONResponse({"error": "invalid role"}, status_code=400)
    if not cam_path.exists():
        if _OFFLINE_PLACEHOLDER.exists():
            from starlette.responses import Response

            return Response(
                content=_OFFLINE_PLACEHOLDER.read_bytes(),
                media_type="image/jpeg",
                headers={**_NO_CACHE, "X-Camera-Status": "offline"},
            )
        return JSONResponse({"error": f"camera {role} not available"}, status_code=404)
    try:
        data = cam_path.read_bytes()
    except OSError:
        return JSONResponse({"error": "read failed"}, status_code=503)
    from starlette.responses import Response

    return Response(content=data, media_type="image/jpeg", headers=_NO_CACHE)


@router.get("/studio/stream/cameras/batch")
async def camera_batch_snapshot(roles: str = ""):
    """Batch JPEG snapshots of multiple cameras in a single multipart response.

    Reduces N HTTP round trips to 1 for camera grid views.
    Query: ?roles=brio-desk,c920-hw,...  (comma-separated camera roles)
    Returns multipart/mixed with one JPEG part per camera.
    """
    from starlette.responses import Response

    if not roles:
        return JSONResponse({"error": "roles parameter required"}, status_code=400)

    role_list = [r.strip() for r in roles.split(",") if r.strip()]
    if not role_list:
        return JSONResponse({"error": "no valid roles"}, status_code=400)

    boundary = "hapax-batch"

    # Pre-read all camera JPEGs into memory to minimize inter-frame skew
    snapshots: list[tuple[str, bytes]] = []
    for role in role_list:
        cam_path = _safe_compositor_path(role)
        if cam_path is None or not cam_path.exists():
            continue
        try:
            snapshots.append((role, cam_path.read_bytes()))
        except OSError:
            continue

    parts: list[bytes] = []
    for role, data in snapshots:
        header = (
            f"--{boundary}\r\n"
            f"Content-Type: image/jpeg\r\n"
            f'Content-Disposition: attachment; name="{role}"\r\n'
            f"Content-Length: {len(data)}\r\n"
            f"\r\n"
        ).encode()
        parts.append(header + data + b"\r\n")

    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    return Response(
        content=body,
        media_type=f"multipart/mixed; boundary={boundary}",
        headers=_NO_CACHE,
    )


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
        from logos._clap import embed_text
        from logos.api.routes._config import STUDIO_MOMENTS_COLLECTION, get_qdrant
    except ImportError:
        return []

    try:
        text_embedding = embed_text(query)
        client = get_qdrant()
        results = client.query_points(
            collection_name=STUDIO_MOMENTS_COLLECTION,
            query=text_embedding.tolist(),
            limit=limit,
        ).points
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
                if len(data) > 100 and data[:2] == b"\xff\xd8":  # valid JPEG SOI
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
        path = _safe_compositor_path(feed)
        if path is None:
            return JSONResponse({"error": "invalid feed name"}, status_code=400)
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
    try:
        data = FX_SNAPSHOT_PATH.read_bytes()
    except (OSError, FileNotFoundError):
        return JSONResponse({"error": "FX pipeline not running"}, status_code=503)
    from starlette.responses import Response

    return Response(content=data, media_type="image/jpeg", headers=_NO_CACHE)


@router.get("/studio/effect/current")
async def get_current_effect():
    """Return the currently active visual effect preset name."""
    current_path = Path("/dev/shm/hapax-compositor/fx-current.txt")
    preset = "clean"
    if current_path.exists():
        try:
            preset = current_path.read_text().strip() or "clean"
        except OSError:
            pass
    from agents.studio_compositor.effects import get_available_preset_names

    available = sorted(get_available_preset_names())
    return {"preset": preset, "available": available}


class EffectSelectRequest(BaseModel):
    preset: str
    fx_source: str = "live"

    model_config = {"extra": "allow"}


@router.post("/studio/effect/select")
async def select_effect(req: EffectSelectRequest):
    """Request the compositor to switch to a different visual effect preset."""
    fx_request = Path("/dev/shm/hapax-compositor/fx-request.txt")
    try:
        # Read previous preset for trace context
        prev = ""
        try:
            from logos._telemetry import trace_compositor_effect

            prev_file = Path("/dev/shm/hapax-compositor/fx-current.txt")
            if prev_file.exists():
                prev = prev_file.read_text().strip()
            trace_compositor_effect(preset=req.preset, prev_preset=prev)
        except Exception:
            pass
        fx_request.write_text(req.preset)
        # Write source selection for input-selector switching
        source_path = Path("/dev/shm/hapax-compositor/fx-source.txt")
        source_path.write_text(req.fx_source)
        return {"status": "requested", "preset": req.preset}
    except OSError:
        return JSONResponse({"error": "write failed"}, status_code=503)


COMPOSITOR_STATUS_PATH = Path.home() / ".cache" / "hapax-compositor" / "status.json"


@router.get("/studio/compositor/live")
async def compositor_live():
    """Live compositor status — read from status.json written by the compositor."""
    import json

    if not COMPOSITOR_STATUS_PATH.exists():
        return JSONResponse({"error": "compositor not running"}, status_code=503)
    try:
        data = json.loads(COMPOSITOR_STATUS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return JSONResponse({"error": "status read failed"}, status_code=503)

    # Read audio energy from perception state for the audio_energy_rms field
    audio_rms = 0.0
    try:
        perc_path = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
        if perc_path.exists():
            perc = json.loads(perc_path.read_text())
            audio_rms = perc.get("audio_energy_rms", 0.0)
    except (json.JSONDecodeError, OSError):
        pass

    return {
        "state": data.get("state", "unknown"),
        "cameras": data.get("cameras", {}),
        "active_cameras": data.get("active_cameras", 0),
        "total_cameras": data.get("total_cameras", 0),
        "recording_enabled": data.get("recording_enabled", False),
        "recording_cameras": data.get("recording_cameras", {}),
        "hls_enabled": data.get("hls_enabled", False),
        "consent_recording_allowed": data.get("consent_recording_allowed", True),
        "guest_present": data.get("guest_present", False),
        "consent_phase": data.get("consent_phase", "no_guest"),
        "audio_energy_rms": audio_rms,
        "timestamp": data.get("timestamp", 0),
    }


@router.post("/studio/recording/enable")
async def enable_recording():
    """Enable recording via compositor control file."""
    RECORDING_CONTROL.parent.mkdir(parents=True, exist_ok=True)
    RECORDING_CONTROL.write_text("1")
    return {"recording": True}


@router.post("/studio/recording/disable")
async def disable_recording():
    """Disable recording via compositor control file."""
    RECORDING_CONTROL.parent.mkdir(parents=True, exist_ok=True)
    RECORDING_CONTROL.write_text("0")
    return {"recording": False}


@router.get("/studio/disk")
async def studio_disk():
    """Disk usage for the video recording directory."""
    import shutil

    rec_dir = Path.home() / ".cache" / "hapax-compositor" / "recordings"
    target = rec_dir if rec_dir.exists() else Path.home()
    usage = shutil.disk_usage(str(target))
    return {
        "path": str(target),
        "total_gb": round(usage.total / (1024**3), 1),
        "used_gb": round(usage.used / (1024**3), 1),
        "free_gb": round(usage.free / (1024**3), 1),
    }


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


@router.post("/studio/vinyl-mode/toggle")
async def toggle_vinyl_mode():
    """Toggle vinyl mode for half-speed content reactivity."""
    toggle_path = Path("/dev/shm/hapax-compositor/vinyl-mode.txt")
    try:
        current = toggle_path.read_text().strip() == "true" if toggle_path.exists() else False
        new_state = not current
        toggle_path.write_text("true" if new_state else "false")
        return {"vinyl_mode": new_state}
    except OSError:
        return JSONResponse({"error": "write failed"}, status_code=503)


@router.get("/studio/vinyl-mode")
async def get_vinyl_mode():
    """Current vinyl mode state."""
    toggle_path = Path("/dev/shm/hapax-compositor/vinyl-mode.txt")
    enabled = toggle_path.read_text().strip() == "true" if toggle_path.exists() else False
    return {"vinyl_mode": enabled}


@router.post("/studio/visual-layer/toggle")
async def toggle_visual_layer():
    """Toggle the visual layer overlay on/off in the compositor."""

    toggle_path = Path("/dev/shm/hapax-compositor/visual-layer-enabled.txt")
    try:
        current = toggle_path.read_text().strip() == "true" if toggle_path.exists() else True
        new_state = not current
        toggle_path.write_text("true" if new_state else "false")
        return {"enabled": new_state}
    except OSError:
        return JSONResponse({"error": "write failed"}, status_code=503)


@router.get("/studio/visual-layer")
async def get_visual_layer_state():
    """Current visual layer state from the aggregator.

    Returns the display state machine output: display state, zone opacities,
    active signals per category, and ambient shader parameters.
    """
    import json

    vl_path = Path("/dev/shm/hapax-compositor/visual-layer-state.json")
    if not vl_path.exists():
        return {
            "available": False,
            "display_state": "ambient",
            "zone_opacities": {},
            "signals": {},
            "ambient_params": {},
        }
    try:
        data = json.loads(vl_path.read_text())
        data["available"] = True
        return data
    except (json.JSONDecodeError, OSError):
        return {
            "available": False,
            "display_state": "ambient",
            "zone_opacities": {},
            "signals": {},
            "ambient_params": {},
        }


@router.get("/studio/perception")
async def get_perception_state():
    """Current perception state from the voice daemon.

    Returns operator presence, flow, emotion, interruptibility, and
    environmental sensing data.
    """
    import json as _json

    perc_path = Path.home() / ".cache" / "hapax-daimonion" / "perception-state.json"
    if not perc_path.exists():
        return {"available": False, "operator_present": False, "presence_score": 0.0}
    try:
        data = _json.loads(perc_path.read_text())
        data["available"] = True
        return data
    except (_json.JSONDecodeError, OSError):
        return {"available": False, "operator_present": False, "presence_score": 0.0}


@router.get("/studio/ambient-content")
async def get_ambient_content():
    """Ambient content pool for the visual layer aggregator.

    Sources profile facts from Qdrant and recent studio moments.
    Called infrequently (~every 5 min) by the aggregator to refresh its pool.
    """
    facts: list[str] = []
    moments: list[str] = []

    # Profile facts from Qdrant
    try:
        from logos.api.routes._config import get_qdrant

        client = get_qdrant()
        # Scroll random points from profile-facts collection
        result = client.scroll(
            collection_name="profile-facts",
            limit=30,
            with_payload=True,
        )
        points = result[0] if result else []
        for point in points:
            payload = point.payload or {}
            text = payload.get("text", payload.get("fact", ""))
            if text and len(text) > 10:
                facts.append(text[:100])
    except Exception:
        pass  # Qdrant may not be available

    # Studio moments (recent CLAP classifications)
    try:
        from logos.api.routes._config import STUDIO_MOMENTS_COLLECTION, get_qdrant

        client = get_qdrant()
        result = client.scroll(
            collection_name=STUDIO_MOMENTS_COLLECTION,
            limit=10,
            with_payload=True,
        )
        points = result[0] if result else []
        for point in points:
            payload = point.payload or {}
            labels = payload.get("top_labels", [])
            if labels:
                moments.append(", ".join(labels[:3]))
    except Exception:
        pass

    # Nudge titles for ambient text display
    nudge_titles: list[str] = []
    try:
        for nudge in cache.nudges[:5]:
            title = getattr(nudge, "title", "")
            if title:
                nudge_titles.append(title[:80])
    except Exception:
        pass

    # Weather conditions (if available from perception or cache)
    weather: str = ""
    try:
        import json as _json

        weather_path = Path.home() / ".cache" / "hapax" / "weather.json"
        if weather_path.exists():
            w = _json.loads(weather_path.read_text())
            condition = w.get("condition", "")
            temp = w.get("temperature_c")
            if condition:
                weather = f"{condition}"
                if temp is not None:
                    weather += f" {temp}°C"
    except Exception:
        pass

    return {
        "facts": facts,
        "moments": moments,
        "nudge_titles": nudge_titles,
        "weather": weather,
    }


class ActivityCorrectionRequest(BaseModel):
    label: str
    detail: str = ""


@router.post("/studio/activity-correction")
async def correct_activity(req: ActivityCorrectionRequest):
    """Operator corrects what Hapax thinks they are doing.

    Writes a correction file that the aggregator reads to override
    its activity inference for 30 minutes.
    """
    import json as _json
    import time as _time

    correction = {
        "label": req.label,
        "detail": req.detail,
        "timestamp": _time.time(),
        "ttl_s": 1800,  # 30 minutes
    }
    correction_path = Path("/dev/shm/hapax-compositor/activity-correction.json")
    try:
        correction_path.write_text(_json.dumps(correction))
    except OSError:
        return JSONResponse({"error": "write failed"}, status_code=503)
    from logos.api.routes._correction_sentinel import write_correction_sentinel

    write_correction_sentinel(correction)
    return {"status": "corrected", "label": req.label}


# --- Effect Node Graph API ---

# Effect graph routes, presets, layer control, and camera routes have been
# extracted to studio_effects.py. The effects_router must be included
# alongside this router in the app.
from logos.api.routes.studio_effects import router as effects_router  # noqa: E402, F401
