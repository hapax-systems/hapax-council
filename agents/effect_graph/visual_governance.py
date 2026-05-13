"""Perception-visual governance — three-tier system for effect reactivity.

Atmospheric layer: selects which preset is active based on stimmung stance,
operator energy level, and music genre.

Gestural layer: adjusts parameters within the active preset based on
desk activity, gaze direction, and person count.

Breathing substrate: ensures the system is never visually dead via
Perlin noise drift, idle escalation, and silence-as-decay.
"""

from __future__ import annotations

import math
import os
import random
import time

from agents._capability import SystemContext
from agents._governance.primitives import Candidate, FallbackChain, Veto, VetoChain
from agents.effect_graph.types import PresetFamily

# ── Atmospheric Layer ─────────────────────────────────────────────────────────

# State matrix: stance × energy_level → PresetFamily
#
# Halftone-monoculture mitigation (researcher audit, 2026-05-04): the dot-
# pattern reversion every cycle traced to two coupled defects — a small
# ``("nominal", "low")`` family with ``halftone_preset`` first AND a default
# fallback that returned a halftone-only family. ``("nominal", "low")`` is
# the dominant condition during quiet research sessions and ``seeking`` (the
# exploration stance) folds back to ``nominal`` in
# ``fx_tick._read_stimmung_stance``, so any quiet tick became a halftone
# tick. The matrix now expands the nominal/seeking-low row to seven distinct
# atmospheric presets with halftone_preset shifted to last position; seeking
# rows are added explicitly so the fold-back can be retired in a follow-up.
_STATE_MATRIX: dict[tuple[str, str], PresetFamily] = {
    # NOMINAL — quiet research / conversation
    ("nominal", "low"): PresetFamily(
        presets=(
            "ghost",
            "ambient",
            "dither_retro",
            "trails",
            "vhs_preset",
            "tape_warmth",
            "mono_print_newsprint",
            "paper_fold_origami",
            "liquid_flow_breath",
            "water_ripple_surface",
            "drone_static_drift",
            "circular_lens_focus",
            "xerox_photocopy_decay",
            "vinyl_dust",
            "chamber_feedback_breathing",
            "chrome_mirror_brushed",
        )
    ),
    ("nominal", "medium"): PresetFamily(
        presets=(
            "kaleidodream",
            "nightvision",
            "trails",
            "ghost",
            "vhs_preset",
            "bloom_neon_night",
            "neon_grid_tunnel",
            "dub_echo_spatial",
            "cellular_kuwahara_paint",
            "kaleido_fractal_mirror",
            "electromag_thermal_field",
            "liquid_flow_fluid",
            "broadcast_vhs_decay",
            "tape_wow_flutter",
            "circular_porthole_view",
        )
    ),
    ("nominal", "high"): PresetFamily(
        presets=(
            "datamosh",
            "feedback_preset",
            "kaleidodream",
            "trap",
            "screwed",
            "glitch_blocks_preset",
            "pixsort_glitch_horizontal",
            "granular_stutter",
            "modulation_pulse_warp",
            "datamosh_heavy",
            "kaleido_fractal_dense",
            "bloom_solar_flare",
            "glitch_y2k_chroma",
        )
    ),
    # SEEKING — exploration / curiosity
    ("seeking", "low"): PresetFamily(
        presets=(
            "ghost",
            "trails",
            "kaleidodream",
            "ambient",
            "dither_retro",
            "voronoi_crystal",
            "water_ripple_caustic",
            "arcane_dither_sigil",
            "mono_print_woodcut",
            "paper_fold_crumple",
            "drone_dense_static",
            "xerox_smudge_streak",
            "cellular_reaction",
            "chrome_mirror_polished",
            "sculpture",
        )
    ),
    ("seeking", "medium"): PresetFamily(
        presets=(
            "kaleidodream",
            "feedback_preset",
            "nightvision",
            "tunnelvision",
            "neon_grid_arcade",
            "electromag_rutt_etra",
            "dub_tunnel_chamber",
            "broadcast_static_carrier",
            "slitscan_preset",
            "pixsort_preset",
            "arcane_ascii_glyph",
            "diff_motion_trail",
            "kaleido_fractal_mirror",
            "liquid_flow_fluid",
        )
    ),
    ("seeking", "high"): PresetFamily(
        presets=(
            "datamosh",
            "feedback_preset",
            "glitch_blocks_preset",
            "pixsort_glitch_vertical",
            "granular_stutter",
            "modulation_pulse_strobe",
            "datamosh_heavy",
            "glitch_y2k_block",
            "antivapor_thresh",
            "fisheye_pulse",
            "bloom_solar_flare",
        )
    ),
    # CAUTIOUS — reserved / careful
    ("cautious", "low"): PresetFamily(
        presets=(
            "ambient",
            "ghost",
            "dither_retro",
            "tape_warmth",
            "mono_print_newsprint",
            "vinyl_dust",
            "chamber_feedback_breathing",
            "water_ripple_surface",
            "paper_fold_origami",
            "circular_lens_focus",
        )
    ),
    ("cautious", "medium"): PresetFamily(
        presets=(
            "ghost",
            "vhs_preset",
            "trails",
            "nightvision",
            "broadcast_vhs_decay",
            "tape_wow_flutter",
            "diff_motion_thermal",
            "cellular_kuwahara_paint",
            "chrome_mirror_brushed",
        )
    ),
    ("cautious", "high"): PresetFamily(
        presets=(
            "trails",
            "ghost",
            "kaleidodream",
            "feedback_preset",
            "neon",
            "bloom_neon_night",
        )
    ),
    # DEGRADED — system stress / error states
    ("degraded", "low"): PresetFamily(
        presets=(
            "dither_retro",
            "vhs_preset",
            "ambient",
            "xerox_photocopy_decay",
            "drone_static_drift",
            "broadcast_vhs_decay",
            "vinyl_pop_static",
            "antivapor_grit",
            "mono_print_woodcut",
        )
    ),
    ("degraded", "medium"): PresetFamily(
        presets=(
            "vhs_preset",
            "dither_retro",
            "screwed",
            "glitch_blocks_preset",
            "broadcast_static_carrier",
            "xerox_smudge_streak",
            "diff_preset",
            "antivapor_thresh",
        )
    ),
    ("degraded", "high"): PresetFamily(
        presets=(
            "screwed",
            "datamosh",
            "glitch_y2k_block",
            "pixsort_glitch_horizontal",
            "datamosh_heavy",
            "granular_stutter",
            "antivapor_thresh",
        )
    ),
    # CRITICAL — system failure
    ("critical", "low"): PresetFamily(presets=("silhouette", "drone_dense_static", "clean")),
    ("critical", "medium"): PresetFamily(presets=("silhouette", "antivapor_grit")),
    ("critical", "high"): PresetFamily(presets=("silhouette",)),
}

