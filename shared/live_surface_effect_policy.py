"""Shared live-surface policy for compositor shader effects.

This module is intentionally broader than the preset-name gates. The live
surface can be reached through preset files, graph mutation, runtime uniform
modulation, WGSL plan compilation, and legacy/manual activation paths. Every
shader node type should therefore be either bounded, structurally guarded, or
blocked pending a source-preserving repair.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParamBound:
    """A live-surface bound for one shader uniform parameter."""

    min_value: float | None = None
    max_value: float | None = None
    force: Any = None
    has_force: bool = False

    def apply(self, value: Any) -> Any:
        if self.has_force:
            return self.force
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        out = float(value)
        if self.min_value is not None:
            out = max(out, self.min_value)
        if self.max_value is not None:
            out = min(out, self.max_value)
        return out


def _max(value: float) -> ParamBound:
    return ParamBound(max_value=value)


def _min(value: float) -> ParamBound:
    return ParamBound(min_value=value)


def _range(low: float, high: float) -> ParamBound:
    return ParamBound(min_value=low, max_value=high)


def _force(value: Any) -> ParamBound:
    return ParamBound(force=value, has_force=True)


# Live-surface policy has no permanent blocklist. Nodes that once replaced the
# frame or painted a fourth-wall pane have been repaired into source-bound,
# bounded effects; new unsafe nodes must either enter this set as temporary
# incident containment or be repaired before merge.
LIVE_SURFACE_BLOCKED_NODE_TYPES = frozenset()

# These nodes have source-bound WGSL repairs, but their legacy GLSL fragments
# can still render viewport/fourth-wall panes when loaded through the
# GStreamer graph-preset path. They remain eligible for WGSL autonomous drift;
# the graph-policy gate blocks only GLSL-backed live-surface activation until
# fragment parity is proven.
LIVE_SURFACE_GLSL_PENDING_SOURCE_BOUND_REPAIR_NODE_TYPES = frozenset(
    {
        "ascii",
        "halftone",
        "noise_gen",
        "palette_extract",
    }
)


CONTENT_SLOT_GUARDED_NODE_TYPES = frozenset({"content_layer", "sierpinski_content"})
STRUCTURAL_NODE_TYPES = frozenset({"output"})


LIVE_SURFACE_PARAM_BOUNDS: dict[str, dict[str, ParamBound]] = {
    "ascii": {
        "cell_size": _range(6.0, 24.0),
        "color_mode": _range(0.0, 1.0),
    },
    "bloom": {
        "alpha": _max(0.35),
        "radius": _max(12.0),
        "threshold": _min(0.25),
    },
    "blend": {
        "alpha": _max(0.24),
        "mode": _range(0.0, 4.0),
    },
    # Full-frame brightness pulsing remains disallowed; this node is repaired
    # as bounded geometric breathing with a tiny source-preserving warp.
    "breathing": {
        "amplitude": _range(0.0, 0.012),
        "rate": _range(0.05, 0.65),
    },
    "chroma_key": {
        "key_b": _range(0.0, 1.0),
        "key_g": _range(0.0, 1.0),
        "key_r": _range(0.0, 1.0),
        "softness": _range(0.04, 0.12),
        "tolerance": _range(0.18, 0.35),
    },
    "chromatic_aberration": {
        "intensity": _max(1.0),
        "offset_x": _range(-4.0, 4.0),
        "offset_y": _range(-4.0, 4.0),
    },
    "circular_mask": {
        "radius": _range(0.62, 0.92),
        "softness": _range(0.08, 0.22),
    },
    "color_map": {"blend": _max(0.35)},
    "colorgrade": {
        "brightness": _range(0.90, 1.10),
        "contrast": _range(0.75, 1.35),
        "hue_rotate": _range(-45.0, 45.0),
        "saturation": _range(0.35, 1.35),
        "sepia": _max(0.15),
    },
    "dither": {
        "color_levels": _min(8.0),
        "matrix_size": _max(4.0),
        "monochrome": _max(0.0),
    },
    "crossfade": {"mix": _max(0.18)},
    "diff": {
        "color_mode": _range(0.0, 2.0),
        "threshold": _range(0.04, 0.14),
    },
    "displacement_map": {
        "strength_x": _range(-0.055, 0.055),
        "strength_y": _range(-0.055, 0.055),
    },
    "drift": {
        "amplitude": _max(0.70),
        "coherence": _max(0.70),
        "speed": _max(1.0),
    },
    "droste": {
        "branches": _range(1.0, 2.5),
        "center_x": _range(0.45, 0.55),
        "center_y": _range(0.45, 0.55),
        "spiral": _range(0.0, 0.45),
        "zoom_speed": _range(0.0, 0.16),
    },
    "echo": {
        "frame_count": _max(4.0),
        "decay_curve": _range(0.3, 2.0),
        "blend_mode": _max(1.0),
    },
    "emboss": {
        "blend": _max(0.35),
        "strength": _max(0.35),
    },
    "edge_detect": {
        "color_mode": _range(0.0, 0.35),
        "threshold": _range(0.08, 0.45),
    },
    "feedback": {
        "blend_mode": _max(1.0),
        "decay": _min(0.12),
        "rotate": _max(0.01),
        "trace_strength": _max(0.25),
        "zoom": _range(0.99, 1.02),
    },
    "fisheye": {
        "center_x": _range(0.35, 0.65),
        "center_y": _range(0.35, 0.65),
        "strength": _range(-0.25, 0.25),
        "zoom": _range(0.75, 1.25),
    },
    "fluid_sim": {
        "amount": _range(0.0, 0.14),
        "dissipation": _range(0.94, 0.995),
        "speed": _range(0.0, 1.0),
        "viscosity": _range(0.001, 0.006),
        "vorticity": _range(0.0, 1.0),
    },
    "glitch_block": {
        "block_size": _min(8.0),
        "intensity": _max(0.25),
        "rgb_split": _max(0.25),
    },
    "grain_bump": {
        "strength": _max(0.35),
    },
    "halftone": {
        "dot_size": _max(8.0),
    },
    "invert": {"strength": _max(0.35)},
    "kaleidoscope": {
        "center_x": _range(0.47, 0.53),
        "center_y": _range(0.47, 0.53),
        "rotation": _range(-0.45, 0.45),
        "segments": _range(1.5, 4.0),
    },
    "kuwahara": {"radius": _max(3.0)},
    "luma_key": {
        "invert": _force(0.0),
        "softness": _range(0.04, 0.12),
        "threshold": _range(0.42, 0.68),
    },
    "mirror": {
        "axis": _range(0.0, 1.0),
        "position": _range(0.40, 0.75),
    },
    "nightvision_tint": {
        "brightness": _range(0.95, 1.20),
        "contrast": _range(0.85, 1.15),
        "green_intensity": _range(0.35, 0.70),
    },
    "noise_gen": {
        "amplitude": _max(0.08),
        "frequency_x": _range(0.5, 8.0),
        "frequency_y": _range(0.5, 8.0),
        "octaves": _range(1.0, 4.0),
        "speed": _max(0.35),
    },
    "noise_overlay": {
        "animated": _force(False),
        "intensity": _max(0.10),
    },
    "palette": {
        "brightness": _range(0.90, 1.10),
        "contrast": _range(0.75, 1.35),
        "hue_rotate": _range(-45.0, 45.0),
        "saturation": _range(0.35, 1.35),
        "sepia": _max(0.15),
    },
    "palette_extract": {
        "strip_height": _range(0.02, 0.10),
        "strip_opacity": _max(0.45),
        "swatch_count": _range(3.0, 10.0),
    },
    "palette_remap": {
        "blend": _max(0.35),
        "cycle_rate": _max(1.0),
    },
    "particle_system": {
        "color_b": _range(0.0, 1.0),
        "color_g": _range(0.0, 1.0),
        "color_r": _range(0.0, 1.0),
        "emit_rate": _range(24.0, 96.0),
        "gravity_y": _range(0.0, 60.0),
        "lifetime": _range(1.5, 4.0),
        "size": _range(1.0, 3.0),
    },
    "pixsort": {
        "sort_length": _range(10.0, 100.0),
        "threshold_low": _range(0.35, 0.70),
        "threshold_high": _range(0.50, 0.85),
    },
    "posterize": {
        "gamma": _range(0.8, 1.4),
        "levels": _min(8.0),
    },
    "postprocess": {
        "anonymize": _max(0.5),
        "master_opacity": _min(0.85),
        "sediment_strength": _max(0.05),
        "vignette_strength": _max(0.25),
    },
    "reaction_diffusion": {
        "amount": _range(0.0, 0.13),
        "diffusion_a": _range(0.8, 1.2),
        "diffusion_b": _range(0.35, 0.65),
        "feed_rate": _range(0.035, 0.070),
        "kill_rate": _range(0.045, 0.066),
        "speed": _range(0.0, 1.0),
    },
    "rutt_etra": {
        "color_mode": _range(0.0, 1.0),
        "displacement": _range(-32.0, 32.0),
        "line_density": _range(3.0, 16.0),
        "line_width": _range(1.0, 3.0),
    },
    "scanlines": {
        "opacity": _max(0.18),
        "spacing": _min(4.0),
        "thickness": _max(1.5),
    },
    "sharpen": {
        "amount": _max(0.75),
        "radius": _max(2.0),
    },
    "sierpinski_lines": {
        "glow_radius": _max(8.0),
        "intensity": _max(0.65),
        "line_width": _max(4.0),
        "opacity": _max(0.45),
    },
    "slitscan": {"speed": _range(0.2, 0.6)},
    "solid": {
        "color_a": _range(0.02, 0.10),
        "color_b": _range(0.0, 1.0),
        "color_g": _range(0.0, 1.0),
        "color_r": _range(0.0, 1.0),
    },
    "strobe": {
        "active": _range(0.0, 0.35),
        "color_a": _max(0.08),
        "color_b": _range(0.0, 1.0),
        "color_g": _range(0.0, 1.0),
        "color_r": _range(0.0, 1.0),
    },
    "stutter": {
        "check_interval": _min(20.0),
        "freeze_chance": _max(0.08),
        "freeze_max": _max(2.0),
        "freeze_min": _max(1.0),
        "replay_frames": _max(1.0),
    },
    "syrup": {
        "bottom_alpha": _max(0.20),
        "color_b": _range(0.0, 1.0),
        "color_g": _range(0.0, 1.0),
        "color_r": _range(0.0, 1.0),
        "top_alpha": _max(0.20),
    },
    "thermal": {
        "edge_glow": _max(0.30),
        "intensity": _max(0.40),
        "palette_shift": _max(0.35),
    },
    "threshold": {
        "level": _range(0.35, 0.65),
        "softness": _range(0.10, 0.30),
    },
    "tile": {
        "count_x": _range(1.0, 3.0),
        "count_y": _range(1.0, 3.0),
        "gap": _range(0.0, 0.035),
        "mirror": _range(0.0, 1.0),
    },
    "trail": {
        "blend_mode": _force(1.0),
        "drift_x": _range(-4.0, 4.0),
        "drift_y": _range(-4.0, 4.0),
        "fade": _min(0.12),
        "opacity": _max(0.30),
    },
    "transform": {
        "pos_x": _range(-0.03, 0.03),
        "pos_y": _range(-0.03, 0.03),
        "rotation": _range(-0.03, 0.03),
        "scale_x": _range(0.98, 1.02),
        "scale_y": _range(0.98, 1.02),
    },
    "tunnel": {
        "distortion": _range(0.0, 2.0),
        "radius": _range(0.08, 0.24),
        "speed": _range(0.0, 0.18),
        "twist": _range(0.0, 0.40),
    },
    "vhs": {
        "chroma_shift": _max(4.0),
        "noise_band_y": _max(0.35),
    },
    "vignette": {
        "radius": _min(0.65),
        "softness": _max(0.35),
        "strength": _max(0.25),
    },
    "voronoi_overlay": {
        "animation_speed": _max(1.0),
        "cell_count": _range(4.0, 20.0),
        "edge_width": _max(0.08),
        "jitter": _max(0.35),
    },
    "warp": {
        "breath": _force(0.0),
        "pan_x": _range(-4.0, 4.0),
        "pan_y": _range(-4.0, 4.0),
        "rotate": _range(-0.03, 0.03),
        "slice_amplitude": _range(-4.0, 4.0),
        "zoom": _range(0.98, 1.02),
    },
    "waveform_render": {
        "color_a": _max(0.16),
        "scale": _range(0.35, 0.80),
        "shape": _range(0.0, 2.0),
        "thickness": _range(0.7, 2.5),
    },
}


def apply_live_surface_param_bounds(node_type: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """Return params clamped to the live-surface policy for ``node_type``."""

    out = dict(params)
    for key, bound in LIVE_SURFACE_PARAM_BOUNDS.get(node_type, {}).items():
        if key in out:
            out[key] = bound.apply(out[key])

    if node_type == "pixsort":
        low = out.get("threshold_low")
        high = out.get("threshold_high")
        if isinstance(low, (int, float)) and isinstance(high, (int, float)):
            low_f = float(low)
            high_f = float(high)
            if high_f < low_f:
                low_f, high_f = high_f, low_f
            if high_f - low_f > 0.20:
                high_f = min(0.85, low_f + 0.20)
            out["threshold_low"] = low_f
            out["threshold_high"] = high_f

    return out


def live_surface_policy_kind(node_type: str) -> str:
    """Return the live-surface classification for a shader node type."""

    if node_type in STRUCTURAL_NODE_TYPES:
        return "structural"
    if node_type in CONTENT_SLOT_GUARDED_NODE_TYPES:
        return "content_slot_guarded"
    if node_type in LIVE_SURFACE_BLOCKED_NODE_TYPES:
        return "blocked_pending_repair"
    if node_type in LIVE_SURFACE_PARAM_BOUNDS:
        return "bounded"
    return "unclassified"


def live_surface_unclassified_node_types(node_types: set[str] | frozenset[str]) -> set[str]:
    """Return shader node types not explicitly covered by live-surface policy."""

    return {
        node_type
        for node_type in node_types
        if live_surface_policy_kind(node_type) == "unclassified"
    }


__all__ = [
    "CONTENT_SLOT_GUARDED_NODE_TYPES",
    "LIVE_SURFACE_BLOCKED_NODE_TYPES",
    "LIVE_SURFACE_GLSL_PENDING_SOURCE_BOUND_REPAIR_NODE_TYPES",
    "LIVE_SURFACE_PARAM_BOUNDS",
    "ParamBound",
    "STRUCTURAL_NODE_TYPES",
    "apply_live_surface_param_bounds",
    "live_surface_policy_kind",
    "live_surface_unclassified_node_types",
]
