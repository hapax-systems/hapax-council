"""Studio effect graph routes — shader presets, node management, modulations.

Extracted from studio.py to keep route files manageable.
These routes share the _graph_runtime and _shader_registry globals from studio.py.
"""

from __future__ import annotations

import json as _json_mod
from pathlib import Path

from fastapi import APIRouter, HTTPException

_BUILTIN_PRESETS = Path(__file__).parent.parent.parent.parent / "presets"
_USER_PRESETS = Path.home() / ".config" / "hapax" / "effect-presets"

COMPOSITOR_LAYER_DIR = Path("/dev/shm/hapax-compositor")
COMPOSITOR_STATUS_PATH = Path("/dev/shm/hapax-compositor/status.json")

router = APIRouter(prefix="/api", tags=["studio-effects"])


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

    rt = _get_runtime()
    if not rt:
        raise HTTPException(503, "Compositor not available")
    try:
        graph = EffectGraph(**request)
        rt.load_graph(graph)
    except Exception as e:
        raise HTTPException(400, str(e)) from e
    try:
        mutation_path = Path("/dev/shm/hapax-compositor/graph-mutation.json")
        mutation_path.parent.mkdir(parents=True, exist_ok=True)
        mutation_path.write_text(_json_mod.dumps(graph.model_dump()))
    except OSError:
        pass
    return {"status": "ok"}


@router.patch("/studio/effect/graph")
async def patch_effect_graph(request: dict[str, object]):
    from agents.effect_graph.types import GraphPatch

    rt = _get_runtime()
    if not rt:
        raise HTTPException(503, "Compositor not available")
    try:
        rt.apply_patch(GraphPatch(**request))
    except Exception as e:
        raise HTTPException(400, str(e)) from e
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


@router.patch("/studio/layer/{layer}/palette")
async def set_layer_palette(layer: str, palette: dict[str, object]):
    from agents.effect_graph.types import LayerPalette

    if layer not in ("live", "smooth", "hls"):
        raise HTTPException(400, f"Invalid layer: {layer}")
    rt = _get_runtime()
    if not rt:
        raise HTTPException(503, "Compositor not available")
    rt.set_layer_palette(layer, LayerPalette(**palette))
    return {"status": "ok"}


@router.get("/studio/layer/status")
async def get_layer_status():
    rt = _get_runtime()
    if not rt:
        return {"layers": {}}
    return {"layers": {l: rt.get_layer_palette(l).model_dump() for l in ("live", "smooth", "hls")}}


@router.put("/studio/effect/graph/modulations")
async def replace_modulations(bindings: list[dict[str, object]]):
    from agents.effect_graph.types import ModulationBinding

    rt = _get_runtime()
    if not rt:
        raise HTTPException(503, "Compositor not available")
    rt.modulator.replace_all([ModulationBinding(**b) for b in bindings])
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
