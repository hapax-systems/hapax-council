"""Studio effect graph routes — shader presets, node management, modulations.

Extracted from studio.py to keep route files manageable.
These routes share the _graph_runtime and _shader_registry globals from studio.py.
"""

from __future__ import annotations

import json as _json_mod
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from agents.studio_compositor.graph_mutation_bus import write_graph_mutation

log = logging.getLogger(__name__)

_BUILTIN_PRESETS = Path(__file__).parent.parent.parent.parent / "presets"
_USER_PRESETS = Path.home() / ".config" / "hapax" / "effect-presets"

COMPOSITOR_LAYER_DIR = Path("/dev/shm/hapax-compositor")
COMPOSITOR_STATUS_PATH = Path("/dev/shm/hapax-compositor/status.json")

router = APIRouter(prefix="/api", tags=["studio-effects"])


# Livestream-performance-map W4.5 / Sprint 7 P1: per-stage command
# latency histogram for the studio effect-graph mutation pipeline. Lazy
# init avoids polluting test environments without prometheus_client.
# The histogram registers on the default REGISTRY so the existing
# prometheus_fastapi_instrumentator /metrics endpoint exposes it without
# additional wiring.
#
# Stages (all measured at the FastAPI handler):
#   - validate     — Pydantic parse + EffectGraph / GraphPatch construction
#   - runtime_load — graph_runtime.load_graph / apply_patch
#   - ipc_write    — write to /dev/shm/hapax-compositor/graph-mutation.json
#   - total        — full handler from entry to return
#
# The downstream stages (compositor inotify wake → WGSL compile → first
# frame) live in a separate process; a Wave 5 follow-up will instrument
# them on the compositor side and the operator can sum medians for an
# end-to-end estimate. This PR captures the FastAPI-side stages, which
# is where the operator's command actions originate.
_LATENCY_BUCKETS_MS: tuple[float, ...] = (
    1.0,
    2.0,
    5.0,
    10.0,
    20.0,
    50.0,
    100.0,
    200.0,
    500.0,
    1000.0,
    2000.0,
)
_COMMAND_LATENCY: Any = None
_COMMAND_LATENCY_INIT_FAILED = False


def _command_latency() -> Any:
    """Return the lazy-init Histogram, or None if prometheus_client is unavailable."""
    global _COMMAND_LATENCY, _COMMAND_LATENCY_INIT_FAILED
    if _COMMAND_LATENCY is not None or _COMMAND_LATENCY_INIT_FAILED:
        return _COMMAND_LATENCY
    try:
        from prometheus_client import Histogram

        _COMMAND_LATENCY = Histogram(
            "logos_command_latency_ms",
            "Per-stage latency for the studio effect-graph command pipeline (FastAPI handler stages)",
            ["command", "stage"],
            buckets=_LATENCY_BUCKETS_MS,
        )
    except Exception:
        log.debug("logos_command_latency_ms init failed", exc_info=True)
        _COMMAND_LATENCY_INIT_FAILED = True
    return _COMMAND_LATENCY


def _observe_stage(command: str, stage: str, dt_ms: float) -> None:
    hist = _command_latency()
    if hist is None:
        return
    try:
        hist.labels(command=command, stage=stage).observe(dt_ms)
    except Exception:
        log.debug("logos_command_latency_ms observe failed", exc_info=True)


def _get_runtime():
    """Get graph runtime from studio module (avoids circular import)."""
    from logos.api.routes.studio import _graph_runtime

    return _graph_runtime


def _get_registry():
    """Get shader registry from studio module."""
    from logos.api.routes.studio import _shader_registry

    return _shader_registry


def _load_preset(name: str) -> object:
    from agents.effect_graph.types import EffectGraph

    for d in (_USER_PRESETS, _BUILTIN_PRESETS):
        p = d / f"{name}.json"
        if p.is_file():
            return EffectGraph(**_json_mod.loads(p.read_text()))
    return None


@router.get("/studio/effect/graph")
async def get_effect_graph():
    rt = _get_runtime()
    return rt.get_graph_state() if rt else {"graph": None}


