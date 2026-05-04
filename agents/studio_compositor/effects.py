"""Effect graph integration for the compositor."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Legacy preset name -> graph file name mapping
GRAPH_PRESET_ALIASES: dict[str, str] = {
    "ascii": "ascii_preset",
    "diff": "diff_preset",
    "feedback": "feedback_preset",
    "glitchblocks": "glitch_blocks_preset",
    "halftone": "halftone_preset",
    "pixsort": "pixsort_preset",
    "slitscan": "slitscan_preset",
    "thermal": "thermal_preset",
    "vhs": "vhs_preset",
}


def init_graph_runtime(compositor: Any) -> Any:
    """Initialize the effect node graph system."""
    try:
        from agents.effect_graph.compiler import GraphCompiler
        from agents.effect_graph.modulator import UniformModulator
        from agents.effect_graph.registry import ShaderRegistry
        from agents.effect_graph.runtime import GraphRuntime

        shader_nodes_dir = Path(__file__).parent.parent / "shaders" / "nodes"
        registry = ShaderRegistry(shader_nodes_dir)
        compiler = GraphCompiler(registry)
        modulator = UniformModulator()
        runtime = GraphRuntime(registry=registry, compiler=compiler, modulator=modulator)

        runtime._on_params_changed = compositor._on_graph_params_changed
        runtime._on_plan_changed = compositor._on_graph_plan_changed

        try:
            from logos.api.routes.studio import set_graph_runtime, set_shader_registry

            set_graph_runtime(runtime)
            set_shader_registry(registry)
        except ImportError:
            log.debug("API routes not available — graph runtime not exposed")

        log.info("Effect node graph: %d node types loaded", len(registry.node_types))
        return runtime
    except Exception:
        log.warning("Effect node graph system not available", exc_info=True)
        return None


def try_graph_preset(compositor: Any, name: str) -> bool:
    """Try to load a graph-based preset. Returns True if found and loaded.

    HOMAGE Phase 6 Layer 5 — on a successful load, when the preset's
    family (see ``preset_family_selector.family_for_preset``) differs
    from the compositor's last-published family, publish a
    ``FXEvent(kind="preset_family_change", preset_family=<new>)`` to the
    ward↔FX bus so ward Cairo sources can react with an accent pulse.
    Same-family reloads are silent.
    """
    candidates = [name]
    alias = GRAPH_PRESET_ALIASES.get(name)
    if alias:
        candidates.append(alias)

    for dir_ in (
        Path.home() / ".config" / "hapax" / "effect-presets",
        Path(__file__).parent.parent.parent / "presets",
    ):
        for candidate in candidates:
            preset_path = dir_ / f"{candidate}.json"
            if preset_path.is_file():
                try:
                    from agents.effect_graph.types import EffectGraph

                    raw = json.loads(preset_path.read_text())
                    graph = EffectGraph(**raw)
                    graph = merge_default_modulations(graph)
                    compositor._graph_runtime.load_graph(graph)
                    log.info("Activated graph preset: %s (file: %s)", name, candidate)
                    _maybe_publish_family_change(compositor, name, candidate)
                    return True
                except Exception:
                    log.warning("Failed to load graph preset %s", candidate, exc_info=True)
    return False


def _maybe_publish_family_change(compositor: Any, name: str, candidate: str) -> None:
    """Publish ``FXEvent(kind="preset_family_change")`` when the family changes.

    Best-effort: any failure — bus import error, unknown preset, missing
    compositor attribute — falls open silently. Preset → family lookup
    tries the requested name first, then the resolved-from-alias
    candidate, so both legacy aliases and canonical filenames are
    classified correctly.
    """
    try:
        from agents.studio_compositor.preset_family_selector import family_for_preset
        from shared.ward_fx_bus import FXEvent, get_bus
    except Exception:
        log.debug("ward_fx_bus import failed; skipping family change publish", exc_info=True)
        return
    family = family_for_preset(name) or family_for_preset(candidate)
    if family is None:
        # Uncatalogued preset: don't publish a family change. The slot
        # selector simply stays on its last-known family for routing.
        return
    last = getattr(compositor, "_fx_last_published_family", None)
    if last == family:
        return
    compositor._fx_last_published_family = family
    try:
        get_bus().publish_fx(FXEvent(kind="preset_family_change", preset_family=family))
    except Exception:
        log.debug("ward_fx_bus publish_fx failed", exc_info=True)


def merge_default_modulations(graph: Any) -> Any:
    """Merge default modulation template into a graph's modulations."""
    template_path = Path(__file__).parent.parent.parent / "presets" / "_default_modulations.json"
    if not template_path.is_file():
        return graph

    try:
        defaults = json.loads(template_path.read_text()).get("default_modulations", [])
    except Exception:
        return graph

    existing = {(m.node, m.param) for m in graph.modulations}

    # Drop #47 DR-5: direct type→node_id map. Previously this built a
    # dict[str, list[str]] + picked `[-1]` to handle prefixed IDs in
    # multi-instance preset chains ('p0_bloom' + 'p1_bloom' → slot 'bloom').
    # No production preset uses that chain composition path and every live
    # preset has unique (node_id, node_type) mappings, so a flat dict
    # assignment (last-wins on any future duplicate) preserves the original
    # semantics with no list bookkeeping.
    type_to_id: dict[str, str] = {node.type: nid for nid, node in graph.nodes.items()}

    from agents.effect_graph.types import ModulationBinding

    merged = list(graph.modulations)
    for d in defaults:
        if "node" not in d or "param" not in d:
            continue  # skip comment entries
        target_type = d["node"]
        node_id = type_to_id.get(target_type)
        if node_id is None:
            continue
        key = (node_id, d["param"])
        if key not in existing:
            merged.append(
                ModulationBinding(
                    node=node_id,
                    param=d["param"],
                    source=d["source"],
                    scale=d.get("scale", 1.0),
                    offset=d.get("offset", 0.0),
                    smoothing=d.get("smoothing", 0.85),
                    attack=d.get("attack"),
                    decay=d.get("decay"),
                )
            )

    return graph.model_copy(update={"modulations": merged})


def get_available_preset_names() -> set[str]:
    """Return set of preset names that exist on disk."""
    names: set[str] = set()
    for dir_ in (
        Path.home() / ".config" / "hapax" / "effect-presets",
        Path(__file__).parent.parent.parent / "presets",
    ):
        if dir_.is_dir():
            for f in dir_.glob("*.json"):
                if not f.name.startswith("_"):
                    names.add(f.stem)
    return names
