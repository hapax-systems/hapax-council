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
    "colorgrade",
    "edge_detect",
    "bloom",
    "scanlines",
    "chromatic_aberration",
    "vignette",
    "feedback",
    "trail",
    "thermal",
    "halftone",
    "kaleidoscope",
    "emboss",
]

POOL_SIZE = 12
PARAM_DRIFT_RATE = 0.003  # Subtle per-tick param wander within active slots

# ── Lifecycle timing ──────────────────────────────────────────────
# Each slot cycles through: IDLE → RISING → PEAK → FALLING → IDLE
# Staggered starts ensure continuous flow.
FADE_IN_S = 15.0        # seconds to rise from 0 → 1
PEAK_HOLD_S = 25.0       # seconds at full intensity (randomized ±40%)
FADE_OUT_S = 15.0        # seconds to fall from 1 → 0
# Stagger: time between successive slot activations
STAGGER_S = 18.0         # new slot activates every ~18s (randomized ±30%)
RECYCLE_IDLE_S = 30.0    # seconds at IDLE before shader recycling


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

        pool_types = list(DEFAULT_POOL)
        remaining = [t for t in self._available_types if t not in pool_types]
        self._rng.shuffle(remaining)
        while len(pool_types) < POOL_SIZE and remaining:
            pool_types.append(remaining.pop())

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
            base_params["mix"] = 0.0
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

        # Kick off initial rotation: activate first 3 slots staggered
        for i, state in enumerate(self._slots[:3]):
            delay = i * STAGGER_S * 0.5  # first 3 ramp up quickly
            state.phase = Phase.RISING
            state.phase_start = now + delay
            state.phase_duration = FADE_IN_S * (0.8 + 0.4 * self._rng.random())
            state.idle_since = 0
            state._active_target = self._random_active_target(state.node_type)

        self._last_activation = now
        self._next_stagger = STAGGER_S * (0.7 + 0.6 * self._rng.random())

        self._booted = True
        log.warning(
            "SlotDrift booted: %d slots loaded from %d eligible types. "
            "Initial: %s",
            len(self._slots),
            len(self._available_types),
            [s.node_type for s in self._slots[:3]],
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

        # Phase 3: Interpolate all slots and flush to GPU
        for state in self._slots:
            self._interpolate_slot(state, sp, now)

        # Phase 4: Recycle idle shader fragments
        if self._tick_count % 90 == 0:  # ~every 15s
            self._maybe_recycle(sp, now)

    def _advance_lifecycle(self, state: SlotState, now: float) -> None:
        """Advance a slot through its lifecycle phases."""
        if state.phase == Phase.IDLE:
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
                state._peak_intensity = 0.25 + 0.45 * self._rng.random()  # 0.25-0.70
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
                log.info("SlotDrift: slot %d (%s) → IDLE",
                         state.slot_idx, state.node_type)

    def _maybe_activate_next(self, now: float) -> None:
        """Activate the next idle slot to keep rotation flowing."""
        elapsed = now - self._last_activation
        if elapsed < self._next_stagger:
            return

        # Count currently active (non-IDLE) slots
        active_count = sum(1 for s in self._slots if s.phase != Phase.IDLE)

        # Keep 2-4 active at a time
        if active_count >= 4:
            return

        # Find idle slots
        idle_slots = [s for s in self._slots if s.phase == Phase.IDLE]
        if not idle_slots:
            return

        # Pick one to activate
        chosen = self._rng.choice(idle_slots)
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

        # u_mix controls passthrough blend
        sp._slot_base_params[idx]["mix"] = state.intensity

        # Interpolate per-shader params toward this slot's randomized target
        passthrough = PASSTHROUGH_MAP.get(state.node_type, {})
        active = getattr(state, '_active_target', None)
        if active is None:
            active = self._random_active_target(state.node_type)
            state._active_target = active

        # Subtle wander for organic feel
        wander = 0.0
        if state.intensity > 0.1:
            wander = self._rng.gauss(0.0, PARAM_DRIFT_RATE)

        for key in passthrough:
            pt_val = passthrough[key]
            act_val = active.get(key, pt_val)
            interpolated = pt_val + (act_val - pt_val) * state.intensity
            if wander != 0 and act_val != pt_val:
                span = abs(act_val - pt_val)
                interpolated += wander * span
                lo, hi = min(pt_val, act_val), max(pt_val, act_val)
                interpolated = max(lo, min(hi, interpolated))
            sp._slot_base_params[idx][key] = interpolated
            state.current_params[key] = interpolated

        sp._apply_glfeedback_uniforms(idx)

    def _maybe_recycle(self, sp: SlotPipeline, now: float) -> None:
        """Swap shader fragment on slots that have been IDLE long enough."""
        for state in self._slots:
            if state.phase != Phase.IDLE:
                continue
            if state.idle_since == 0:
                continue

            idle_time = now - state.idle_since
            if idle_time < RECYCLE_IDLE_S:
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
            base_params["mix"] = 0.0
            sp._slot_base_params[idx] = base_params
            sp._slot_preset_params[idx] = dict(base_params)
            sp._apply_glfeedback_uniforms(idx)

            state.node_type = new_type
            state.current_params = dict(passthrough)
            state.idle_since = now

            log.info("SlotDrift recycle: slot %d %s → %s (idle %.0fs)",
                     idx, old_type, new_type, idle_time)
