"""Three-layer policy for the audio router (spec §6.2).

Layer 1 — safety clamps (fail-closed). Consent-critical, programme
ceilings, intelligibility budget, Mode D mutex, monetization gate,
hardware availability.

Layer 2 — context lookup. (stance, programme_role) → (tier, S-4 scenes).

Layer 3 — salience modulation. Impingement deltas compose via max
(not sum) — a single strong impingement dominates; mild impingements
do not stack into anthropomorphization risk.
"""

from __future__ import annotations

from agents.audio_router.state import (
    AudioRouterState,
    ImpingementDelta,
    RoutingIntent,
    Stance,
)

# Spec §6.2 Layer 2 — (stance, programme_role) → (tier, vocal_scene, music_scene).
# Music scene is "MUSIC-BED" default; overridden per programme below.
_STANCE_DEFAULTS: dict[Stance, tuple[int, str]] = {
    "NOMINAL": (2, "VOCAL-COMPANION"),
    "ENGAGED": (2, "VOCAL-COMPANION"),
    "SEEKING": (3, "VOCAL-MOSAIC"),  # D3 cross-character swap
    "ANT": (2, "VOCAL-COMPANION"),
    "FORTRESS": (0, "BYPASS"),
    "CONSTRAINED": (2, "VOCAL-COMPANION"),
}

# Programme overrides: (role → ceiling_tier, vocal_scene, music_scene)
_PROGRAMME_OVERRIDES: dict[str, tuple[int | None, str | None, str | None]] = {
    "livestream_director": (None, "VOCAL-COMPANION", "MUSIC-BED"),
    "memory_narrator": (3, "MEMORY-COMPANION", "MUSIC-BED"),
    "research_mode": (0, "RECORD-DRY", "MUSIC-BED"),  # dry capture
    "sonic_ritual": (5, "SONIC-RITUAL", "MUSIC-DRONE"),  # opt-in gated
    "live_performance": (0, "VOCAL-COMPANION", "BEAT-1"),  # TTS dry; beat + vinyl take FX space
}


# Evil Pet preset selection per tier.
_TIER_TO_PRESET: dict[int, str] = {
    0: "hapax-unadorned",
    1: "hapax-radio",
    2: "hapax-broadcast-ghost",
    3: "hapax-memory",
    4: "hapax-underwater",
    5: "hapax-granular-wash",
    6: "hapax-obliterated",
}


def apply_safety_clamps(intent: RoutingIntent, state: AudioRouterState) -> RoutingIntent:
    """Layer 1 — fail-closed clamps. Must run first.

    Clamps happen in priority order per spec §6.3 arbitration:
    1. consent-critical → T0 (absolute)
    2. Mode D mutex → re-route voice-tier-5+ to S-4 Mosaic
    3. monetization gate → clamp to highest opt-in-allowed tier
    4. intelligibility budget → clamp to T3 if budget exhausted
    5. programme ceiling → clamp to programme.voice_tier_ceiling
    6. hardware: Evil Pet MIDI unreachable → freeze preset
    7. hardware: S-4 USB absent → single-engine
    """
    # 1. Consent-critical (absolute)
    if state.broadcaster.consent_critical_utterance_pending:
        return RoutingIntent(
            topology="EP_LINEAR",
            tier=0,
            evilpet_preset="hapax-unadorned",
            s4_vocal_scene=None,
            s4_music_scene=None,
            clamp_reasons=["consent_critical"],
        )

    # 1b. FORTRESS stance emergency clean fallback (spec §6 UC7).
    # FORTRESS isn't in the numeric arbitration list but is an
    # operator-stressed stance that triggers bypass-all-FX. Treated as
    # a safety clamp — overrides programme targets, but not consent.
    if state.stimmung.stance == "FORTRESS":
        return RoutingIntent(
            topology="EP_LINEAR",
            tier=0,
            evilpet_preset="hapax-unadorned",
            s4_vocal_scene="BYPASS" if state.hardware.s4_usb_enumerated else None,
            s4_music_scene="BYPASS" if state.hardware.s4_usb_enumerated else None,
            clamp_reasons=["fortress_stance"],
        )

    # 2. Mode D mutex — voice-tier-5+ re-routes to S-4 Mosaic
    if intent.tier >= 5 and state.broadcaster.mode_d_active:
        intent = intent.reroute_voice_to_s4_mosaic("mode_d_mutex")

    # 3. Monetization gate
    if not intent.monetization_opt_in_ok(state.programme.monetization_opt_ins):
        # Clamp to the highest allowed tier (T4 if voice_tier_granular missing)
        intent = intent.clamp_tier(4, "monetization_gate")
        # Re-pick preset for the clamped tier
        intent = intent.model_copy(update={"evilpet_preset": _TIER_TO_PRESET[intent.tier]})

    # 4. Intelligibility budget
    if state.intelligibility.budget_exhausted_for(intent.tier):
        if not state.programme.intelligibility_gate_override:
            intent = intent.clamp_tier(3, "intelligibility_budget")
            intent = intent.model_copy(update={"evilpet_preset": _TIER_TO_PRESET[intent.tier]})

    # 5. Programme ceiling
    if state.programme.voice_tier_ceiling is not None:
        intent = intent.clamp_tier(state.programme.voice_tier_ceiling, "programme_ceiling")
        intent = intent.model_copy(update={"evilpet_preset": _TIER_TO_PRESET[intent.tier]})

    # 6. Hardware: Evil Pet MIDI unreachable
    if not state.hardware.evilpet_midi_reachable:
        intent = intent.freeze_evilpet("evilpet_midi_unreachable")

    # 7. Hardware: S-4 absent
    if not state.hardware.s4_usb_enumerated:
        intent = intent.downgrade_to_single_engine("s4_absent")

    return intent