@router.put("/studio/effect/graph")
async def replace_effect_graph(request: dict[str, object]):
    from agents.effect_graph.types import EffectGraph

    # Drop #48 API-1/API-2: mutation-bus is the authoritative path.
    # Previously this handler called `rt.load_graph(graph)` directly
    # in-process AND wrote the mutation file, causing the compositor to
    # apply the same graph twice (once synchronously on the FastAPI
    # worker thread, once ~50-100 ms later from `state_reader_loop`'s
    # 10 Hz poll of graph-mutation.json). The in-process double-apply
    # wasted 5-7 ms of control-plane work per PUT per drop #46
    # measurement. Consolidating on the mutation-bus path also makes
    # this handler consistent with chat_reactor + random_mode, which
    # already write to the same bus.
    #
    # Caller-visible contract change: this handler no longer guarantees
    # the graph is active by the time the response returns; the
    # compositor picks it up on its next 10 Hz poll (worst-case 100 ms
    # latency). Operator-facing tools (chain builder, API) observe the
    # activation via subsequent GET /studio/effect/graph reads, which
    # return the in-process state from `rt.get_graph_state()` — that's
    # updated from the same mutation bus, so consistency holds at the
    # operator-visible layer.
    t_start = time.perf_counter()
    rt = _get_runtime()
    if not rt:
        raise HTTPException(503, "Compositor not available")
    # Extract source before validating as EffectGraph (source is not a graph field)
    source = str(request.pop("fx_source", request.pop("_source", "live")))
    try:
        graph = EffectGraph(**request)
        t_validate = time.perf_counter()
        _observe_stage("replace_graph", "validate", (t_validate - t_start) * 1000.0)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    try:
        mutation_path = Path("/dev/shm/hapax-compositor/graph-mutation.json")
        write_graph_mutation(graph.model_dump(), path=mutation_path)
        # Write source selection alongside graph mutation
        source_path = Path("/dev/shm/hapax-compositor/fx-source.txt")
        source_path.write_text(source)
        t_ipc = time.perf_counter()
        _observe_stage("replace_graph", "ipc_write", (t_ipc - t_validate) * 1000.0)
    except OSError:
        pass
    _observe_stage("replace_graph", "total", (time.perf_counter() - t_start) * 1000.0)
    return {"status": "ok"}


@router.patch("/studio/effect/graph")
async def patch_effect_graph(request: dict[str, object]):
    from agents.effect_graph.types import GraphPatch

    t_start = time.perf_counter()
    rt = _get_runtime()
    if not rt:
        raise HTTPException(503, "Compositor not available")
    try:
        patch = GraphPatch(**request)
        t_validate = time.perf_counter()
        _observe_stage("patch_graph", "validate", (t_validate - t_start) * 1000.0)
        rt.apply_patch(patch)
        _observe_stage("patch_graph", "runtime_load", (time.perf_counter() - t_validate) * 1000.0)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    _observe_stage("patch_graph", "total", (time.perf_counter() - t_start) * 1000.0)
    return {"status": "ok"}


@router.patch("/studio/effect/graph/node/{node_id}/params")
async def patch_node_params(node_id: str, params: dict[str, object]):
    rt = _get_runtime()
    if not rt:
        raise HTTPException(503, "Compositor not available")
    rt.patch_node_params(node_id, params)
    return {"status": "ok"}


@router.delete("/studio/effect/graph/node/{node_id}")
async def remove_graph_node(node_id: str):
    from agents.effect_graph.compiler import GraphValidationError

    rt = _get_runtime()
    if not rt:
        raise HTTPException(503, "Compositor not available")
    try:
        rt.remove_node(node_id)
    except GraphValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "ok"}


@router.put("/studio/effect/graph/modulations")
async def replace_modulations(bindings: list[dict[str, object]]):
    from agents.effect_graph.types import ModulationBinding

    rt = _get_runtime()
    if not rt:
        raise HTTPException(503, "Compositor not available")
    # Drop #48 API-7: dispatch the mutation onto the GLib main loop so it
    # serializes with tick_modulator's per-frame iteration of
    # modulator.bindings. Previously this ran on the FastAPI worker thread
    # and races with the main-loop reader; CPython GIL makes list
    # assignment atomic but iteration semantics are fragile. GLib.idle_add
    # returns False so the callback fires once and drops.
    parsed = [ModulationBinding(**b) for b in bindings]
    try:
        import gi

        gi.require_version("GLib", "2.0")
        from gi.repository import GLib  # type: ignore[attr-defined]

        def _apply() -> bool:
            rt.modulator.replace_all(parsed)
            return False

        GLib.idle_add(_apply)
    except (ImportError, ValueError):
        # GLib unavailable (test environment, etc.) — fall back to direct
        # apply. Accepts the latent race under the same terms as before
        # this fix.
        rt.modulator.replace_all(parsed)
    return {"status": "ok"}


@router.get("/studio/effect/graph/modulations")
async def get_modulations():
    rt = _get_runtime()
    if not rt:
        return {"bindings": []}
    return {"bindings": [b.model_dump() for b in rt.modulator.bindings]}


@router.get("/studio/presets")
async def list_presets():
    seen: set[str] = set()
    result = []
    for d in (_USER_PRESETS, _BUILTIN_PRESETS):
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            if p.name.startswith("_"):
                continue
            if p.stem not in seen:
                seen.add(p.stem)
                try:
                    raw = _json_mod.loads(p.read_text())
                    result.append(
                        {
                            "name": p.stem,
                            "display_name": raw.get("name", p.stem),
                            "description": raw.get("description", ""),
                        }
                    )
                except Exception:
                    pass
    return {"presets": result}


