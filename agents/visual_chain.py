"""Visual chain capability — semantic visual affordances for wgpu shader modulation.

Nine expressive dimensions (same as vocal chain) mapped to wgpu shader graph
node uniforms. Registered in Qdrant for cross-modal impingement activation.
"""

from __future__ import annotations

import json
import logging
import time as time_mod
from dataclasses import dataclass
from pathlib import Path

from agents._affordance import CapabilityRecord, OperationalProperties
from agents._impingement import Impingement

log = logging.getLogger(__name__)

SHM_PATH = Path("/dev/shm/hapax-visual/visual-chain-state.json")


@dataclass(frozen=True)
class ParameterMapping:
    """Maps an activation level to a specific shader graph node uniform."""

    technique: str  # vocabulary node ID: "noise", "fb", "post", "rd", "physarum"
    param: str
    breakpoints: list[tuple[float, float]]


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


# Reusable breakpoint curves (all produce 0.0 at level=0.0)
_STD = [(0.0, 0.0), (0.25, 0.10), (0.50, 0.25), (0.75, 0.50), (1.0, 1.0)]
_INV = [(0.0, 0.0), (0.50, -0.10), (1.0, -0.30)]

_PM = ParameterMapping  # shorthand

VISUAL_DIMENSIONS: dict[str, VisualDimension] = {
    "visual_chain.intensity": VisualDimension(
        "visual_chain.intensity",
        "Increases visual energy and density — brighter, more saturated, more present.",
        [_PM("noise", "amplitude", _STD), _PM("post", "vignette_strength", _INV)],
    ),
    "visual_chain.tension": VisualDimension(
        "visual_chain.tension",
        "Constricts visual patterns — tighter, sharper, angular energy.",
        [
            _PM("rd", "feed_rate", [(0.0, 0.0), (0.5, 0.005), (1.0, 0.015)]),
            _PM("noise", "frequency_x", [(0.0, 0.0), (0.5, 0.5), (1.0, 2.0)]),
        ],
    ),
    "visual_chain.diffusion": VisualDimension(
        "visual_chain.diffusion",
        "Scatters visual output — ambient, sourceless, environmental.",
        [
            _PM("rd", "diffusion_a", [(0.0, 0.0), (0.5, 0.1), (1.0, 0.4)]),
            _PM("drift", "amplitude", [(0.0, 0.0), (0.5, 0.3), (1.0, 0.8)]),
        ],
    ),
    "visual_chain.degradation": VisualDimension(
        "visual_chain.degradation",
        "Corrupts visual signal — noise, disruption, broken patterns.",
        [
            _PM("noise", "octaves", [(0.0, 0.0), (0.5, 1.0), (1.0, 3.0)]),
            _PM("post", "sediment_strength", [(0.0, 0.0), (0.5, 0.02), (1.0, 0.08)]),
        ],
    ),
    "visual_chain.depth": VisualDimension(
        "visual_chain.depth",
        "Places visual in recessive space — darkens, recedes, cave-like.",
        [_PM("noise", "amplitude", _INV), _PM("post", "vignette_strength", _STD)],
    ),
    "visual_chain.pitch_displacement": VisualDimension(
        "visual_chain.pitch_displacement",
        "Shifts visual color — hue rotation, displaced and uncanny.",
        [
            _PM("color", "hue_rotate", [(0.0, 0.0), (0.5, 25.0), (1.0, 70.0)]),
            _PM("fb", "hue_shift", [(0.0, 0.0), (0.5, 1.5), (1.0, 5.0)]),
            _PM("color", "saturation", [(0.0, 0.0), (0.5, 0.1), (1.0, 0.3)]),
        ],
    ),
    "visual_chain.temporal_distortion": VisualDimension(
        "visual_chain.temporal_distortion",
        "Stretches or accelerates visual animation in time.",
        [
            _PM("noise", "speed", [(0.0, 0.0), (0.3, -0.03), (0.7, 0.0), (1.0, 0.15)]),
            _PM("drift", "speed", [(0.0, 0.0), (0.3, -0.1), (0.7, 0.0), (1.0, 0.5)]),
        ],
    ),
    "visual_chain.spectral_color": VisualDimension(
        "visual_chain.spectral_color",
        "Shifts visual warmth and saturation — tonal character changes.",
        [
            _PM("color", "saturation", [(0.0, 0.0), (0.5, 0.25), (1.0, 0.6)]),
            _PM("color", "brightness", [(0.0, 0.0), (0.5, 0.1), (1.0, 0.3)]),
        ],
    ),
    "visual_chain.coherence": VisualDimension(
        "visual_chain.coherence",
        "Controls pattern regularity — structured to dissolved.",
        [
            _PM("noise", "frequency_x", [(0.0, 0.0), (0.5, -0.5), (1.0, -1.5)]),
            _PM("rd", "feed_rate", [(0.0, 0.0), (0.5, -0.005), (1.0, -0.015)]),
            _PM("fb", "decay", [(0.0, 0.0), (0.5, 0.05), (1.0, 0.15)]),
        ],
    ),
}

VISUAL_CHAIN_RECORDS = [
    CapabilityRecord(
        name=dim.name,
        description=dim.description,
        daemon="visual_layer_aggregator",
        operational=OperationalProperties(latency_class="realtime", medium="visual"),
    )
    for dim in VISUAL_DIMENSIONS.values()
]

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
        metric = impingement.content.get("metric", "")
        if any(aff in metric for aff in VISUAL_CHAIN_AFFORDANCES):
            return impingement.strength
        if "stimmung" in impingement.source:
            return impingement.strength * 0.4
        if "dmn.evaluative" in impingement.source:
            return impingement.strength * 0.3
        return 0.0

    def activate(self, impingement: Impingement, level: float) -> dict[str, object]:
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
        self._activation_level = max(self._levels.values()) if any_active else 0.0

    def deactivate(self) -> None:
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
        state = {"levels": levels, "params": params, "timestamp": time_mod.time()}
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state))
        tmp_path.rename(path)