def apply_context_lookup(state: AudioRouterState) -> RoutingIntent:
    """Layer 2 — stance + programme → tier + scenes.

    Returns a baseline RoutingIntent that Layer 1 will then clamp.
    Dual-engine topology D2 is the baseline (§5.9); D3 engages when
    SEEKING stance (§5.10).
    """
    # Stance default
    base_tier, vocal_scene = _STANCE_DEFAULTS[state.stimmung.stance]
    music_scene = "MUSIC-BED"

    # Programme override
    if state.programme.role and state.programme.role in _PROGRAMME_OVERRIDES:
        p_ceiling, p_vocal, p_music = _PROGRAMME_OVERRIDES[state.programme.role]
        if p_ceiling is not None:
            # Programme-overridden explicit tier target
            base_tier = min(base_tier, p_ceiling) if base_tier > 0 else p_ceiling
        if p_vocal is not None:
            vocal_scene = p_vocal
        if p_music is not None:
            music_scene = p_music

    # Explicit voice_tier_target wins
    if state.programme.voice_tier_target is not None:
        base_tier = state.programme.voice_tier_target

    # Topology selection
    # Operator/programme topology_override wins (UC1 dual-voice, UC5 serial mode, etc.)
    if state.programme.topology_override is not None:
        topology = state.programme.topology_override
    elif state.stimmung.stance == "SEEKING" and state.stimmung.exploration_deficit > 0.6:
        topology = "D3_SWAP"
    elif state.stimmung.stance == "FORTRESS":
        topology = "EP_LINEAR"
    else:
        topology = "D2_SPLIT"

    return RoutingIntent(
        topology=topology,
        tier=base_tier,
        evilpet_preset=_TIER_TO_PRESET[base_tier],
        s4_vocal_scene=vocal_scene,
        s4_music_scene=music_scene,
    )


def apply_salience_modulation(
    intent: RoutingIntent, impingements: list[ImpingementDelta]
) -> RoutingIntent:
    """Layer 3 — impingement deltas compose via max(abs(tier_shift)).

    Max-composition prevents multiple mild impingements from stacking
    into anthropomorphization risk (§7.2).
    """
    active = [i for i in impingements if i.active]
    if not active:
        return intent

    # Pick the delta with the largest absolute tier_shift.
    dominant = max(active, key=lambda d: abs(d.tier_shift))
    if dominant.tier_shift == 0:
        return intent

    new_tier = max(0, min(6, intent.tier + dominant.tier_shift))
    if new_tier == intent.tier:
        return intent

    return intent.model_copy(
        update={
            "tier": new_tier,
            "evilpet_preset": _TIER_TO_PRESET[new_tier],
        }
    )


def compute_ramp_seconds(stimmung_velocity: float) -> float:
    """Compute CC-interpolation ramp duration per spec §6.4.

    Ramp time scales inversely with stimmung velocity:
    - High velocity (>= 4.0 d(stance)/s) → 0.2 s (snappy transitions)
    - Default (~0.8) → 1.0 s (smooth)
    - Low velocity (< 0.32) → 2.5 s (cinematic drift)

    Formula: ``clamp(0.2, 2.5, 0.8 / max(velocity, 0.1))``

    The 0.1 lower bound on denominator prevents division by zero when
    stimmung is stationary. The upper clamp at 2.5 s prevents a
    runaway ramp — beyond 2.5 s the operator should use the CLI
    `hapax-voice-tier --sticky` to lock the tier explicitly.
    """
    velocity = max(stimmung_velocity, 0.1)
    raw = 0.8 / velocity
    return max(0.2, min(2.5, raw))


def arbitrate(state: AudioRouterState) -> RoutingIntent:
    """Full 3-layer arbitration — the router tick entry point.

    Order: context lookup → salience modulation → safety clamps.
    (Salience happens before clamps so the clamp layer has the final
    impingement-modulated tier to clamp against.)
    """
    intent = apply_context_lookup(state)
    intent = apply_salience_modulation(intent, state.impingements)
    intent = apply_safety_clamps(intent, state)
    return intent