@router.get("/studio/presets/{name}")
async def get_preset(name: str):
    p = _load_preset(name)
    if not p:
        raise HTTPException(404, f"Preset not found: {name}")
    return p.model_dump()


@router.post("/studio/presets/{name}/activate")
async def activate_preset(name: str):
    p = _load_preset(name)
    if not p:
        raise HTTPException(404, f"Preset not found: {name}")
    rt = _get_runtime()
    if not rt:
        raise HTTPException(503, "Compositor not available")
    try:
        rt.load_graph(p)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    try:
        fx_req = Path("/dev/shm/hapax-compositor/fx-request.txt")
        fx_req.parent.mkdir(parents=True, exist_ok=True)
        fx_req.write_text(name)
    except OSError:
        pass
    return {"status": "ok", "name": p.name}


@router.post("/studio/presets")
async def create_preset(request: dict[str, object]):
    """Save a preset JSON to the user preset directory."""
    name = request.get("name")
    if not name or not isinstance(name, str):
        raise HTTPException(400, "Missing or invalid 'name' field")
    # Sanitize filename
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_").strip()
    if not safe_name:
        raise HTTPException(400, "Invalid preset name")
    _USER_PRESETS.mkdir(parents=True, exist_ok=True)
    path = _USER_PRESETS / f"{safe_name}.json"
    try:
        path.write_text(_json_mod.dumps(request, indent=2))
    except OSError as e:
        raise HTTPException(503, f"Failed to write preset: {e}") from e
    return {"status": "saved", "name": safe_name, "path": str(path)}


@router.get("/studio/effect/nodes")
async def list_node_types():
    reg = _get_registry()
    return {"nodes": reg.all_schemas()} if reg else {"nodes": {}}


@router.get("/studio/effect/nodes/{node_type}")
async def get_node_type(node_type: str):
    reg = _get_registry()
    if not reg:
        raise HTTPException(503, "Registry not available")
    s = reg.schema(node_type)
    if not s:
        raise HTTPException(404, f"Unknown: {node_type}")
    return s


@router.patch("/studio/layer/{layer}/enabled")
async def set_layer_enabled(layer: str, body: dict[str, object]):
    if layer not in ("live", "smooth", "hls"):
        raise HTTPException(400, f"Invalid layer: {layer}")
    enabled = body.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(400, "Body must contain 'enabled' boolean")
    flag_path = COMPOSITOR_LAYER_DIR / f"layer-{layer}-enabled.txt"
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text("1" if enabled else "0")
    return {"layer": layer, "enabled": enabled}


@router.patch("/studio/layer/smooth/delay")
async def set_smooth_delay(body: dict[str, object]):
    delay = body.get("delay_seconds")
    if not isinstance(delay, (int, float)) or delay < 0 or delay > 30:
        raise HTTPException(400, "'delay_seconds' must be a number between 0 and 30")
    flag_path = COMPOSITOR_LAYER_DIR / "smooth-delay.txt"
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text(str(float(delay)))
    return {"delay_seconds": float(delay)}


@router.put("/studio/presets/{name}")
async def save_preset(name: str, body: dict[str, object]):
    from agents.effect_graph.types import EffectGraph

    if body:
        try:
            graph = EffectGraph(**body)
        except Exception as e:
            raise HTTPException(400, f"Invalid graph: {e}") from e
    else:
        rt = _get_runtime()
        if rt and rt.current_graph:
            graph = rt.current_graph
        else:
            raise HTTPException(400, "No graph data provided and no active graph")

    _USER_PRESETS.mkdir(parents=True, exist_ok=True)
    preset_path = _USER_PRESETS / f"{name}.json"
    preset_path.write_text(_json_mod.dumps(graph.model_dump(), indent=2))
    return {"status": "saved", "name": name, "path": str(preset_path)}


@router.delete("/studio/presets/{name}")
async def delete_preset(name: str):
    preset_path = _USER_PRESETS / f"{name}.json"
    if not preset_path.is_file():
        builtin = _BUILTIN_PRESETS / f"{name}.json"
        if builtin.is_file():
            raise HTTPException(403, "Cannot delete built-in preset")
        raise HTTPException(404, f"Preset not found: {name}")
    preset_path.unlink()
    return {"status": "deleted", "name": name}


@router.get("/studio/cameras")
async def list_cameras():
    import json

    if not COMPOSITOR_STATUS_PATH.exists():
        return {"cameras": []}
    try:
        data = json.loads(COMPOSITOR_STATUS_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"cameras": []}
    return {"cameras": data.get("cameras", {})}


@router.post("/studio/camera/select")
async def select_camera(body: dict[str, object]):
    role = body.get("role")
    if not role or not isinstance(role, str):
        raise HTTPException(400, "'role' string required")
    flag_path = COMPOSITOR_LAYER_DIR / "hero-camera.txt"
    flag_path.parent.mkdir(parents=True, exist_ok=True)
    flag_path.write_text(role)
    return {"status": "ok", "hero": role}
