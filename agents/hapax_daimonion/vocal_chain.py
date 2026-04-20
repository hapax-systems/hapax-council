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


class _VocalChainMetrics:
    """Prometheus counters for vocal-chain CC activity. Fail-soft on registry errors."""

    def __init__(self) -> None:
        self._cc_sent: Any = None
        self._activation: Any = None
        try:
            from prometheus_client import REGISTRY, Counter
        except ImportError:
            return
        for name, doc, labels, attr in (
            (
                "hapax_vocal_chain_cc_sent_total",
                "MIDI CCs emitted by vocal chain per device and dimension",
                ["device", "dimension"],
                "_cc_sent",
            ),
            (
                "hapax_vocal_chain_activation_total",
                "Dimension activations by source family",
                ["dimension", "source"],
                "_activation",
            ),
        ):
            try:
                setattr(self, attr, Counter(name, doc, labels))
            except ValueError:
                setattr(self, attr, REGISTRY._names_to_collectors.get(name))  # noqa: SLF001

    def inc_cc(self, device: str, dimension: str) -> None:
        if self._cc_sent is None:
            return
        try:
            self._cc_sent.labels(device=device, dimension=dimension).inc()
        except Exception:
            log.debug("vocal_chain cc counter inc failed", exc_info=True)

    def inc_activation(self, dimension: str, source: str) -> None:
        if self._activation is None:
            return
        try:
            self._activation.labels(dimension=dimension, source=source).inc()
        except Exception:
            log.debug("vocal_chain activation counter inc failed", exc_info=True)


_metrics = _VocalChainMetrics()


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