# Default fallback — diverse pool for unknown matrix keys.
_DEFAULT_FAMILY: PresetFamily = PresetFamily(
    presets=(
        "ambient",
        "ghost",
        "trails",
        "kaleidodream",
        "vhs_preset",
        "dither_retro",
        "nightvision",
        "voronoi_crystal",
        "tape_warmth",
        "water_ripple_surface",
        "bloom_neon_night",
        "cellular_kuwahara_paint",
    )
)

# Genre bias: genre keyword → list of preferred preset names (prepended to family)
_GENRE_BIAS: dict[str, list[str]] = {
    "hip hop": ["trap", "screwed", "ghost"],
    "trap": ["trap", "screwed", "ghost"],
    "lo-fi": ["vhs_preset", "dither_retro", "ambient"],
    "jazz": ["vhs_preset", "dither_retro", "ambient"],
    "soul": ["vhs_preset", "ambient"],
    "electronic": ["voronoi_crystal", "tunnelvision", "kaleidodream"],
    "ambient": ["voronoi_crystal", "tunnelvision", "kaleidodream"],
}

_DWELL_MIN_S = 30.0  # minimum seconds before atmospheric transition
_DWELL_MIN_ENV = "HAPAX_ATMOSPHERIC_MIN_DWELL_S"
_ROTATE_ON_STABLE_ENV = "HAPAX_ATMOSPHERIC_ROTATE_ON_STABLE"


def _read_min_dwell_s() -> float:
    """Return the atmospheric topology dwell floor.

    The default preserves the variety fix that prevents preset monoculture.
    Incident canaries may raise the value so agency stays active through
    uniforms and wards while expensive topology swaps happen less often.
    """

    raw = os.environ.get(_DWELL_MIN_ENV)
    if raw is None or raw.strip() == "":
        return _DWELL_MIN_S
    try:
        value = float(raw)
    except ValueError:
        return _DWELL_MIN_S
    return max(0.0, value)


