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


def _query_camera_salience_for_voice(impingement: Impingement) -> dict[str, Any] | None:
    """Query the camera-salience broker for voice activation context.

    Mirrors the inline pattern used by ``director_loop`` and
    ``affordance_pipeline``. Fails closed (returns ``None``) on any
    broker error so vocal activation never blocks on a salience lookup.
    """
    try:
        from shared.camera_salience_singleton import broker as _camera_broker

        bundle = _camera_broker().query(
            consumer="voice",
            decision_context=f"vocal_chain_activate:{impingement.source}",
            candidate_action="modulate_vocal_dimensions",
        )
        if bundle is None:
            return None
        return bundle.to_wcs_projection_payload()
    except Exception:
        log.debug("camera salience voice query failed", exc_info=True)
        return None


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
        *,
        route_switcher: Any | None = None,
        fx_device_witness_provider: Any | None = None,
    ) -> None:
        self._midi = midi_output
        self._evil_pet_ch = evil_pet_channel
        self._s4_ch = s4_channel
        self._decay_rate = decay_rate
        self._levels: dict[str, float] = {name: 0.0 for name in DIMENSIONS}
        self._activation_level = 0.0
        # Dual-FX Phase 5: current PipeWire routing path, tracked so tier
        # transitions only invoke the pactl switcher when the path actually
        # changes (DRY → EVIL_PET, etc.). None = not-yet-initialised; the
        # first apply_tier() sets it.
        self._current_path: Any | None = None
        # Injectable for tests. Production callers leave this None and the
        # default shared.audio_route_switcher.apply_switch is used.
        self._route_switcher = route_switcher
        # Injectable for tests and future hardware witness producers. When
        # absent, the expression surface reads the repo-visible /dev/shm
        # witness and fails closed if it is missing or stale.
        self._fx_device_witness_provider = fx_device_witness_provider

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

        On every activation the broker is queried for camera salience under
        ``consumer="voice"``; the WCS projection (or ``None`` when unavailable)
        is attached to the returned payload as ``camera_salience`` so the
        caller can correlate the vocal modulation with which apertures were
        salient at activation time.
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
        salience = _query_camera_salience_for_voice(impingement)
        if not activated:
            score = self.can_resolve(impingement)
            if score > 0:
                self.activate(impingement, score)
                return {
                    "activated": True,
                    "level": score,
                    "dimensions": [],
                    "camera_salience": salience,
                }
        return {
            "activated": bool(activated),
            "level": self._activation_level,
            "dimensions": activated,
            "camera_salience": salience,
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

    def apply_tier(
        self,
        tier: Any,
        impingement: Impingement | None = None,
        *,
        path_override: Any | None = None,
        route_audio: bool = True,
    ) -> None:
        """Apply a VoiceTier profile — set 9 dim levels + emit extra CCs.

        Convenience wrapper over shared.voice_tier.apply_tier that closes
        over this chain's MidiOutput so the tier's non-9-dim CC overrides
        (granular engine engagement for T5/T6) flow through the same
        pipeline. Deactivates first so no stale dim levels from a prior
        tier bleed into the new one.

        Dual-FX Phase 5: before emitting CCs, resolves the target
        VoicePath for the tier (via ``agents.hapax_daimonion.voice_path
        .select_voice_path``) and switches the PipeWire default sink
        when the path has changed. Order: route-switch first so the
        Evil Pet / S-4 CCs land on the sink that's actually carrying
        the audio. Route switches only fire on path transitions; a
        same-path retier skips the pactl call entirely.

        Args:
            tier: a VoiceTier enum value (from shared.voice_tier).
            impingement: Optional Impingement for telemetry attribution.
                If None, a synthetic one is constructed with
                ``source="voice_tier"``.
            path_override: Operator override for tier→path selection.
                When set, bypasses ``select_voice_path`` and uses this
                value directly. Intended for the hapax-voice-tier CLI's
                ``--path`` flag.
            route_audio: When False, skip the pactl switch and just emit
                MIDI CCs. Used by tests and by paths where the caller
                has already acquired the route (e.g. mutex Phase 3).
        """
        from shared.voice_tier import apply_tier as _apply_tier_fn

        if impingement is None:
            import time as _time

            from shared.impingement import Impingement as _Imp
            from shared.impingement import ImpingementType as _ImpType

            impingement = _Imp(
                timestamp=_time.time(),
                source="voice_tier",
                type=_ImpType.STATISTICAL_DEVIATION,
                strength=1.0,
                content={"metric": f"tier_{int(tier)}"},
            )

        if route_audio and not self._maybe_switch_route(tier, path_override):
            return

        self.deactivate()
        _apply_tier_fn(tier, vocal_chain=self, midi_output=self._midi, impingement=impingement)

    def emit_voice_tier_impingement(
        self,
        tier: Any,
        *,
        programme_band: tuple[int, int] | None = None,
        excursion: bool = False,
        clamped_from: Any | None = None,
        strength: float = 1.0,
    ) -> Any:
        """Produce a ``VoiceTierImpingement``-wrapped ``Impingement`` for the director loop.

        Phase 3b cross-zone glue (alpha handoff §7.1). Returns an
        ``Impingement`` whose ``content`` is the typed payload so
        ``agents/studio_compositor/director_loop.py`` consumes via
        ``VoiceTierImpingement.try_from(imp)`` without needing a
        direct import of this module.

        Args:
            tier: ``VoiceTier`` the director picked for this tick.
            programme_band: Optional ``(low, high)`` structural band;
                defaults to the tier as its own band when the director
                has no active Programme override.
            excursion: True when this tier is a §4.2 excursion pick
                (outside the structural band). Signals the consumer
                that the transition should not be treated as the new
                steady state.
            clamped_from: Optional original tier requested by the
                director before IntelligibilityBudget clamped it down;
                None when no clamp fired.
            strength: Impingement activation strength (0..1).
        """
        from agents.hapax_daimonion.voice_path import (
            VoicePath as _LiveVoicePath,
        )
        from agents.hapax_daimonion.voice_path import (
            resolve_public_voice_path,
        )
        from shared.typed_impingements import VoiceTierImpingement
        from shared.voice_tier import (
            TIER_MONETIZATION_RISK,
        )
        from shared.voice_tier import (
            VoiceTier as _VoiceTier,
        )

        tier_enum = tier if isinstance(tier, _VoiceTier) else _VoiceTier(int(tier))
        band = programme_band if programme_band is not None else (int(tier_enum), int(tier_enum))
        # Map the tier's public route through the expression-surface gate;
        # fail closed to HELD on lookup or witness failure.
        try:
            path_enum = resolve_public_voice_path(
                tier_enum,
                device_witness_provider=self._fx_device_witness_provider,
            ).path
        except Exception:
            path_enum = _LiveVoicePath.HELD
        payload = VoiceTierImpingement(
            tier=tier_enum,
            programme_band=band,
            voice_path=path_enum.value,
            monetization_risk=TIER_MONETIZATION_RISK[tier_enum],
            excursion=excursion,
            clamped_from=clamped_from if clamped_from is None else _VoiceTier(int(clamped_from)),
        )
        return payload.to_impingement(strength=strength)

    def _maybe_switch_route(self, tier: Any, path_override: Any | None) -> bool:
        """Resolve the tier's VoicePath and switch PipeWire routing if it changed.

        No-ops silently when:
        - the tier's path matches ``self._current_path`` (saves pactl calls)
        - the path lookup raises (missing config, tier not in map)
        - the pactl call raises (subprocess failure tolerated so a
          broken audio graph doesn't block voice MIDI entirely)
        """
        try:
            from agents.hapax_daimonion.voice_path import VoicePath as _LiveVoicePath
            from agents.hapax_daimonion.voice_path import (
                load_paths,
                resolve_public_voice_path,
            )
        except Exception:
            return False
        try:
            if path_override is not None:
                path = path_override
            else:
                decision = resolve_public_voice_path(
                    tier,
                    device_witness_provider=self._fx_device_witness_provider,
                )
                if not decision.accepted:
                    self._current_path = _LiveVoicePath.HELD
                    log.info(
                        "vocal_chain public route held: %s",
                        decision.operator_visible_reason,
                    )
                    return False
                path = decision.path
        except Exception:
            log.debug("voice_path resolution failed", exc_info=True)
            return False
        if path == _LiveVoicePath.HELD:
            self._current_path = _LiveVoicePath.HELD
            return False
        if path == self._current_path:
            return True
        # Resolve the sink from the loaded path config.
        try:
            paths = load_paths()
            sink = paths[path].sink
        except Exception:
            log.debug("voice_path sink lookup failed", exc_info=True)
            return False
        switcher = self._route_switcher
        if switcher is None:
            try:
                from shared.audio_route_switcher import apply_switch as _apply_switch
            except Exception:
                return False
            switcher = _apply_switch
        try:
            switcher(sink)
        except Exception:
            log.warning("pactl route switch failed; continuing with MIDI", exc_info=True)
            return True
        self._current_path = path
        log.info("vocal_chain route switched to %s (sink=%s)", path, sink)
        return True

    def _send_dimension_cc(self, dimension_name: str) -> None:
        """Send MIDI CC messages for a dimension at its current level."""
        dim = DIMENSIONS[dimension_name]
        level = self._levels[dimension_name]
        for mapping in dim.cc_mappings:
            value = cc_value_from_level(level, mapping.breakpoints)
            channel = self._evil_pet_ch if mapping.device == "evil_pet" else self._s4_ch
            self._midi.send_cc(channel=channel, cc=mapping.cc, value=value)
            _metrics.inc_cc(mapping.device, dimension_name)
