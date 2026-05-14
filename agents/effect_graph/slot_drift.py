"""Slot-pool continuous rotation — indeterminate presets flowing into one another.

Architecture per ``feedback_no_presets_use_parametric_modulation``:
variance emerges from per-parameter walks within constraint envelopes,
NOT from preset selection or topology mutation.

Key design: effects have individual lifecycles (fade-in → peak → fade-out)
staggered across time. At any moment, 2-4 effects are at various stages
of their lifecycle. The overlap creates continuous visual flow — there is
never a static "hold" where the look doesn't evolve.

Shader fragment swaps ONLY happen at u_mix=0 (passthrough), eliminating
GL recompile blinks.
"""

from __future__ import annotations

import logging
import random
import math
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.effect_graph.pipeline import SlotPipeline
    from agents.effect_graph.registry import ShaderRegistry

log = logging.getLogger(__name__)


def wrap_glsl_with_mix(glsl: str) -> str:
    """Inject a u_mix uniform that blends between original input and effect output.

    At u_mix=0.0 the output is the unmodified input texture (passthrough),
    at u_mix=1.0 the output is the full effect. This gives EVERY shader a
    guaranteed passthrough path.

    Strategy: save the original texture at the top of main(), let the shader
    run its full logic (including any if/else branches that set gl_FragColor),
    then AFTER all shader logic, mix the final gl_FragColor with the original.
    This handles shaders with multiple gl_FragColor assignments correctly.
    """
    if "u_mix" in glsl:
        return glsl

    lines = glsl.split("\n")
    last_uniform_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("uniform "):
            last_uniform_idx = i

    if last_uniform_idx == -1:
        for i, line in enumerate(lines):
            if "void main" in line:
                last_uniform_idx = i - 1
                break

    lines.insert(last_uniform_idx + 1,
                 "uniform float u_mix;  // drift: 0=passthrough, 1=full effect")

    result = "\n".join(lines)

    # Find main() opening brace
    main_idx = result.find("void main")
    if main_idx == -1:
        return glsl

    brace_idx = result.find("{", main_idx)
    if brace_idx == -1:
        return glsl

    # Insert original capture right after opening brace
    preamble = "\n    vec4 _drift_original = texture2D(tex, v_texcoord);\n"
    result = result[:brace_idx + 1] + preamble + result[brace_idx + 1:]

    # Find the LAST closing brace of main() — this is where we append the mix
    # Walk backwards from end of string to find it
    last_brace = result.rfind("}")
    if last_brace == -1:
        return glsl

    # Insert the final mix BEFORE the closing brace
    # This runs AFTER all shader logic, regardless of which branch set gl_FragColor
    postamble = "\n    gl_FragColor = mix(_drift_original, gl_FragColor, u_mix);\n"
    result = result[:last_brace] + postamble + result[last_brace:]

    return result


# Types excluded from drift pool
EXCLUDED_TYPES = frozenset({
    # Temporally discontinuous — produce flashing by design
    "stutter", "glitch_block", "diff", "echo",
    "output", "content_layer", "solid", "strobe", "chroma_key",
    "luma_key", "circular_mask", "syrup", "waveform_render",
    "fluid_sim", "reaction_diffusion", "particle_system",
    "blend", "crossfade", "noise_gen",
    # Temporal accumulation — accum buffer creates persistent ghost
    # layers that duplicate the entire layout even at correct params.
    "trail", "feedback",
})

