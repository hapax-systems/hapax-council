"""Programme-aware substrate palette composition for Reverie (Phase 8).

`Programme.constraints.reverie_saturation_target` is a RANGE CENTRE that
stimmung + transition_energy modulate around. The composed value is a
soft prior — the programme target is not a ceiling, transition energy
can briefly lift saturation above it. This is the architectural axiom
``project_programmes_enable_grounding`` applied to the visual substrate.

Precedence (resolved in ``_uniforms.write_uniforms``):

    1. Programme present + ``reverie_saturation_target`` set
       → composed target overrides ``color.saturation``
    2. Otherwise → fall through to existing HOMAGE A6 package damping
       (BitchX writes 0.40, other packages no-op, missing → plan default)

Plan §Phase 8 (lines 827-903) of
``docs/superpowers/plans/2026-04-20-programme-layer-plan.md``.
"""

from __future__ import annotations

from shared.programme import Programme

# Stimmung-stance → saturation delta. Substrate quiets as system stimmung
# degrades; soft modulation only.
_STIMMUNG_STANCE_DELTA: dict[str, float] = {
    "nominal": 0.0,
    "seeking": 0.05,
    "cautious": -0.05,
    "degraded": -0.10,
    "critical": -0.15,
}

# Per-tick transition_energy contribution to saturation. The +0.1 ceiling
# is the spec-mandated "brief lift" amount — high enough to be visible
# above a quiet programme target, low enough that it cannot drown out
# stimmung modulation. Plan §Phase 8 line 847.
_TRANSITION_ENERGY_GAIN: float = 0.10


def stimmung_delta(stimmung: dict | None) -> float:
    """Stance-derived saturation delta, bounded by the stance table."""
    if not stimmung:
        return 0.0
    stance = stimmung.get("overall_stance", "nominal")
    return _STIMMUNG_STANCE_DELTA.get(stance, 0.0)


def compute_substrate_saturation(
    programme: Programme | None,
    stimmung: dict | None = None,
    transition_energy: float = 0.0,
) -> float | None:
    """Compose the programme-aware saturation target.

    Returns ``None`` when no programme target is set so the caller can
    fall through to package damping or plan defaults. Returns a clamped
    value in ``[0.0, 1.0]`` when a target is composed.

    Soft-prior property: the returned value is the composition
    ``target + stimmung_delta + 0.10 * transition_energy`` clamped to
    the unit interval. ``transition_energy`` of 1.0 with a target of
    ``0.30`` yields ``0.40`` (or higher if stimmung also lifts) —
    the programme centre is not a ceiling.
    """
    if programme is None:
        return None
    target = programme.constraints.reverie_saturation_target
    if target is None:
        return None
    delta = stimmung_delta(stimmung)
    energy = max(0.0, min(1.0, float(transition_energy)))
    composed = target + delta + _TRANSITION_ENERGY_GAIN * energy
    return max(0.0, min(1.0, composed))


__all__ = [
    "compute_substrate_saturation",
    "stimmung_delta",
]