def _read_rotate_on_stable() -> bool:
    """Return whether a stable atmospheric context may rotate by dwell alone."""

    raw = os.environ.get(_ROTATE_ON_STABLE_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def energy_level_from_activity(desk_activity: str) -> str:
    """Map desk_activity classification to energy level."""
    if desk_activity in ("drumming", "scratching"):
        return "high"
    if desk_activity in ("tapping",):
        return "medium"
    return "low"


class AtmosphericSelector:
    """State machine for atmospheric preset selection."""

    def __init__(
        self,
        rng: random.Random | None = None,
        *,
        dwell_min_s: float | None = None,
        rotate_on_stable: bool | None = None,
    ) -> None:
        self._current_preset: str | None = None
        self._current_stance: str = "nominal"
        self._current_context: tuple[str, str, str] | None = None
        self._last_transition: float = 0.0
        self._dwell_min_s = (
            max(0.0, dwell_min_s) if dwell_min_s is not None else _read_min_dwell_s()
        )
        self._rotate_on_stable = (
            rotate_on_stable if rotate_on_stable is not None else _read_rotate_on_stable()
        )
        # Anti-recency: deterministic-but-non-trivial picker. Tests can pass
        # a seeded RNG; production constructs without args and gets a
        # process-local Random with monotonic-time seed so two co-running
        # selectors don't lock-step.
        self._rng = rng if rng is not None else random.Random(time.monotonic_ns())

    def select_family(self, stance: str, energy_level: str) -> PresetFamily:
        """Get the preset family for a stance x energy combination."""
        key = (stance, energy_level)
        return _STATE_MATRIX.get(key, _DEFAULT_FAMILY)

    def mark_load_failed(self, preset: str) -> None:
        """Forget a selected preset when the compositor refuses to load it.

        ``evaluate`` records its target before the GL graph load happens.
        If that load fails, holding the refused target through dwell makes
        the 30 fps governance tick retry the same invalid preset every
        frame. Clearing the optimistic selection lets the next tick choose
        a different eligible preset.
        """
        if preset == self._current_preset:
            self._current_preset = None
            self._last_transition = 0.0

    def _pick_with_anti_recency(
        self, candidates: tuple[str, ...], available_presets: set[str]
    ) -> str | None:
        """Pick a preset from ``candidates`` that is loaded and avoids repeating.

        Filters to only loaded presets, drops ``self._current_preset`` when
        another option exists (anti-recency), and randomly picks among the
        survivors. Falls back to ``current_preset`` when it is the only
        loaded option, and returns ``None`` if nothing in ``candidates`` is
        available.
        """
        loaded = tuple(p for p in candidates if p in available_presets)
        if not loaded:
            return None
        # Avoid repeating the same preset twice in a row when the family
        # offers genuine alternatives. This is the load-bearing diversity
        # mechanism — without it, ``first_available`` deterministically
        # picks the first family entry every time.
        non_recent = tuple(p for p in loaded if p != self._current_preset)
        pool = non_recent if non_recent else loaded
        return self._rng.choice(pool)

    def evaluate(
        self,
        stance: str,
        energy_level: str,
        available_presets: set[str],
        genre: str = "",
    ) -> str | None:
        """Evaluate atmospheric state and return the preset to load.

        Returns the current preset if dwell time has not elapsed, or None
        if no preset is available.
        """
        now = time.monotonic()
        genre_lower = genre.lower().strip()
        context = (stance, energy_level, genre_lower)
        stable_context = context == self._current_context

        # Stance change bypasses dwell
        stance_changed = stance != self._current_stance
        self._current_stance = stance

        if self._current_preset is not None and stable_context and not self._rotate_on_stable:
            return self._current_preset

        # Check dwell time (unless stance changed)
        if not stance_changed and (now - self._last_transition) < self._dwell_min_s:
            return self._current_preset

        family = self.select_family(stance, energy_level)

        # Apply genre bias: prepend genre-preferred presets to the family
        bias: list[str] = []
        for keyword, preferred in _GENRE_BIAS.items():
            if keyword in genre_lower:
                bias = preferred
                break
        if bias:
            biased_presets = tuple(p for p in bias if p in available_presets) + family.presets
            family = PresetFamily(presets=biased_presets)

        # Anti-recency rotation: pick a different preset than the current
        # one when the family offers >1 loaded option. This kills the
        # halftone-monoculture failure mode where deterministic
        # ``first_available`` reverts to the first family entry every tick.
        target = self._pick_with_anti_recency(family.presets, available_presets)
        if target is None:
            return self._current_preset
        if target == self._current_preset:
            return self._current_preset

        self._current_preset = target
        self._current_context = (stance, energy_level, genre_lower)
        self._last_transition = now
        return target


# ── Gestural Layer ────────────────────────────────────────────────────────────

# Activity → {(node, param): offset}
_ACTIVITY_OFFSETS: dict[str, dict[tuple[str, str], float]] = {
    "scratching": {
        ("trail", "opacity"): 0.2,
        ("bloom", "alpha"): 0.15,
        ("drift", "speed"): 1.0,
    },
    "drumming": {
        ("bloom", "alpha"): 0.2,
        ("stutter", "freeze_chance"): 0.1,
    },
    "tapping": {
        ("trail", "opacity"): 0.1,
        ("bloom", "alpha"): 0.1,
    },
    "typing": {},  # typing uses modulation_depth_scale instead
}

_GAZE_MODIFIERS: dict[str, float] = {
    "screen": 0.5,
    "hardware": 1.2,
    "away": 1.0,
    "person": 0.8,
}

_GUEST_REDUCTION = 0.6


def compute_gestural_offsets(
    desk_activity: str,
    gaze_direction: str,
    person_count: int,
) -> dict[tuple[str, str], float]:
    """Compute additive parameter offsets from gestural signals.

    Returns dict of {(node_id, param_name): offset_value}.
    """
    base = dict(_ACTIVITY_OFFSETS.get(desk_activity, {}))

    # Gaze modifier scales all offsets
    gaze_scale = _GAZE_MODIFIERS.get(gaze_direction, 1.0)
    for key in base:
        base[key] *= gaze_scale

    # Guest presence reduces intensity
    if person_count >= 2:
        for key in base:
            base[key] *= _GUEST_REDUCTION

    return base


# ── Breathing Substrate ───────────────────────────────────────────────────────


def compute_perlin_drift(t: float, desk_energy: float) -> float:
    """Compute Perlin-like drift value. Inversely proportional to desk_energy.

    Uses layered sine waves at irrational frequencies as a lightweight
    Perlin approximation.
    """
    noise = math.sin(t * 0.13) * 0.5 + math.sin(t * 0.31) * 0.3 + math.sin(t * 0.71) * 0.2
    base_amplitude = 0.03  # 3% wobble
    activity_suppression = min(1.0, desk_energy * 5.0)
    return noise * base_amplitude * (1.0 - activity_suppression)


def compute_idle_escalation(idle_duration_s: float) -> float:
    """Compute drift amplitude multiplier based on idle duration.

    Returns 1.0 immediately, ramps to ~2.7x over 5 minutes, caps at 3.0.
    """
    if idle_duration_s <= 0:
        return 1.0
    return min(3.0, 1.0 + math.log1p(idle_duration_s / 60.0))


# ── Governance Composition ───────────────────────────────────────────────────


class VisualGovernance:
    """Governance composition for visual expression.

    Wraps AtmosphericSelector with deny-wins vetoes and priority-ordered
    fallbacks. Same governance primitives as daimonion's PipelineGovernor.
    """

    def __init__(self, atmospheric: AtmosphericSelector | None = None) -> None:
        self._atmospheric = atmospheric or AtmosphericSelector()
        self._veto_chain: VetoChain[SystemContext] = VetoChain(
            [
                Veto(
                    "block_consent_pending",
                    lambda ctx: ctx.consent_state.get("phase") != "consent_pending",
                    axiom="interpersonal_transparency",
                ),
            ]
        )
        self._fallback: FallbackChain[SystemContext, str] = FallbackChain(
            [
                Candidate(
                    "critical_health",
                    lambda ctx: ctx.stimmung_stance == "critical",
                    "silhouette",
                ),
            ],
            default="atmospheric",
        )

    def evaluate(
        self,
        ctx: SystemContext,
        stance: str,
        energy: str,
        available_presets: list[str],
        genre: str | None = None,
    ) -> str | None:
        """Evaluate visual governance. Returns preset name or None (suppress)."""
        veto = self._veto_chain.evaluate(ctx)
        if not veto.allowed:
            return None

        selected = self._fallback.select(ctx)
        if selected.action != "atmospheric":
            return selected.action

        return self._atmospheric.evaluate(stance, energy, set(available_presets), genre or "")