# Per-shader passthrough values (shader output ≈ input)
PASSTHROUGH_MAP: dict[str, dict[str, float]] = {
    "colorgrade":           {"saturation": 1.0, "brightness": 1.0, "contrast": 1.0,
                             "sepia": 0.0, "hue_rotate": 0.0},
    "edge_detect":          {"threshold": 1.0},
    "bloom":                {"alpha": 0.0},
    "emboss":               {"strength": 0.0},
    "sharpen":              {"amount": 0.0},
    "invert":               {"strength": 0.0},
    "vignette":             {"strength": 0.0},
    "noise_overlay":        {"intensity": 0.0},
    "scanlines":            {"opacity": 0.0},
    "chromatic_aberration":  {"intensity": 0.0},
    "posterize":            {"levels": 256.0},
    "glitch_block":         {"intensity": 0.0},
    "thermal":              {"intensity": 0.0},
    "halftone":             {"dot_size": 1.0},
    "dither":               {"color_levels": 256.0},
    "feedback":             {"decay": 0.0},
    "vhs":                  {"chroma_shift": 0.0},
    "fisheye":              {"strength": 0.0},
    "ascii":                {"cell_size": 1.0},
    "pixsort":              {"sort_length": 0.0},
    "nightvision_tint":     {"green_intensity": 0.0, "brightness": 1.0, "contrast": 1.0},
    "threshold":            {"level": 0.0},
    "sierpinski_lines":     {"opacity": 0.0},
    "breathing":            {"amplitude": 0.0},
    "echo":                 {"frame_count": 1.0},
    "stutter":              {"freeze_chance": 0.0},
    "voronoi_overlay":      {"edge_width": 0.0},
    "palette":              {"saturation": 1.0, "brightness": 1.0, "contrast": 1.0},
    "postprocess":          {"master_opacity": 0.0},
    "kuwahara":             {"radius": 0.0},
    "diff":                 {"threshold": 1.0},
    "color_map":            {"blend": 0.0},
    "drift":                {"amplitude": 0.0},
    "mirror":               {"position": 0.5},
    "kaleidoscope":         {"segments": 1.0},
    "tile":                 {"count_x": 1.0, "count_y": 1.0},
    "trail":                {"opacity": 0.0},
    "transform":            {"scale_x": 1.0, "scale_y": 1.0, "rotation": 0.0,
                             "pos_x": 0.0, "pos_y": 0.0},
    "palette_remap":        {"blend": 0.0},
    "palette_extract":      {"strip_opacity": 0.0},
    "sierpinski_content":   {"intensity": 0.0},
    "droste":               {"zoom_speed": 0.0, "spiral": 0.0},
    "slitscan":             {"speed": 0.0},
    "tunnel":               {"speed": 0.0, "distortion": 0.0},
    "rutt_etra":            {"displacement": 0.0},
    "warp":                 {"breath": 0.0, "slice_amplitude": 0.0, "rotate": 0.0, "zoom": 1.0},
    "displacement_map":     {"strength_x": 0.0, "strength_y": 0.0},
}

