"""Pydantic state models for the audio router (spec §6.1).

State is assembled from live /dev/shm surfaces (stimmung), programme
manager (in-memory), capability-health Prometheus gauges, and hardware
probes. The arbiter reads this snapshot and emits a RoutingIntent.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Stance = Literal["NOMINAL", "ENGAGED", "SEEKING", "ANT", "FORTRESS", "CONSTRAINED"]

VOICE_TIER_MIN = 0
VOICE_TIER_MAX = 6


class StimmungState(BaseModel):
    """Snapshot from /dev/shm/hapax-stimmung/state.json (VLA writer)."""

    stance: Stance = "NOMINAL"
    energy: float = Field(default=0.5, ge=0.0, le=1.0)
    coherence: float = Field(default=0.5, ge=0.0, le=1.0)
    focus: float = Field(default=0.5, ge=0.0, le=1.0)
    intention_clarity: float = Field(default=0.5, ge=0.0, le=1.0)
    presence: float = Field(default=0.5, ge=0.0, le=1.0)
    exploration_deficit: float = Field(default=0.0, ge=0.0, le=1.0)
    timestamp: float = 0.0


class ProgrammeState(BaseModel):
    """ProgrammeManager snapshot (in-memory; router pulls directly)."""

    role: str | None = None
    monetization_opt_ins: list[str] = Field(default_factory=list)
    voice_tier_target: int | None = None
    voice_tier_ceiling: int | None = None
    intelligibility_gate_override: bool = False
    abort_predicates: list[str] = Field(default_factory=list)
    # Operator/programme-level topology override per spec §6.8 escape
    # hatches. When set, context_lookup returns this topology instead
    # of the stance-derived default. UC1 (dual voice character) engages
    # via this; UC5 serial mode toggles via ``D5_SERIAL_FALLBACK_PARALLEL``.
    topology_override: str | None = None


class BroadcasterState(BaseModel):
    """Ephemeral broadcast state (Rode VAD, Mode D flag, sampler, SFX)."""

    operator_voice_active: bool = False
    mode_d_active: bool = False
    sampler_active: bool = False
    sfx_emitting: bool = False
    consent_critical_utterance_pending: bool = False


class HardwareState(BaseModel):
    """Hardware availability (probed from PipeWire / MIDI enumeration)."""

    evilpet_midi_reachable: bool = True
    s4_usb_enumerated: bool = False
    l12_monitor_a_integrity: bool = True


class IntelligibilityBudget(BaseModel):
    """Rolling 5-min budget for inaudible-speech tiers (spec §9.4)."""

    t5_remaining_s: float = Field(default=120.0, ge=0.0)
    t6_remaining_s: float = Field(default=15.0, ge=0.0)
    dual_granular_remaining_s: float = Field(default=60.0, ge=0.0)  # §9.6
    window_start: float = 0.0

    def budget_exhausted_for(self, tier: int) -> bool:
        if tier >= 6:
            return self.t6_remaining_s <= 0.0
        if tier >= 5:
            return self.t5_remaining_s <= 0.0
        return False


class ImpingementDelta(BaseModel):
    """One impingement's contribution to the router decision.

    ``tier_shift`` is the signed adjustment to the target tier
    (negative = toward T0, positive = toward T6). ``source`` is a
    human-readable reason for the shift (included in Langfuse event).
    """

    source: str
    salience: float = Field(ge=0.0, le=1.0)
    tier_shift: int
    duration_s: float = Field(default=0.0, ge=0.0)
    active: bool = True


class AudioRouterState(BaseModel):
    """Full state snapshot the arbiter reads at each tick."""

    stimmung: StimmungState = Field(default_factory=StimmungState)
    programme: ProgrammeState = Field(default_factory=ProgrammeState)
    broadcaster: BroadcasterState = Field(default_factory=BroadcasterState)
    hardware: HardwareState = Field(default_factory=HardwareState)
    intelligibility: IntelligibilityBudget = Field(default_factory=IntelligibilityBudget)
    impingements: list[ImpingementDelta] = Field(default_factory=list)
    capability_health: dict[str, float] = Field(default_factory=dict)


class RoutingIntent(BaseModel):
    """The arbiter's output per tick.

    Consumed by dynamic_router.py's MIDI + gain emission layers.
    """

    topology: Literal[
        # Single-engine classes (preserved from prior design)
        "EP_LINEAR",  # §5.1 Evil Pet single-engine
        "S4_LINEAR",  # §5.2 S-4 single-engine
        "SERIAL_EP_S4",  # §5.3
        "PARALLEL_DRY_EP",  # §5.4
        "PARALLEL_EP_S4",  # §5.5
        "MIDI_COUPLED",  # §5.6
        "HYBRID_SAMPLER",  # §5.7
        # Dual-engine classes (new in spec §5.8-§5.12)
        "D1_DUAL_VOICE",  # §5.8 dual-parallel voice
        "D2_SPLIT",  # §5.9 complementary split (default baseline)
        "D3_SWAP",  # §5.10 cross-character swap
        "D4_MIDI_COUPLED_DUAL",  # §5.11
        "D5_SERIAL_FALLBACK_PARALLEL",  # §5.12
    ] = "D2_SPLIT"
    tier: int = Field(default=2, ge=VOICE_TIER_MIN, le=VOICE_TIER_MAX)
    evilpet_preset: str = "hapax-broadcast-ghost"
    s4_vocal_scene: str | None = "VOCAL-COMPANION"
    s4_music_scene: str | None = "MUSIC-BED"
    evilpet_gain: float = Field(default=1.0, ge=0.0, le=2.0)
    s4_vocal_gain: float = Field(default=1.0, ge=0.0, le=2.0)
    clamp_reasons: list[str] = Field(default_factory=list)
    rerouted_reasons: list[str] = Field(default_factory=list)

    def clamp_tier(self, max_tier: int, reason: str) -> RoutingIntent:
        """Return a copy clamped to ``max_tier`` with ``reason`` logged."""
        if self.tier <= max_tier:
            return self
        return self.model_copy(
            update={
                "tier": max_tier,
                "clamp_reasons": [*self.clamp_reasons, reason],
            }
        )

    def reroute_voice_to_s4_mosaic(self, reason: str) -> RoutingIntent:
        """Route voice-tier-5+ through S-4 Mosaic when Evil Pet granular
        is occupied by Mode D (spec §7.5 R3)."""
        return self.model_copy(
            update={
                # Voice does NOT go through Evil Pet granular (Mode D has it)
                "evilpet_preset": "hapax-broadcast-ghost",  # fall back to non-granular
                # S-4 Mosaic claims the granular role for voice
                "s4_vocal_scene": "VOCAL-MOSAIC",
                "rerouted_reasons": [*self.rerouted_reasons, reason],
            }
        )

    def freeze_evilpet(self, reason: str) -> RoutingIntent:
        """Evil Pet MIDI unreachable — hold last-known preset."""
        return self.model_copy(
            update={
                "clamp_reasons": [*self.clamp_reasons, reason],
            }
        )

    def downgrade_to_single_engine(self, reason: str) -> RoutingIntent:
        """S-4 absent — fall back to Evil Pet linear (§5.1)."""
        return self.model_copy(
            update={
                "topology": "EP_LINEAR",
                "s4_vocal_scene": None,
                "s4_music_scene": None,
                "clamp_reasons": [*self.clamp_reasons, reason],
            }
        )

    def monetization_opt_in_ok(self, opt_ins: list[str]) -> bool:
        """T5+ requires voice_tier_granular; dual-granular requires
        dual_granular_simultaneous."""
        if self.tier >= 5 and "voice_tier_granular" not in opt_ins:
            return False
        return not (
            self.tier >= 5
            and self.s4_vocal_scene == "SONIC-RITUAL"
            and "dual_granular_simultaneous" not in opt_ins
        )
