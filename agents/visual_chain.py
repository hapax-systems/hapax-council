"""Visual chain capability — semantic visual affordances for wgpu shader modulation.

Nine expressive dimensions (same as vocal chain) mapped to wgpu technique
uniforms instead of MIDI CCs. Registered in Qdrant for cross-modal
impingement activation alongside vocal_chain.*.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from shared.affordance import CapabilityRecord, OperationalProperties

log = logging.getLogger(__name__)

SHM_PATH = Path("/dev/shm/hapax-visual/visual-chain-state.json")


@dataclass(frozen=True)
class ParameterMapping:
    """Maps an activation level to a specific wgpu technique uniform."""

    technique: str  # "gradient", "rd", "physarum", "compositor", "postprocess"
    param: str  # uniform name
    breakpoints: list[tuple[float, float]]  # (level, param_value)


@dataclass(frozen=True)
class VisualDimension:
    """A semantic visual modulation dimension."""

    name: str
    description: str
    parameter_mappings: list[ParameterMapping]


def param_value_from_level(level: float, breakpoints: list[tuple[float, float]]) -> float:
    """Interpolate parameter value from activation level using piecewise linear breakpoints."""
    level = max(0.0, min(1.0, level))
    if level <= breakpoints[0][0]:
        return breakpoints[0][1]
    if level >= breakpoints[-1][0]:
        return breakpoints[-1][1]
    for i in range(len(breakpoints) - 1):
        l0, v0 = breakpoints[i]
        l1, v1 = breakpoints[i + 1]
        if l0 <= level <= l1:
            t = (level - l0) / (l1 - l0) if l1 != l0 else 0.0
            return v0 + t * (v1 - v0)
    return breakpoints[-1][1]


# ---------------------------------------------------------------------------
# Reusable breakpoint curves (all produce 0.0 at level=0.0)
# ---------------------------------------------------------------------------

_GENTLE = [(0.0, 0.0), (0.25, 0.05), (0.50, 0.15), (0.75, 0.30), (1.0, 0.50)]
_STANDARD = [(0.0, 0.0), (0.25, 0.10), (0.50, 0.25), (0.75, 0.50), (1.0, 1.0)]
_AGGRESSIVE = [(0.0, 0.0), (0.25, 0.15), (0.50, 0.40), (0.75, 0.70), (1.0, 1.0)]
_INVERTED = [(0.0, 0.0), (0.50, -0.10), (1.0, -0.30)]

VISUAL_DIMENSIONS: dict[str, VisualDimension] = {
    "visual_chain.intensity": VisualDimension(
        name="visual_chain.intensity",
        description=(
            "Increases visual energy and density. Display becomes brighter, more "
            "saturated, more present. Distinct from emotional valence — pure energy."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "brightness", _STANDARD),
            ParameterMapping("compositor", "opacity_rd", [(0.0, 0.0), (0.5, 0.1), (1.0, 0.3)]),
            ParameterMapping("postprocess", "vignette_strength", _INVERTED),
        ],
    ),
    "visual_chain.tension": VisualDimension(
        name="visual_chain.tension",
        description=(
            "Constricts visual patterns. Display tightens, sharpens, builds angular "
            "energy. Turing patterns become finer, waves increase frequency."
        ),
        parameter_mappings=[
            ParameterMapping("rd", "f_delta", [(0.0, 0.0), (0.5, 0.005), (1.0, 0.015)]),
            ParameterMapping("compositor", "opacity_wave", [(0.0, 0.0), (0.5, 0.1), (1.0, 0.3)]),
            ParameterMapping("gradient", "turbulence", [(0.0, 0.0), (0.5, -0.03), (1.0, -0.06)]),
        ],
    ),
    "visual_chain.diffusion": VisualDimension(
        name="visual_chain.diffusion",
        description=(
            "Scatters visual output across spatial field. Patterns become ambient, "
            "sourceless, environmental. Structure dissolves into texture at high levels."
        ),
        parameter_mappings=[
            ParameterMapping("physarum", "sensor_dist", [(0.0, 0.0), (0.5, 4.0), (1.0, 12.0)]),
            ParameterMapping("rd", "da_delta", [(0.0, 0.0), (0.5, 0.05), (1.0, 0.2)]),
            ParameterMapping(
                "compositor", "opacity_feedback", [(0.0, 0.0), (0.5, 0.08), (1.0, 0.2)]
            ),
        ],
    ),
    "visual_chain.degradation": VisualDimension(
        name="visual_chain.degradation",
        description=(
            "Corrupts visual signal. Display fractures into noise, disruption, "
            "broken pattern. System malfunction expressed through visual artifacts."
        ),
        parameter_mappings=[
            ParameterMapping("physarum", "deposit_amount", [(0.0, 0.0), (0.5, 2.0), (1.0, 6.0)]),
            ParameterMapping(
                "compositor", "opacity_physarum", [(0.0, 0.0), (0.5, 0.05), (1.0, 0.15)]
            ),
            ParameterMapping(
                "postprocess", "sediment_height", [(0.0, 0.0), (0.5, 0.02), (1.0, 0.08)]
            ),
        ],
    ),
    "visual_chain.depth": VisualDimension(
        name="visual_chain.depth",
        description=(
            "Places visual in recessive space. Display darkens, recedes, "
            "becomes distant and cave-like. Vignette intensifies."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "brightness", _INVERTED),
            ParameterMapping("postprocess", "vignette_strength", _STANDARD),
            ParameterMapping(
                "compositor", "opacity_feedback", [(0.0, 0.0), (0.5, 0.08), (1.0, 0.2)]
            ),
        ],
    ),
    "visual_chain.pitch_displacement": VisualDimension(
        name="visual_chain.pitch_displacement",
        description=(
            "Shifts visual color away from natural register. Hue rotates, "
            "colors become displaced and uncanny without changing brightness."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "hue_offset", [(0.0, 0.0), (0.5, 25.0), (1.0, 70.0)]),
            ParameterMapping("feedback", "hue_shift", [(0.0, 0.0), (0.5, 1.5), (1.0, 5.0)]),
            ParameterMapping("gradient", "chroma_boost", [(0.0, 0.0), (0.5, 0.02), (1.0, 0.05)]),
        ],
    ),
    "visual_chain.temporal_distortion": VisualDimension(
        name="visual_chain.temporal_distortion",
        description=(
            "Stretches or accelerates visual animation in time. Patterns elongate, "
            "slow, or rush. Temporal continuity shifts."
        ),
        parameter_mappings=[
            ParameterMapping(
                "gradient",
                "speed",
                [(0.0, 0.0), (0.3, -0.03), (0.7, 0.0), (1.0, 0.15)],
            ),
            ParameterMapping(
                "physarum",
                "move_speed",
                [(0.0, 0.0), (0.3, -0.3), (0.7, 0.0), (1.0, 1.5)],
            ),
        ],
    ),
    "visual_chain.spectral_color": VisualDimension(
        name="visual_chain.spectral_color",
        description=(
            "Shifts visual warmth and saturation. Display becomes cooler or warmer, "
            "more or less chromatic. Tonal character changes."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "color_warmth", [(0.0, 0.0), (0.5, 0.25), (1.0, 0.6)]),
            ParameterMapping("gradient", "chroma_boost", [(0.0, 0.0), (0.5, 0.02), (1.0, 0.06)]),
        ],
    ),
    "visual_chain.coherence": VisualDimension(
        name="visual_chain.coherence",
        description=(
            "Controls pattern regularity. Master axis from structured to dissolved. "
            "Affects overall visual turbulence and pattern stability."
        ),
        parameter_mappings=[
            ParameterMapping("gradient", "turbulence", _STANDARD),
            ParameterMapping("rd", "f_delta", [(0.0, 0.0), (0.5, -0.005), (1.0, -0.015)]),
            ParameterMapping("physarum", "turn_speed", [(0.0, 0.0), (0.5, 0.15), (1.0, 0.5)]),
        ],
    ),
}

# CapabilityRecords for Qdrant indexing
VISUAL_CHAIN_RECORDS = [
    CapabilityRecord(
        name=dim.name,
        description=dim.description,
        daemon="visual_layer_aggregator",
        operational=OperationalProperties(latency_class="realtime"),
    )
    for dim in VISUAL_DIMENSIONS.values()
]

# Affordance keywords for can_resolve matching
VISUAL_CHAIN_AFFORDANCES = {
    "visual_modulation",
    "stimmung_shift",
    "visual_character",
    "display_texture",
    "ambient_expression",
}