# Per-shader "active" target ranges — min/max for randomized activation.
# Each activation picks a random point in these ranges, so the same shader
# type never looks the same twice. Keys not listed use registry defaults.
ACTIVE_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "colorgrade":           {"saturation": (0.3, 1.8), "brightness": (0.7, 1.6), "contrast": (0.8, 1.6),
                             "sepia": (0.0, 0.7), "hue_rotate": (0.0, 1.0)},
    "edge_detect":          {"threshold": (0.05, 0.5)},
    "bloom":                {"alpha": (0.1, 0.5)},
    "emboss":               {"strength": (0.3, 1.0)},
    "sharpen":              {"amount": (0.2, 0.8)},
    "invert":               {"strength": (0.3, 1.0)},
    "vignette":             {"strength": (0.2, 0.7)},
    "noise_overlay":        {"intensity": (0.02, 0.12)},
    "scanlines":            {"opacity": (0.05, 0.35)},
    "chromatic_aberration":  {"intensity": (0.3, 1.5)},
    "posterize":            {"levels": (2.0, 12.0)},
    "glitch_block":         {"intensity": (0.1, 0.5)},
    "thermal":              {"intensity": (0.3, 0.9)},
    "halftone":             {"dot_size": (3.0, 12.0)},
    "dither":               {"color_levels": (2.0, 12.0)},
    "feedback":             {"decay": (0.04, 0.2)},
    "vhs":                  {"chroma_shift": (1.0, 6.0)},
    "fisheye":              {"strength": (0.15, 0.7)},
    "ascii":                {"cell_size": (4.0, 14.0)},
    "pixsort":              {"sort_length": (30.0, 150.0)},
    "nightvision_tint":     {"green_intensity": (0.4, 1.0), "brightness": (1.2, 2.2), "contrast": (1.0, 1.6)},
    "threshold":            {"level": (0.2, 0.8)},
    "sierpinski_lines":     {"opacity": (0.2, 0.8)},
    "breathing":            {"amplitude": (0.02, 0.08)},
    "echo":                 {"frame_count": (2.0, 10.0)},
    "stutter":              {"freeze_chance": (0.04, 0.25)},
    "voronoi_overlay":      {"edge_width": (0.02, 0.08)},
    "palette":              {"saturation": (0.2, 1.5), "brightness": (0.8, 1.6), "contrast": (0.8, 1.8)},
    "postprocess":          {"master_opacity": (0.4, 1.0)},
    "kuwahara":             {"radius": (1.0, 6.0)},
    "diff":                 {"threshold": (0.03, 0.12)},
    "color_map":            {"blend": (0.4, 1.0)},
    "drift":                {"amplitude": (0.3, 1.2)},
    "mirror":               {"position": (0.15, 0.45)},
    "kaleidoscope":         {"segments": (3.0, 12.0)},
    "tile":                 {"count_x": (2.0, 5.0), "count_y": (2.0, 5.0)},
    "trail":                {"opacity": (0.1, 0.5)},
    "transform":            {"scale_x": (0.95, 1.15), "scale_y": (0.95, 1.15), "rotation": (0.0, 0.08)},
    "palette_remap":        {"blend": (0.4, 1.0)},
    "palette_extract":      {"strip_opacity": (0.4, 1.0)},
    "sierpinski_content":   {"intensity": (0.3, 0.9)},
    "droste":               {"zoom_speed": (0.1, 0.5), "spiral": (0.05, 0.4)},
    "slitscan":             {"speed": (0.05, 0.3)},
    "tunnel":               {"speed": (0.1, 0.5), "distortion": (0.15, 0.7)},
    "rutt_etra":            {"displacement": (0.2, 0.8)},
    "warp":                 {"breath": (0.1, 0.5), "slice_amplitude": (0.05, 0.4), "rotate": (0.01, 0.1), "zoom": (0.95, 1.2)},
    "displacement_map":     {"strength_x": (0.05, 0.3), "strength_y": (0.05, 0.3)},
}

# Curated initial pool: diverse visual character across the spectrum
DEFAULT_POOL: list[str] = [
    # Tonal: color/light transforms
    "colorgrade",
    "bloom",
    "vignette",
    "thermal",
    # Texture: surface treatment
    "scanlines",
    "halftone",
    "emboss",
    "kuwahara",
    # Spatial: geometric transforms (safe — u_mix=1.0, native param lifecycle)
    "kaleidoscope",
    "chromatic_aberration",
    # Edge: structural emphasis
    "edge_detect",
]

POOL_SIZE = 6
PARAM_DRIFT_RATE = 0.015  # Aggressive per-tick wander — look never stays static

# ── Lifecycle timing ──────────────────────────────────────────────
# Each slot cycles through: IDLE → RISING → PEAK → FALLING → IDLE
# Staggered starts ensure continuous flow.
FADE_IN_S = 40.0        # slow imperceptible rise        # seconds to rise from 0 → target (imperceptible)
PEAK_HOLD_S = 15.0       # brief peak before starting descent       # seconds at peak intensity (randomized ±40%)
FADE_OUT_S = 40.0        # slow imperceptible fall        # seconds to fall from peak → 0 (imperceptible)
# Stagger: time between successive slot activations
STAGGER_S = 19.0         # ~95s/5 slots = constant 1 transition at a time         # new slot activates every ~30s (randomized ±30%)
RECYCLE_IDLE_S = 3.0     # recycle almost immediately — no idle camping    # seconds at IDLE before shader recycling

# Shaders that spatially displace pixels. These MUST NOT use u_mix
# at intermediate values because mix(original, displaced, 0.5) creates
# a ghost overlay of the undistorted layout on top of the distorted one.
# For these, u_mix=1.0 always; lifecycle via native parameter interpolation.
SPATIAL_TYPES = frozenset({
    "kaleidoscope", "tile", "mirror", "drift", "fisheye", "transform",
    "warp", "droste", "slitscan", "tunnel", "displacement_map",
    "rutt_etra",
})

