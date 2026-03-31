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
import time

from agents._capability import SystemContext
from agents._governance.primitives import Candidate, FallbackChain, Veto, VetoChain
from agents.effect_graph.types import PresetFamily

# ── Atmospheric Layer ─────────────────────────────────────────────────────────

# State matrix: stance × energy_level → PresetFamily
_STATE_MATRIX: dict[tuple[str, str], PresetFamily] = {
    # NOMINAL
    ("nominal", "low"): PresetFamily(presets=("clean", "ambient")),
    ("nominal", "medium"): PresetFamily(presets=("trails", "ghost")),
    ("nominal", "high"): PresetFamily(presets=("feedback_preset", "kaleidodream")),
    # CAUTIOUS
    ("cautious", "low"): PresetFamily(presets=("ambient",)),
    ("cautious", "medium"): PresetFamily(presets=("ghost",)),
    ("cautious", "high"): PresetFamily(presets=("trails",)),
    # DEGRADED
    ("degraded", "low"): PresetFamily(presets=("dither_retro", "vhs_preset")),
    ("degraded", "medium"): PresetFamily(presets=("vhs_preset",)),
    ("degraded", "high"): PresetFamily(presets=("screwed",)),
    # CRITICAL
    ("critical", "low"): PresetFamily(presets=("silhouette",)),
    ("critical", "medium"): PresetFamily(presets=("silhouette",)),
    ("critical", "high"): PresetFamily(presets=("silhouette",)),
}

# Genre bias: genre keyword → list of preferred preset names (prepended to family)
_GENRE_BIAS: dict[str, list[str]] = {
    "hip hop": ["trap", "screwed", "ghost"],
    "trap": ["trap", "screwed", "ghost"],
    "lo-fi": ["vhs_preset", "dither_retro", "ambient"],
    "jazz": ["vhs_preset", "dither_retro", "ambient"],
    "soul": ["vhs_preset", "ambient"],
    "electronic": ["voronoi_crystal", "tunnel_vision", "kaleidodream"],
    "ambient": ["voronoi_crystal", "tunnel_vision", "kaleidodream"],
}

_DWELL_MIN_S = 30.0  # minimum seconds before atmospheric transition


def energy_level_from_activity(desk_activity: str) -> str:
    """Map desk_activity classification to energy level."""
    if desk_activity in ("drumming", "scratching"):
        return "high"
    if desk_activity in ("tapping",):
        return "medium"
    return "low"


class AtmosphericSelector:
    """State machine for atmospheric preset selection."""

    def __init__(self) -> None:
        self._current_preset: str | None = None
        self._current_stance: str = "nominal"
        self._last_transition: float = 0.0

    def select_family(self, stance: str, energy_level: str) -> PresetFamily:
        """Get the preset family for a stance x energy combination."""
        key = (stance, energy_level)
        return _STATE_MATRIX.get(key, PresetFamily(presets=("clean",)))

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

        # Stance change bypasses dwell
        stance_changed = stance != self._current_stance
        self._current_stance = stance

        # Check dwell time (unless stance changed)
        if not stance_changed and (now - self._last_transition) < _DWELL_MIN_S:
            return self._current_preset

        family = self.select_family(stance, energy_level)

        # Apply genre bias: prepend genre-preferred presets to the family
        genre_lower = genre.lower().strip()
        bias: list[str] = []
        for keyword, preferred in _GENRE_BIAS.items():
            if keyword in genre_lower:
                bias = preferred
                break
        if bias:
            biased_presets = tuple(p for p in bias if p in available_presets) + family.presets
            family = PresetFamily(presets=biased_presets)

        target = family.first_available(available_presets)
        if target is None or target == self._current_preset:
            return self._current_preset

        self._current_preset = target
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
