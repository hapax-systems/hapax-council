"""Vocal chain capability — semantic MIDI affordances for speech modulation.

Nine expressive dimensions (intensity, tension, diffusion, etc.) indexed
independently in Qdrant. Each dimension maps to CC parameters on the
Evil Pet and Torso S-4. Activation is hold-and-decay: levels persist
until shifted by another impingement or decayed by a timer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from agents._affordance import CapabilityRecord, OperationalProperties
from agents._impingement import Impingement

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CCMapping:
    """Maps an activation level to a specific MIDI CC on a specific device."""

    device: str  # "evil_pet" or "s4"
    cc: int
    # Piecewise linear breakpoints: (level, cc_value)
    breakpoints: list[tuple[float, int]]


@dataclass(frozen=True)
class Dimension:
    """A semantic vocal modulation dimension."""

    name: str
    description: str
    cc_mappings: list[CCMapping]


def cc_value_from_level(level: float, breakpoints: list[tuple[float, int]]) -> int:
    """Interpolate CC value from activation level using piecewise linear breakpoints."""
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
            return round(v0 + t * (v1 - v0))
    return breakpoints[-1][1]


_STD_CURVE = [(0.0, 0), (0.25, 20), (0.50, 50), (0.75, 85), (1.0, 127)]
_GENTLE_CURVE = [(0.0, 0), (0.25, 15), (0.50, 35), (0.75, 65), (1.0, 100)]
_CENTER_CURVE = [(0.0, 64), (0.25, 72), (0.50, 85), (0.75, 105), (1.0, 127)]

DIMENSIONS: dict[str, Dimension] = {
    "vocal_chain.intensity": Dimension(
        name="vocal_chain.intensity",
        description="Increases vocal energy and density. Speech becomes louder, more present, more forceful. Distinct from emotional valence — pure physical energy.",
        cc_mappings=[
            CCMapping("evil_pet", 40, _STD_CURVE),
            CCMapping("evil_pet", 46, _GENTLE_CURVE),
            CCMapping("s4", 69, _STD_CURVE),
            CCMapping("s4", 63, _GENTLE_CURVE),
        ],
    ),
    "vocal_chain.tension": Dimension(
        name="vocal_chain.tension",
        description="Constricts vocal timbre. Speech sounds strained, tight, forced through resistance. Harmonics sharpen, resonance builds. Distinct from volume.",
        cc_mappings=[
            CCMapping("evil_pet", 71, _STD_CURVE),
            CCMapping("evil_pet", 39, _GENTLE_CURVE),
            CCMapping("s4", 79, _STD_CURVE),
            CCMapping("s4", 94, _GENTLE_CURVE),
        ],
    ),
    "vocal_chain.diffusion": Dimension(
        name="vocal_chain.diffusion",
        description="Scatters vocal output across spatial field. Speech becomes ambient, sourceless, environmental. Words dissolve into texture at high levels.",
        cc_mappings=[
            CCMapping("evil_pet", 42, _STD_CURVE),
            CCMapping("evil_pet", 43, _GENTLE_CURVE),
            CCMapping("s4", 67, _STD_CURVE),
            CCMapping("s4", 66, _GENTLE_CURVE),
        ],
    ),
    "vocal_chain.degradation": Dimension(
        name="vocal_chain.degradation",
        description="Corrupts vocal signal. Speech fractures into digital artifacts, broken transmission, static. System malfunction expressed through voice.",
        cc_mappings=[
            CCMapping("evil_pet", 39, _STD_CURVE),
            CCMapping("evil_pet", 84, [(0.0, 0), (0.5, 80), (1.0, 110)]),
            CCMapping("s4", 96, _STD_CURVE),
            CCMapping("s4", 98, _GENTLE_CURVE),
        ],
    ),
    "vocal_chain.depth": Dimension(
        name="vocal_chain.depth",
        description="Places voice in reverberant space. Distant, cathedral-like, submerged. Speech recedes from foreground without losing content at low levels.",
        cc_mappings=[
            CCMapping("evil_pet", 91, _STD_CURVE),
            CCMapping("evil_pet", 93, _GENTLE_CURVE),
            CCMapping("s4", 112, _STD_CURVE),
            CCMapping("s4", 113, _GENTLE_CURVE),
        ],
    ),
    "vocal_chain.pitch_displacement": Dimension(
        name="vocal_chain.pitch_displacement",
        description="Shifts vocal pitch away from natural register. Higher, lower, or unstable. Uncanny displacement without volume or timbre change.",
        cc_mappings=[
            CCMapping("evil_pet", 44, _CENTER_CURVE),
            CCMapping("s4", 62, _CENTER_CURVE),
            CCMapping("s4", 68, _GENTLE_CURVE),
        ],
    ),
    "vocal_chain.temporal_distortion": Dimension(
        name="vocal_chain.temporal_distortion",
        description="Stretches, freezes, or stutters speech in time. Words elongate, fragment, or loop. Temporal continuity breaks down.",
        cc_mappings=[
            CCMapping("evil_pet", 50, [(0.0, 100), (0.5, 60), (1.0, 10)]),
            CCMapping("s4", 63, [(0.0, 64), (0.5, 30), (1.0, 5)]),
            CCMapping("s4", 65, _STD_CURVE),
        ],
    ),
    "vocal_chain.spectral_color": Dimension(
        name="vocal_chain.spectral_color",
        description="Shifts vocal brightness and metallicity. Dark, bright, hollow, metallic. Changes tonal character without changing pitch or volume.",
        cc_mappings=[
            CCMapping("evil_pet", 70, _CENTER_CURVE),
            CCMapping("s4", 83, _CENTER_CURVE),
            CCMapping("s4", 88, _CENTER_CURVE),
        ],
    ),
    "vocal_chain.coherence": Dimension(
        name="vocal_chain.coherence",
        description="Controls intelligibility of speech. Master axis from clear human voice to pure abstract texture. Affects overall processing depth.",
        cc_mappings=[
            CCMapping("evil_pet", 40, _STD_CURVE),
            CCMapping("s4", 69, _STD_CURVE),
            CCMapping("s4", 85, _GENTLE_CURVE),
        ],
    ),
}

VOCAL_CHAIN_RECORDS = [
    CapabilityRecord(
        name=dim.name,
        description=dim.description,
        daemon="hapax_daimonion",
        operational=OperationalProperties(latency_class="fast"),
    )
    for dim in DIMENSIONS.values()
]

VOCAL_CHAIN_AFFORDANCES = {
    "vocal_modulation",
    "stimmung_shift",
    "voice_character",
    "speech_texture",
    "conversational_tone",
}


class VocalChainCapability:
    """Vocal chain as a Capability — recruited for expressive speech modulation."""

    def __init__(
        self,
        midi_output: Any,
        evil_pet_channel: int = 0,
        s4_channel: int = 1,
        decay_rate: float = 0.02,
    ) -> None:
        self._midi = midi_output
        self._evil_pet_ch = evil_pet_channel
        self._s4_ch = s4_channel
        self._decay_rate = decay_rate
        self._levels: dict[str, float] = {name: 0.0 for name in DIMENSIONS}
        self._activation_level = 0.0

    @property
    def name(self) -> str:
        return "vocal_chain"

    @property
    def affordance_signature(self) -> set[str]:
        return VOCAL_CHAIN_AFFORDANCES

    @property
    def activation_cost(self) -> float:
        return 0.05  # MIDI CC is nearly free

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
        """Match impingements that warrant vocal modulation."""
        metric = impingement.content.get("metric", "")
        if any(aff in metric for aff in VOCAL_CHAIN_AFFORDANCES):
            return impingement.strength
        if "stimmung" in impingement.source:
            return impingement.strength * 0.4
        if "dmn.evaluative" in impingement.source:
            return impingement.strength * 0.3
        return 0.0

    def activate(self, impingement: Impingement, level: float) -> dict[str, object]:
        """Activate vocal chain — sets activation level for cascade tracking."""
        self._activation_level = level
        log.info(
            "Vocal chain activated: %s (strength=%.2f, level=%.2f)",
            impingement.content.get("metric", impingement.source),
            impingement.strength,
            level,
        )
        return {"vocal_chain_activated": True, "level": level}

    def activate_from_impingement(self, impingement: Impingement) -> dict[str, object]:
        """Activate vocal chain dimensions from impingement content.

        Accepts bare names ("intensity") or fully-qualified ("vocal_chain.intensity").
        """
        dims = impingement.context.get("dimensions", {})
        activated: list[str] = []
        for raw, level in dims.items():
            if not isinstance(level, (int, float)):
                continue
            key = raw if raw in DIMENSIONS else f"vocal_chain.{raw}"
            if key in DIMENSIONS:
                self.activate_dimension(key, impingement, float(level))
                activated.append(key)
        if not activated:
            score = self.can_resolve(impingement)
            if score > 0:
                self.activate(impingement, score)
                return {"activated": True, "level": score, "dimensions": []}
        return {
            "activated": bool(activated),
            "level": self._activation_level,
            "dimensions": activated,
        }

    def activate_dimension(
        self, dimension_name: str, impingement: Impingement, level: float
    ) -> None:
        """Activate a specific dimension and send corresponding MIDI CCs."""
        if dimension_name not in DIMENSIONS:
            log.debug("Unknown dimension: %s", dimension_name)
            return
        self._levels[dimension_name] = max(0.0, min(1.0, level))
        self._activation_level = max(self._levels.values())
        self._send_dimension_cc(dimension_name)

    def get_dimension_level(self, dimension_name: str) -> float:
        """Get the current activation level of a dimension.

        Accepts bare names ("intensity") or fully-qualified ("vocal_chain.intensity").
        """
        key = dimension_name if dimension_name in self._levels else f"vocal_chain.{dimension_name}"
        return self._levels.get(key, 0.0)

    def decay(self, elapsed_s: float) -> None:
        """Decay all active dimensions toward transparent."""
        amount = self._decay_rate * elapsed_s
        any_active = False
        for name in list(self._levels):
            if self._levels[name] > 0.0:
                self._levels[name] = max(0.0, self._levels[name] - amount)
                if self._levels[name] > 0.0:
                    any_active = True
                self._send_dimension_cc(name)
        self._activation_level = max(self._levels.values()) if any_active else 0.0

    def deactivate(self) -> None:
        """Reset all dimensions to transparent."""
        for name in self._levels:
            self._levels[name] = 0.0
        self._activation_level = 0.0

    def _send_dimension_cc(self, dimension_name: str) -> None:
        """Send MIDI CC messages for a dimension at its current level."""
        dim = DIMENSIONS[dimension_name]
        level = self._levels[dimension_name]
        for mapping in dim.cc_mappings:
            value = cc_value_from_level(level, mapping.breakpoints)
            channel = self._evil_pet_ch if mapping.device == "evil_pet" else self._s4_ch
            self._midi.send_cc(channel=channel, cc=mapping.cc, value=value)