# ── Aesthetic families ────────────────────────────────────────────
# Shaders within the same family share tonal character. Adjacent
# activations prefer the same or neighboring family for smooth
# aesthetic flow. Cross-family jumps still happen but are rarer.
SHADER_FAMILIES: dict[str, str] = {
    # Tonal: color/light transforms
    "colorgrade": "tonal", "bloom": "tonal", "vignette": "tonal",
    "thermal": "tonal", "nightvision_tint": "tonal", "palette": "tonal",
    "palette_remap": "tonal", "color_map": "tonal", "invert": "tonal",
    "posterize": "tonal",
    # Texture: surface treatment
    "scanlines": "texture", "halftone": "texture", "noise_overlay": "texture",
    "emboss": "texture", "kuwahara": "texture", "dither": "texture",
    "vhs": "texture", "ascii": "texture", "sharpen": "texture",
    # Edge: structural emphasis
    "edge_detect": "edge", "sierpinski_lines": "edge", "sierpinski_content": "edge",
    "voronoi_overlay": "edge", "threshold": "edge",
    # Atmospheric: mood overlays
    "breathing": "atmospheric", "postprocess": "atmospheric",
    "chromatic_aberration": "atmospheric", "pixsort": "atmospheric",
    "palette_extract": "atmospheric",
}
# Families that blend well together (can co-activate without jarring contrast)
FAMILY_AFFINITY: dict[str, list[str]] = {
    "tonal":       ["tonal", "atmospheric", "texture"],
    "texture":     ["texture", "tonal", "edge"],
    "edge":        ["edge", "texture", "atmospheric"],
    "atmospheric": ["atmospheric", "tonal", "edge"],
}


class Phase(Enum):
    IDLE = auto()     # u_mix = 0, at passthrough
    RISING = auto()   # fading in
    PEAK = auto()     # at full intensity
    FALLING = auto()  # fading out


@dataclass
class SlotState:
    """Per-slot lifecycle state."""
    node_type: str
    slot_idx: int
    phase: Phase = Phase.IDLE
    intensity: float = 0.0
    # When current phase started (monotonic)
    phase_start: float = 0.0
    # Duration of current phase (randomized)
    phase_duration: float = 0.0
    # When slot entered IDLE (for recycle eligibility)
    idle_since: float = 0.0
    # Per-param state
    current_params: dict[str, float] = field(default_factory=dict)


