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
    """Try to load a graph-based preset. Returns True if found and loaded."""
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
                    return True
                except Exception:
                    log.warning("Failed to load graph preset %s", candidate, exc_info=True)
    return False


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
    graph_nodes = set(graph.nodes.keys())

    from agents.effect_graph.types import ModulationBinding

    merged = list(graph.modulations)
    for d in defaults:
        key = (d["node"], d["param"])
        if key not in existing and d["node"] in graph_nodes:
            merged.append(ModulationBinding(**d))

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


def switch_fx_preset(compositor: Any, preset_name: str) -> None:
    """Switch the active visual effect preset at runtime."""
    from agents.studio_effects import PRESETS

    preset = PRESETS.get(preset_name)
    if preset is None:
        log.warning("Unknown FX preset: %s", preset_name)
        return
    if preset_name == compositor._fx_active_preset:
        return

    Gst = compositor._Gst

    if preset.use_glow:
        compositor._fx_glow_effect.set_property("effect", 15)
    elif preset.use_sobel:
        compositor._fx_glow_effect.set_property("effect", 16)
    else:
        compositor._fx_glow_effect.set_property("effect", 0)

    pp = preset.post_process
    pp_uniforms = Gst.Structure.from_string(
        f"uniforms, u_vignette_strength=(float){pp.vignette_strength}, "
        f"u_scanline_alpha=(float){pp.scanline_alpha}, "
        f"u_time=(float)0.0, "
        f"u_band_active=(float)0.0, "
        f"u_band_y=(float)0.0, u_band_height=(float)0.0, u_band_shift=(float)0.0, "
        f"u_syrup_active=(float){1.0 if pp.syrup_gradient else 0.0}, "
        f"u_syrup_color_r=(float){pp.syrup_color[0]}, "
        f"u_syrup_color_g=(float){pp.syrup_color[1]}, "
        f"u_syrup_color_b=(float){pp.syrup_color[2]}"
    )
    compositor._fx_post_proc.set_property("uniforms", pp_uniforms[0])

    trail = preset.trail
    if compositor._fx_temporal is not None:
        if trail.count > 0 and trail.opacity > 0:
            compositor._fx_temporal.set_property("feedback-amount", trail.opacity)
            fp = trail.filter_params
            if "decay_r" in fp:
                compositor._fx_temporal.set_property("decay-r", min(fp["decay_r"], 0.99))
                compositor._fx_temporal.set_property("decay-g", min(fp["decay_g"], 0.99))
                compositor._fx_temporal.set_property("decay-b", min(fp["decay_b"], 0.99))
            else:
                decay_base = fp.get("brightness", 0.7)
                compositor._fx_temporal.set_property("decay-r", min(decay_base * 1.0, 0.99))
                compositor._fx_temporal.set_property("decay-g", min(decay_base * 0.98, 0.99))
                compositor._fx_temporal.set_property("decay-b", min(decay_base * 0.96, 0.99))
            compositor._fx_temporal.set_property("hue-shift", fp.get("hue_rotate", 0.0))
            blend_map = {"add": 0, "multiply": 1, "difference": 2, "source-over": 3}
            compositor._fx_temporal.set_property("blend-mode", blend_map.get(trail.blend_mode, 0))
        else:
            compositor._fx_temporal.set_property("feedback-amount", 0.0)

    st = preset.stutter
    if st:
        compositor._fx_stutter.set_property("check-interval", st.check_interval)
        compositor._fx_stutter.set_property("freeze-chance", st.freeze_chance)
        compositor._fx_stutter.set_property("freeze-min", st.freeze_min)
        compositor._fx_stutter.set_property("freeze-max", st.freeze_max)
        compositor._fx_stutter.set_property("replay-frames", st.replay_frames)
    else:
        compositor._fx_stutter.set_property("freeze-chance", 0.0)
        compositor._fx_stutter.set_property("check-interval", 999)

    compositor._fx_active_preset = preset_name
    compositor._fx_tick = 0
    log.info("FX preset switched to: %s", preset_name)