def _ranged(cc_min: int, cc_max: int) -> list[tuple[float, int]]:
    """Linear curve clamped to a sub-range of CC values (level 0 → cc_min, level 1 → cc_max)."""
    return [(0.0, cc_min), (0.5, (cc_min + cc_max) // 2), (1.0, cc_max)]


def _centered(center: int, span: int) -> list[tuple[float, int]]:
    """Level 0.5 = center; 0.0 = center-span; 1.0 = center+span (clamped 0..127)."""
    lo = max(0, center - span)
    hi = min(127, center + span)
    return [(0.0, lo), (0.5, center), (1.0, hi)]


def _inverted(cc_high: int, cc_low: int) -> list[tuple[float, int]]:
    """Level 0 = cc_high, level 1 = cc_low. Used for damping (more level = less damp)."""
    return [(0.0, cc_high), (0.5, (cc_high + cc_low) // 2), (1.0, cc_low)]


# CC map derived from docs/research/2026-04-19-evil-pet-s4-base-config.md §5.1–§5.2.
# Research-approved ceilings keep speech intelligible and prevent anthropomorphic
# coloration (no granular re-synthesis, no LFO wobble, no extreme resonance).
# One CC per (device, dimension) — no within-device collisions between dimensions,
# so activating one dimension never writes over another's CC on the same device.
DIMENSIONS: dict[str, Dimension] = {
    "vocal_chain.intensity": Dimension(
        name="vocal_chain.intensity",
        description="Increases vocal energy and density. Speech becomes louder, more present, more forceful. Distinct from emotional valence — pure physical energy.",
        cc_mappings=[
            CCMapping("evil_pet", 39, _ranged(0, 80)),  # saturator amount
            CCMapping("s4", 95, _ranged(20, 60)),  # deform drive
        ],
    ),
    "vocal_chain.tension": Dimension(
        name="vocal_chain.tension",
        description="Constricts vocal timbre. Speech sounds strained, tight, forced through resistance. Harmonics sharpen, resonance builds. Distinct from volume.",
        cc_mappings=[
            CCMapping("evil_pet", 70, _ranged(40, 100)),  # filter frequency
            CCMapping("evil_pet", 71, _ranged(20, 60)),  # filter resonance
            CCMapping("s4", 79, _ranged(40, 80)),  # ring cutoff
            CCMapping("s4", 80, _ranged(15, 35)),  # ring resonance (conservative ceiling)
        ],
    ),
    "vocal_chain.diffusion": Dimension(
        name="vocal_chain.diffusion",
        description="Scatters vocal output across spatial field. Speech becomes ambient, sourceless, environmental. Words dissolve into texture at high levels.",
        cc_mappings=[
            CCMapping("evil_pet", 91, [(0.0, 20), (0.7, 45), (1.0, 60)]),  # reverb amount (log)
            CCMapping("s4", 115, _ranged(40, 90)),  # reverb size
        ],
    ),
    "vocal_chain.degradation": Dimension(
        name="vocal_chain.degradation",
        description="Corrupts vocal signal. Speech fractures into digital artifacts, broken transmission, static. System malfunction expressed through voice.",
        cc_mappings=[
            CCMapping(
                "evil_pet", 84, [(0.0, 0), (0.49, 0), (0.5, 90), (1.0, 110)]
            ),  # saturator type: stepped distortion→bit-crush
            CCMapping("s4", 96, _ranged(50, 90)),  # deform compress (heavier under degradation)
        ],
    ),
    "vocal_chain.depth": Dimension(
        name="vocal_chain.depth",
        description="Places voice in reverberant space. Distant, cathedral-like, submerged. Speech recedes from foreground without losing content at low levels.",
        cc_mappings=[
            CCMapping("evil_pet", 93, _ranged(20, 70)),  # reverb tail
            CCMapping("s4", 114, _ranged(20, 55)),  # reverb amount
        ],
    ),
    "vocal_chain.pitch_displacement": Dimension(
        name="vocal_chain.pitch_displacement",
        description="Shifts vocal pitch away from natural register. Higher, lower, or unstable. Uncanny displacement without volume or timbre change.",
        cc_mappings=[
            CCMapping("evil_pet", 44, _centered(64, 30)),  # pitch (centered)
            CCMapping("s4", 82, _centered(64, 24)),  # ring pitch (centered, conservative span)
        ],
    ),
    "vocal_chain.temporal_distortion": Dimension(
        name="vocal_chain.temporal_distortion",
        description="Stretches, freezes, or stutters speech in time. Words elongate, fragment, or loop. Temporal continuity breaks down.",
        cc_mappings=[
            CCMapping("evil_pet", 96, _ranged(20, 80)),  # env-filter mod (signal-honest motion)
            CCMapping("s4", 116, _ranged(20, 45)),  # delay feedback (clamped — prevents runaway)
        ],
    ),
    "vocal_chain.spectral_color": Dimension(
        name="vocal_chain.spectral_color",
        description="Shifts vocal brightness and metallicity. Dark, bright, hollow, metallic. Changes tonal character without changing pitch or volume.",
        cc_mappings=[
            CCMapping("evil_pet", 92, _centered(60, 20)),  # reverb tone (40..80)
            CCMapping("s4", 118, _inverted(80, 40)),  # reverb damp (inverted: brighter = less damp)
        ],
    ),
    "vocal_chain.coherence": Dimension(
        name="vocal_chain.coherence",
        description="Controls intelligibility of speech. Master axis from clear human voice to pure abstract texture. Affects overall processing depth.",
        cc_mappings=[
            CCMapping(
                "evil_pet", 40, _ranged(40, 70)
            ),  # master wet/dry mix (dryness floor keeps words clear)
            CCMapping("s4", 103, _ranged(40, 70)),  # deform wet
        ],
    ),
}

VOCAL_CHAIN_RECORDS = [
    CapabilityRecord(
        name=dim.name,
        description=dim.description,
        daemon="hapax_daimonion",
        operational=OperationalProperties(latency_class="fast", medium="auditory"),
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
        dims = impingement.content.get("dimensions", {}) or impingement.context.get(
            "dimensions", {}
        )
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
        _metrics.inc_activation(dimension_name, impingement.source.split(".", 1)[0] or "unknown")
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
            _metrics.inc_cc(mapping.device, dimension_name)
