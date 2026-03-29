"""Visual chain capability — semantic visual affordances for wgpu shader modulation.

Nine expressive dimensions (same as vocal chain) mapped to wgpu technique
uniforms instead of MIDI CCs. Registered in Qdrant for cross-modal
impingement activation alongside vocal_chain.*.
"""

from __future__ import annotations

import json
import logging
import time as time_mod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shared.affordance import CapabilityRecord, OperationalProperties
from shared.impingement import Impingement

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


class VisualChainCapability:
    """Visual chain as a Capability — recruited for expressive visual modulation."""

    def __init__(self, decay_rate: float = 0.02) -> None:
        self._decay_rate = decay_rate
        self._levels: dict[str, float] = {name: 0.0 for name in VISUAL_DIMENSIONS}
        self._activation_level = 0.0

    @property
    def name(self) -> str:
        return "visual_chain"

    @property
    def affordance_signature(self) -> set[str]:
        return VISUAL_CHAIN_AFFORDANCES

    @property
    def activation_cost(self) -> float:
        return 0.01

    @property
    def activation_level(self) -> float:
        return self._activation_level

    @property
    def consent_required(self) -> bool:
        return False

    @property
    def priority_floor(self) -> bool:
        return False

    def can_resolve(self, impingement: Impingement) -> float:
        """Match impingements that warrant visual modulation."""
        content = impingement.content
        metric = content.get("metric", "")

        if any(aff in metric for aff in VISUAL_CHAIN_AFFORDANCES):
            return impingement.strength

        if "stimmung" in impingement.source:
            return impingement.strength * 0.4

        if "dmn.evaluative" in impingement.source:
            return impingement.strength * 0.3

        return 0.0

    def activate(self, impingement: Impingement, level: float) -> dict[str, Any]:
        """Activate visual chain — sets activation level for cascade tracking."""
        self._activation_level = level
        log.info(
            "Visual chain activated: %s (strength=%.2f, level=%.2f)",
            impingement.content.get("metric", impingement.source),
            impingement.strength,
            level,
        )
        return {"visual_chain_activated": True, "level": level}

    def activate_dimension(
        self, dimension_name: str, impingement: Impingement, level: float
    ) -> None:
        """Activate a specific dimension and update parameter state."""
        if dimension_name not in VISUAL_DIMENSIONS:
            log.debug("Unknown dimension: %s", dimension_name)
            return

        self._levels[dimension_name] = max(0.0, min(1.0, level))
        self._activation_level = max(self._levels.values())

    def get_dimension_level(self, dimension_name: str) -> float:
        """Get the current activation level of a dimension."""
        return self._levels.get(dimension_name, 0.0)

    def compute_param_deltas(self) -> dict[str, float]:
        """Compute summed parameter deltas across all active dimensions."""
        deltas: dict[str, float] = {}
        for dim_name, dim in VISUAL_DIMENSIONS.items():
            level = self._levels.get(dim_name, 0.0)
            for mapping in dim.parameter_mappings:
                key = f"{mapping.technique}.{mapping.param}"
                value = param_value_from_level(level, mapping.breakpoints)
                deltas[key] = deltas.get(key, 0.0) + value
        return deltas

    def decay(self, elapsed_s: float) -> None:
        """Decay all active dimensions toward zero."""
        amount = self._decay_rate * elapsed_s
        any_active = False
        for name in list(self._levels):
            if self._levels[name] > 0.0:
                self._levels[name] = max(0.0, self._levels[name] - amount)
                if self._levels[name] > 0.0:
                    any_active = True

        if not any_active:
            self._activation_level = 0.0
        else:
            self._activation_level = max(self._levels.values())

    def deactivate(self) -> None:
        """Reset all dimensions to zero."""
        for name in self._levels:
            self._levels[name] = 0.0
        self._activation_level = 0.0

    def write_state(self, path: Path | None = None) -> None:
        """Write current state as JSON, atomically via tmp+rename."""
        if path is None:
            path = SHM_PATH
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        levels = {k: v for k, v in self._levels.items() if v > 0.0}
        params = self.compute_param_deltas()
        state = {
            "levels": levels,
            "params": params,
            "timestamp": time_mod.time(),
        }

        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state))
        tmp_path.rename(path)