class SlotDriftEngine:
    """Continuous rotation: effects flow in and out on staggered lifecycles.

    At any moment, 2-4 effects are at various stages of their lifecycle
    (rising, peak, or falling). There is no static "hold" — the visual
    is always evolving.
    """

    def __init__(self, registry: ShaderRegistry, seed: int = 42) -> None:
        self.registry = registry
        self._rng = random.Random(seed)
        self._slots: list[SlotState] = []
        self._booted = False
        self._tick_count = 0
        # Recently-used buffer prevents shader types from repeating
        # within the last 18 uses (~3x pool size). Ensures the visual
        # cycles through the full 39-type vocabulary.
        from collections import deque
        self._recently_used: deque = deque(maxlen=18)
        self._last_activation: float = 0.0
        self._next_stagger: float = STAGGER_S

        self._available_types = [
            nt for nt in registry.node_types
            if nt not in EXCLUDED_TYPES
            and nt in PASSTHROUGH_MAP
            and nt in ACTIVE_RANGES
            and registry.get(nt) is not None
            and registry.get(nt).glsl_source is not None
        ]
        log.info("SlotDrift: %d eligible shader types", len(self._available_types))

    def boot(self, sp: SlotPipeline) -> None:
        """Populate slot pool with diverse shaders, start staggered rotation."""
        if self._booted:
            return

        # Fully randomized initial pool — no hardcoded starting shaders.
        # Every restart gets a unique visual character from the first frame.
        all_types = list(self._available_types)
        self._rng.shuffle(all_types)
        pool_types = all_types[:POOL_SIZE]

        now = time.monotonic()

        for i, node_type in enumerate(pool_types):
            if i >= sp.num_slots:
                break

            defn = self.registry.get(node_type)
            if defn is None or defn.glsl_source is None:
                continue

            # Load shader fragment with u_mix wrapper
            sp._slot_assignments[i] = node_type
            frag = wrap_glsl_with_mix(defn.glsl_source)
            if frag != sp._slot_last_frag[i]:
                sp._slots[i].set_property("fragment", frag)
                sp._slot_last_frag[i] = frag

            # Set passthrough params
            passthrough = PASSTHROUGH_MAP.get(node_type, {})
            base_params: dict[str, Any] = {}
            for k, p in defn.params.items():
                if p.default is not None:
                    base_params[k] = p.default
            base_params.update(passthrough)
            base_params["mix"] = 1.0 if node_type in SPATIAL_TYPES else 0.0
            sp._slot_base_params[i] = base_params
            sp._slot_preset_params[i] = dict(base_params)
            sp._apply_glfeedback_uniforms(i)

            state = SlotState(
                node_type=node_type,
                slot_idx=i,
                phase=Phase.IDLE,
                intensity=0.0,
                idle_since=now,
                current_params=dict(passthrough),
            )
            self._slots.append(state)

        # Kick off initial rotation: first 3 slots start at partial intensity
        # for immediate visual variety, then continue their lifecycle.
        for i, state in enumerate(self._slots[:4]):
            state.phase = Phase.RISING
            state.phase_start = now - FADE_IN_S * 0.4 * (i + 1)  # pre-advanced
            state.phase_duration = FADE_IN_S * (0.8 + 0.4 * self._rng.random())
            state.idle_since = 0
            state._active_target = self._random_active_target(state.node_type)
            if state.node_type in SPATIAL_TYPES:
                state._peak_intensity = 0.25 + 0.20 * self._rng.random()
            else:
                state._peak_intensity = 0.55 + 0.35 * self._rng.random()

        self._last_activation = now
        self._next_stagger = STAGGER_S * (0.7 + 0.6 * self._rng.random())

        self._booted = True
        log.warning(
            "SlotDrift booted: %d slots loaded from %d eligible types. "
            "Initial: %s",
            len(self._slots),
            len(self._available_types),
            [s.node_type for s in self._slots[:4]],
        )

    def tick(self, sp: SlotPipeline, t: float) -> None:
        """Advance one frame. Called at ~30fps."""
        if not self._booted:
            return

        self._tick_count += 1
        # Throttle to ~6Hz
        if self._tick_count % 5 != 0:
            return

        now = time.monotonic()

        # Phase 1: Advance each slot's lifecycle
        for state in self._slots:
            self._advance_lifecycle(state, now)

        # Phase 2: Maybe activate a new slot (continuous rotation)
        self._maybe_activate_next(now)

        # Phase 2.5: Inline recycle — swap fragments on slots that just entered IDLE
        for state in self._slots:
            if getattr(state, '_needs_recycle', False):
                self._recycle_slot(sp, state)
                state._needs_recycle = False

        # Phase 3: Interpolate all slots and flush to GPU
        for state in self._slots:
            self._interpolate_slot(state, sp, now)

        # Phase 4: Recycle idle shader fragments
        # Timer-based recycle DISABLED — inline recycle on FALLING→IDLE
        # handles all shader rotation. The timer caused double-recycling
        # and churn that made slots swap fragments while still invisible.
        # if self._tick_count % 180 == 0:
        #     self._maybe_recycle(sp, now)

    def _advance_lifecycle(self, state: SlotState, now: float) -> None:
        """Advance a slot through its lifecycle phases."""
        if state.phase == Phase.IDLE:
            # Auto-promote to RISING after recompile buffer
            rerise = getattr(state, '_rerise_after', 0.0)
            if rerise > 0.0 and now >= rerise:
                state.phase = Phase.RISING
                state.phase_start = now
                state.phase_duration = FADE_IN_S * (0.8 + 0.4 * self._rng.random())
                state._active_target = self._random_active_target(state.node_type)
                if state.node_type in SPATIAL_TYPES:
                    state._peak_intensity = 0.25 + 0.20 * self._rng.random()
                else:
                    state._peak_intensity = 0.55 + 0.35 * self._rng.random()
                state._rerise_after = 0.0
                state.idle_since = 0
                log.debug("SlotDrift: slot %d (%s) → RISING (post-buffer)",
                          state.slot_idx, state.node_type)
            return

        elapsed = now - state.phase_start

        if state.phase == Phase.RISING:
            progress = min(1.0, elapsed / state.phase_duration) if state.phase_duration > 0 else 1.0
            # Smooth ease-in (cubic), targeting randomized peak
            peak = getattr(state, '_peak_intensity', 0.6)
            smooth = progress * progress * (3.0 - 2.0 * progress)
            state.intensity = smooth * peak
            if progress >= 1.0:
                state.phase = Phase.PEAK
                state.phase_start = now
                state.phase_duration = PEAK_HOLD_S * (0.6 + 0.8 * self._rng.random())
                # Randomized peak: effects tint the image rather than replacing it
                if state.node_type in SPATIAL_TYPES:
                    state._peak_intensity = 0.25 + 0.20 * self._rng.random()  # 0.25-0.45 spatial
                else:
                    state._peak_intensity = 0.55 + 0.35 * self._rng.random()  # 0.55-0.90 tonal
                log.debug("SlotDrift: slot %d (%s) → PEAK (%.0fs, intensity=%.2f)",
                          state.slot_idx, state.node_type, state.phase_duration,
                          state._peak_intensity)

        elif state.phase == Phase.PEAK:
            state.intensity = getattr(state, '_peak_intensity', 0.6)
            if elapsed >= state.phase_duration:
                state.phase = Phase.FALLING
                state.phase_start = now
                state.phase_duration = FADE_OUT_S * (0.8 + 0.4 * self._rng.random())
                log.info("SlotDrift: slot %d (%s) → FALLING (%.0fs)",
                         state.slot_idx, state.node_type, state.phase_duration)

        elif state.phase == Phase.FALLING:
            progress = min(1.0, elapsed / state.phase_duration) if state.phase_duration > 0 else 1.0
            # Smooth ease-out (cubic) from actual peak
            peak = getattr(state, '_peak_intensity', 0.6)
            inv = 1.0 - progress
            state.intensity = peak * inv * inv * (3.0 - 2.0 * inv)
            if progress >= 1.0:
                state.intensity = 0.0
                state.phase = Phase.IDLE
                state.idle_since = now
                state._needs_recycle = True
                log.info("SlotDrift: slot %d (%s) → IDLE (recycle queued)",
                         state.slot_idx, state.node_type)

    def _maybe_activate_next(self, now: float) -> None:
        """Activate the next idle slot to keep rotation flowing."""
        elapsed = now - self._last_activation
        if elapsed < self._next_stagger:
            return

        # Count currently active (non-IDLE) slots
        active_count = sum(1 for s in self._slots if s.phase != Phase.IDLE)

        # Keep 2-4 active at a time
        if active_count >= 5:
            return

        # Find idle slots
        idle_slots = [s for s in self._slots if s.phase == Phase.IDLE]
        if not idle_slots:
            return

        # Pick family-affine idle slot for smooth aesthetic flow
        chosen = self._pick_family_affine(idle_slots)
        chosen.phase = Phase.RISING
        chosen.phase_start = now
        chosen.phase_duration = FADE_IN_S * (0.8 + 0.4 * self._rng.random())
        chosen.idle_since = 0
        # Fresh randomized target — same shader type, different visual every time
        chosen._active_target = self._random_active_target(chosen.node_type)

        self._last_activation = now
        self._next_stagger = STAGGER_S * (0.7 + 0.6 * self._rng.random())

        log.info("SlotDrift: activating slot %d (%s), %d now active",
                 chosen.slot_idx, chosen.node_type, active_count + 1)

    def _pick_family_affine(self, idle_slots: list[SlotState]) -> SlotState:
        """Pick an idle slot whose shader family is affine to currently active effects."""
        active_families = set()
        for s in self._slots:
            if s.phase != Phase.IDLE:
                fam = SHADER_FAMILIES.get(s.node_type, "tonal")
                active_families.add(fam)
        
        if not active_families:
            return self._rng.choice(idle_slots)
        
        # Collect affine families
        affine = set()
        for fam in active_families:
            affine.update(FAMILY_AFFINITY.get(fam, [fam]))
        
        # Prefer idle slots in affine families (70% chance)
        affine_idle = [s for s in idle_slots if SHADER_FAMILIES.get(s.node_type, "tonal") in affine]
        if affine_idle and self._rng.random() < 0.7:
            return self._rng.choice(affine_idle)
        return self._rng.choice(idle_slots)

    def _random_active_target(self, node_type: str) -> dict[str, float]:
        """Generate a randomized active target for this shader type.

        Each activation picks a unique point within the shader's aesthetic
        range. This is the systemic fix for "same effect" repetition — the
        same shader type never produces the identical visual twice.
        """
        ranges = ACTIVE_RANGES.get(node_type, {})
        target: dict[str, float] = {}
        for key, (lo, hi) in ranges.items():
            target[key] = self._rng.uniform(lo, hi)
        return target

    def _interpolate_slot(self, state: SlotState, sp: SlotPipeline,
                          now: float) -> None:
        """Set params and flush to GPU for one slot."""
        idx = state.slot_idx
        if idx >= sp.num_slots or sp._slot_assignments[idx] is None:
            return

        # Spatial shaders (kaleidoscope, warp, fisheye, etc.) MUST use
        # u_mix=1.0 because intermediate u_mix blends the undistorted
        # layout with the distorted version = ghost duplicate.
        # Their lifecycle is driven by native passthrough params
        # (segments=1, strength=0, etc.) which produce identity.
        #
        # Tonal/color shaders (colorgrade, bloom, edge_detect, etc.)
        # use u_mix=intensity because their "passthrough" params may
        # not produce visual identity (e.g. edge_detect threshold=1.0
        # = black). u_mix blending is safe for these since they don't
        # displace pixels spatially.
        if state.node_type in SPATIAL_TYPES:
            sp._slot_base_params[idx]["mix"] = 1.0
        else:
            sp._slot_base_params[idx]["mix"] = state.intensity

        # Interpolate per-shader params toward this slot's randomized target
        passthrough = PASSTHROUGH_MAP.get(state.node_type, {})
        active = getattr(state, '_active_target', None)
        if active is None:
            active = self._random_active_target(state.node_type)
            state._active_target = active

        # Sinusoidal modulation + gaussian wander for continuous inner variation.
        # Each param gets a unique phase offset (seeded by slot+key) so
        # multi-param shaders create complex, non-repeating motion.
        for ki, key in enumerate(passthrough):
            pt_val = passthrough[key]
            act_val = active.get(key, pt_val)
            span = abs(act_val - pt_val)

            # Base interpolation toward active target
            interpolated = pt_val + (act_val - pt_val) * state.intensity

            if state.intensity > 0.05 and span > 0.001:
                # Sinusoidal sweep: each param oscillates within its range
                # at a unique frequency. Creates continuous inner animation
                # even for "static" shaders like colorgrade/vignette/bloom.
                phase_seed = (idx * 17 + ki * 7) * 0.1
                freq = 0.08 + 0.05 * ((idx * 3 + ki * 11) % 7)  # 0.08-0.43 Hz
                sine = math.sin(now * freq + phase_seed)
                # Spatial shaders get gentler modulation to prevent
                # extreme displacement that pushes layout off-screen.
                is_spatial = state.node_type in SPATIAL_TYPES
                mod_depth = 0.10 if is_spatial else 0.30
                modulation = sine * mod_depth * span * state.intensity
                interpolated += modulation

                # Gaussian wander on top (reduced for spatial)
                drift_scale = PARAM_DRIFT_RATE * (0.3 if is_spatial else 1.0)
                wander = self._rng.gauss(0.0, drift_scale) * span
                interpolated += wander

                # Strict clamp — no overflow beyond active range
                lo = min(pt_val, act_val)
                hi = max(pt_val, act_val)
                interpolated = max(lo, min(hi, interpolated))

            sp._slot_base_params[idx][key] = interpolated
            state.current_params[key] = interpolated

        sp._apply_glfeedback_uniforms(idx)

    def _recycle_slot(self, sp: SlotPipeline, state: SlotState) -> None:
        """Swap one slot's shader fragment to a new type (at intensity=0)."""
        current_types = {s.node_type for s in self._slots}
        recently_used = set(self._recently_used)
        # Exclude both current pool AND recently used types
        candidates = [t for t in self._available_types
                      if t not in current_types and t not in recently_used]
        if not candidates:
            # Relax: exclude only current pool
            candidates = [t for t in self._available_types if t not in current_types]
        if not candidates:
            candidates = [t for t in self._available_types if t != state.node_type]
        if not candidates:
            return

        new_type = self._rng.choice(candidates)
        defn = self.registry.get(new_type)
        if defn is None or defn.glsl_source is None:
            return

        idx = state.slot_idx
        old_type = state.node_type

        sp._slot_assignments[idx] = new_type
        frag = wrap_glsl_with_mix(defn.glsl_source)
        if frag != sp._slot_last_frag[idx]:
            sp._slots[idx].set_property("fragment", frag)
            sp._slot_last_frag[idx] = frag

        passthrough = PASSTHROUGH_MAP.get(new_type, {})
        base_params: dict[str, Any] = {}
        for k, p in defn.params.items():
            if p.default is not None:
                base_params[k] = p.default
        base_params.update(passthrough)
        base_params["mix"] = 1.0 if new_type in SPATIAL_TYPES else 0.0
        sp._slot_base_params[idx] = base_params
        sp._slot_preset_params[idx] = dict(base_params)
        sp._apply_glfeedback_uniforms(idx)

        state.node_type = new_type
        state.current_params = dict(passthrough)
        state.intensity = 0.0
        # Schedule re-rise after 2s GL recompile buffer
        import time as _time
        state._rerise_after = _time.monotonic() + 2.0
        self._recently_used.append(old_type)
        log.info("SlotDrift inline recycle: slot %d %s → %s (rerise in 2s, history=%d)",
                 idx, old_type, new_type, len(self._recently_used))

    def _maybe_recycle(self, sp: SlotPipeline, now: float) -> None:
        """Swap shader fragment on slots that have been IDLE long enough."""
        for state in self._slots:
            if state.phase != Phase.IDLE:
                continue
            if state.idle_since == 0:
                continue

            idle_time = now - state.idle_since
            if idle_time < 0.5:  # swap after 0.5s idle (within 2s buffer)
                continue

            current_types = {s.node_type for s in self._slots}
            candidates = [t for t in self._available_types if t not in current_types]
            if not candidates:
                continue

            new_type = self._rng.choice(candidates)
            defn = self.registry.get(new_type)
            if defn is None or defn.glsl_source is None:
                continue

            idx = state.slot_idx
            old_type = state.node_type

            # Swap fragment (invisible — at passthrough)
            sp._slot_assignments[idx] = new_type
            frag = wrap_glsl_with_mix(defn.glsl_source)
            if frag != sp._slot_last_frag[idx]:
                sp._slots[idx].set_property("fragment", frag)
                sp._slot_last_frag[idx] = frag

            # Reset params to passthrough
            passthrough = PASSTHROUGH_MAP.get(new_type, {})
            base_params: dict[str, Any] = {}
            for k, p in defn.params.items():
                if p.default is not None:
                    base_params[k] = p.default
            base_params.update(passthrough)
            base_params["mix"] = 1.0 if new_type in SPATIAL_TYPES else 0.0
            sp._slot_base_params[idx] = base_params
            sp._slot_preset_params[idx] = dict(base_params)
            sp._apply_glfeedback_uniforms(idx)

            state.node_type = new_type
            state.current_params = dict(passthrough)
            state.idle_since = now

            log.info("SlotDrift recycle: slot %d %s → %s (idle %.0fs)",
                     idx, old_type, new_type, idle_time)
            break  # only recycle ONE slot per pass to avoid GL recompile bursts
