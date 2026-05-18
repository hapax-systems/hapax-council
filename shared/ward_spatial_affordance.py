"""Ward spatial affordance model for the Nebulous Scrim.

Each ward declares where on the scrim it prefers to live, how fast it
drifts, what its depth band is, and which other wards it pushes/pulls.
The Choreographer's placement post-pass composes these with the active
Programme's scrim_mode_priors to produce final placement tuples.

Phase 0 of the Nebulous Scrim implementation.
Spec: docs/research/2026-04-20-homage-scrim-1-algorithmic-intelligence.md
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class DepthBand(StrEnum):
    FOREGROUND = "foreground"
    MIDGROUND = "midground"
    BACKGROUND = "background"
    SUBSTRATE = "substrate"


class FishbowlMode(StrEnum):
    DEEP_WATER = "deep-water"
    SHALLOWS = "shallows"
    CURRENT = "current"
    STILL_POOL = "still-pool"


class CompositionAttractor(BaseModel):
    x: float = Field(ge=0.0, le=1.0, description="Normalized x attractor (0=left, 1=right)")
    y: float = Field(ge=0.0, le=1.0, description="Normalized y attractor (0=top, 1=bottom)")
    weight: float = Field(default=1.0, ge=0.0, le=10.0)


class MotionPriors(BaseModel):
    drift_velocity_min: float = Field(default=0.0, ge=0.0, description="Pixels/second minimum")
    drift_velocity_max: float = Field(default=5.0, ge=0.0, description="Pixels/second maximum")
    vibration_amplitude: float = Field(default=0.0, ge=0.0, description="Sub-pixel oscillation")
    breath_period_s: float = Field(default=4.0, gt=0.0, description="Slow pulsation period")


class WardSpatialAffordance(BaseModel):
    """Declared spatial behavior for a single ward type."""

    source_id: str = Field(description="Ward source identifier (e.g., 'token-pole', 'sierpinski')")
    depth_band: DepthBand = Field(default=DepthBand.MIDGROUND)
    composition_attractors: list[CompositionAttractor] = Field(
        default_factory=lambda: [CompositionAttractor(x=0.333, y=0.333)],
        description="Preferred composition positions (rule-of-thirds intersections)",
    )
    motion: MotionPriors = Field(default_factory=MotionPriors)
    scale_range: tuple[float, float] = Field(default=(0.5, 1.5), description="Min/max scale factor")
    opacity_range: tuple[float, float] = Field(default=(0.3, 1.0), description="Min/max opacity")
    push_sources: list[str] = Field(default_factory=list, description="Ward IDs this repels")
    pull_sources: list[str] = Field(
        default_factory=list, description="Ward IDs this attracts toward"
    )
    hero_eligible: bool = Field(
        default=False, description="Can this ward be the single hero in still-pool mode"
    )
    beat_responsive: bool = Field(default=False, description="Does motion respond to audio onsets")


class ScrimModePriors(BaseModel):
    """Programme-supplied soft priors for scrim fishbowl mode."""

    fishbowl_mode: FishbowlMode = Field(default=FishbowlMode.DEEP_WATER)
    max_simultaneous_wards: int = Field(default=4, ge=1, le=12)
    negative_space_ratio: float = Field(default=0.6, ge=0.0, le=1.0)
    drift_gain: float = Field(
        default=1.0, ge=0.0, le=5.0, description="Multiplier on ward drift velocities"
    )
    depth_spread: float = Field(
        default=1.0, ge=0.0, le=2.0, description="How much depth separation between wards"
    )
    attention_budget: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Total attention demand budget"
    )


WARD_SPATIAL_REGISTRY: dict[str, WardSpatialAffordance] = {
    "sierpinski": WardSpatialAffordance(
        source_id="sierpinski",
        depth_band=DepthBand.SUBSTRATE,
        composition_attractors=[CompositionAttractor(x=0.5, y=0.5, weight=10.0)],
        motion=MotionPriors(drift_velocity_min=0, drift_velocity_max=0, breath_period_s=8.0),
        scale_range=(1.0, 1.0),
        opacity_range=(0.8, 1.0),
        hero_eligible=True,
    ),
    "token-pole": WardSpatialAffordance(
        source_id="token-pole",
        depth_band=DepthBand.FOREGROUND,
        composition_attractors=[
            CompositionAttractor(x=0.667, y=0.333, weight=2.0),
            CompositionAttractor(x=0.333, y=0.667, weight=1.5),
        ],
        motion=MotionPriors(drift_velocity_max=2.0, breath_period_s=6.0),
        scale_range=(0.4, 1.2),
        push_sources=["hardm"],
    ),
    "hardm": WardSpatialAffordance(
        source_id="hardm",
        depth_band=DepthBand.MIDGROUND,
        composition_attractors=[CompositionAttractor(x=0.5, y=0.5, weight=3.0)],
        motion=MotionPriors(drift_velocity_max=1.0, vibration_amplitude=0.5, breath_period_s=4.0),
        scale_range=(0.3, 0.8),
        opacity_range=(0.5, 1.0),
        hero_eligible=True,
        beat_responsive=True,
    ),
    "album": WardSpatialAffordance(
        source_id="album",
        depth_band=DepthBand.FOREGROUND,
        composition_attractors=[
            CompositionAttractor(x=0.167, y=0.5, weight=2.0),
            CompositionAttractor(x=0.833, y=0.5, weight=2.0),
        ],
        motion=MotionPriors(drift_velocity_max=0.5),
        scale_range=(0.3, 0.6),
        push_sources=["token-pole"],
    ),
    "clock": WardSpatialAffordance(
        source_id="clock",
        depth_band=DepthBand.FOREGROUND,
        composition_attractors=[CompositionAttractor(x=0.95, y=0.05, weight=5.0)],
        motion=MotionPriors(drift_velocity_max=0),
        scale_range=(0.15, 0.25),
        opacity_range=(0.6, 0.9),
    ),
    "pango-overlay": WardSpatialAffordance(
        source_id="pango-overlay",
        depth_band=DepthBand.FOREGROUND,
        composition_attractors=[
            CompositionAttractor(x=0.5, y=0.9, weight=3.0),
        ],
        motion=MotionPriors(drift_velocity_max=0),
        scale_range=(0.8, 1.0),
        opacity_range=(0.7, 1.0),
    ),
    "pip-camera": WardSpatialAffordance(
        source_id="pip-camera",
        depth_band=DepthBand.FOREGROUND,
        composition_attractors=[
            CompositionAttractor(x=0.167, y=0.167, weight=2.0),
            CompositionAttractor(x=0.833, y=0.833, weight=2.0),
        ],
        motion=MotionPriors(drift_velocity_max=0.5),
        scale_range=(0.15, 0.35),
    ),
}


FISHBOWL_MODE_DEFAULTS: dict[FishbowlMode, ScrimModePriors] = {
    FishbowlMode.DEEP_WATER: ScrimModePriors(
        fishbowl_mode=FishbowlMode.DEEP_WATER,
        max_simultaneous_wards=3,
        negative_space_ratio=0.7,
        drift_gain=0.5,
        depth_spread=1.5,
        attention_budget=0.3,
    ),
    FishbowlMode.SHALLOWS: ScrimModePriors(
        fishbowl_mode=FishbowlMode.SHALLOWS,
        max_simultaneous_wards=6,
        negative_space_ratio=0.4,
        drift_gain=1.2,
        depth_spread=0.8,
        attention_budget=0.7,
    ),
    FishbowlMode.CURRENT: ScrimModePriors(
        fishbowl_mode=FishbowlMode.CURRENT,
        max_simultaneous_wards=5,
        negative_space_ratio=0.5,
        drift_gain=2.0,
        depth_spread=1.0,
        attention_budget=0.6,
    ),
    FishbowlMode.STILL_POOL: ScrimModePriors(
        fishbowl_mode=FishbowlMode.STILL_POOL,
        max_simultaneous_wards=1,
        negative_space_ratio=0.85,
        drift_gain=0.1,
        depth_spread=0.3,
        attention_budget=0.15,
    ),
}


def get_ward_affordance(source_id: str) -> WardSpatialAffordance | None:
    return WARD_SPATIAL_REGISTRY.get(source_id)


def get_fishbowl_defaults(mode: FishbowlMode) -> ScrimModePriors:
    return FISHBOWL_MODE_DEFAULTS.get(mode, FISHBOWL_MODE_DEFAULTS[FishbowlMode.DEEP_WATER])
