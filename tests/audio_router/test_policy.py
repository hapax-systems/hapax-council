"""Audio-router 3-layer policy tests (Phase B3).

Pins the spec §6.2 policy:
  Layer 1 (safety clamps) — fail-closed, highest priority
  Layer 2 (context lookup) — stance + programme → tier + scenes
  Layer 3 (salience modulation) — impingement deltas, max composition

Hardware-independent — runs pure Python, no MIDI, no /dev/shm.
"""

from __future__ import annotations

from agents.audio_router import (
    AudioRouterState,
    BroadcasterState,
    HardwareState,
    ImpingementDelta,
    IntelligibilityBudget,
    ProgrammeState,
    StimmungState,
    apply_context_lookup,
    apply_salience_modulation,
    arbitrate,
)


def _state(**kw: object) -> AudioRouterState:
    """Helper to build router state with sensible defaults."""
    return AudioRouterState(
        stimmung=kw.get("stimmung", StimmungState()),  # type: ignore[arg-type]
        programme=kw.get("programme", ProgrammeState()),  # type: ignore[arg-type]
        broadcaster=kw.get("broadcaster", BroadcasterState()),  # type: ignore[arg-type]
        hardware=kw.get("hardware", HardwareState(s4_usb_enumerated=True)),  # type: ignore[arg-type]
        intelligibility=kw.get("intelligibility", IntelligibilityBudget()),  # type: ignore[arg-type]
        impingements=kw.get("impingements", []),  # type: ignore[arg-type]
    )


# ═══ Layer 1 — safety clamps ═══


def test_consent_critical_forces_t0_absolute() -> None:
    state = _state(
        broadcaster=BroadcasterState(consent_critical_utterance_pending=True),
        stimmung=StimmungState(stance="ENGAGED"),
    )
    intent = arbitrate(state)
    assert intent.tier == 0
    assert intent.evilpet_preset == "hapax-unadorned"
    assert "consent_critical" in intent.clamp_reasons


def test_mode_d_active_reroutes_voice_t5_to_s4_mosaic() -> None:
    state = _state(
        stimmung=StimmungState(stance="NOMINAL"),
        programme=ProgrammeState(
            voice_tier_target=5,
            monetization_opt_ins=["voice_tier_granular"],
        ),
        broadcaster=BroadcasterState(mode_d_active=True),
    )
    intent = arbitrate(state)
    # Voice does NOT run Evil Pet granular (Mode D has it)
    assert intent.evilpet_preset != "hapax-granular-wash"
    # Voice IS re-routed to S-4 Mosaic
    assert intent.s4_vocal_scene == "VOCAL-MOSAIC"
    assert "mode_d_mutex" in intent.rerouted_reasons


def test_monetization_gate_clamps_t5_without_opt_in() -> None:
    state = _state(
        programme=ProgrammeState(voice_tier_target=5, monetization_opt_ins=[]),
    )
    intent = arbitrate(state)
    assert intent.tier <= 4
    assert "monetization_gate" in intent.clamp_reasons


def test_monetization_gate_allows_t5_with_opt_in() -> None:
    state = _state(
        programme=ProgrammeState(
            voice_tier_target=5,
            monetization_opt_ins=["voice_tier_granular"],
        ),
    )
    intent = arbitrate(state)
    assert intent.tier == 5
    assert "monetization_gate" not in intent.clamp_reasons


def test_intelligibility_budget_clamps_t5_to_t3() -> None:
    state = _state(
        programme=ProgrammeState(
            voice_tier_target=5,
            monetization_opt_ins=["voice_tier_granular"],
        ),
        intelligibility=IntelligibilityBudget(t5_remaining_s=0.0),
    )
    intent = arbitrate(state)
    assert intent.tier == 3
    assert "intelligibility_budget" in intent.clamp_reasons


def test_intelligibility_override_allows_t5_with_budget_exhausted() -> None:
    state = _state(
        programme=ProgrammeState(
            voice_tier_target=5,
            monetization_opt_ins=["voice_tier_granular"],
            intelligibility_gate_override=True,
        ),
        intelligibility=IntelligibilityBudget(t5_remaining_s=0.0),
    )
    intent = arbitrate(state)
    assert intent.tier == 5


def test_programme_ceiling_clamps_tier() -> None:
    state = _state(
        programme=ProgrammeState(voice_tier_target=5, voice_tier_ceiling=2),
        stimmung=StimmungState(stance="ENGAGED"),
    )
    intent = arbitrate(state)
    assert intent.tier <= 2
    assert "programme_ceiling" in intent.clamp_reasons


def test_s4_absent_downgrades_to_single_engine() -> None:
    state = _state(
        hardware=HardwareState(evilpet_midi_reachable=True, s4_usb_enumerated=False),
    )
    intent = arbitrate(state)
    assert intent.topology == "EP_LINEAR"
    assert intent.s4_vocal_scene is None
    assert intent.s4_music_scene is None
    assert "s4_absent" in intent.clamp_reasons


def test_evilpet_midi_unreachable_freezes_preset() -> None:
    state = _state(
        hardware=HardwareState(evilpet_midi_reachable=False, s4_usb_enumerated=True),
    )
    intent = arbitrate(state)
    assert "evilpet_midi_unreachable" in intent.clamp_reasons


# ═══ Layer 2 — context lookup ═══


def test_nominal_stance_defaults_to_t2_d2_split() -> None:
    state = _state(stimmung=StimmungState(stance="NOMINAL"))
    intent = apply_context_lookup(state)
    assert intent.topology == "D2_SPLIT"
    assert intent.tier == 2
    assert intent.evilpet_preset == "hapax-broadcast-ghost"
    assert intent.s4_vocal_scene == "VOCAL-COMPANION"


def test_fortress_stance_forces_bypass_ep_linear() -> None:
    state = _state(stimmung=StimmungState(stance="FORTRESS"))
    intent = apply_context_lookup(state)
    assert intent.topology == "EP_LINEAR"
    assert intent.tier == 0
    assert intent.evilpet_preset == "hapax-unadorned"


def test_seeking_with_high_deficit_engages_d3_swap() -> None:
    state = _state(stimmung=StimmungState(stance="SEEKING", exploration_deficit=0.8))
    intent = apply_context_lookup(state)
    assert intent.topology == "D3_SWAP"
    assert intent.s4_vocal_scene == "VOCAL-MOSAIC"


def test_programme_memory_narrator_overrides_scene() -> None:
    state = _state(
        stimmung=StimmungState(stance="NOMINAL"),
        programme=ProgrammeState(role="memory_narrator"),
    )
    intent = apply_context_lookup(state)
    assert intent.s4_vocal_scene == "MEMORY-COMPANION"


def test_programme_live_performance_uses_beat_1_music() -> None:
    state = _state(
        stimmung=StimmungState(stance="ENGAGED"),
        programme=ProgrammeState(role="live_performance"),
    )
    intent = apply_context_lookup(state)
    assert intent.s4_music_scene == "BEAT-1"


# ═══ Layer 3 — salience modulation ═══


def test_no_impingements_is_identity() -> None:
    base = apply_context_lookup(_state())
    result = apply_salience_modulation(base, [])
    assert result.tier == base.tier
    assert result.evilpet_preset == base.evilpet_preset


def test_single_impingement_shifts_tier() -> None:
    base = apply_context_lookup(_state())
    imp = ImpingementDelta(
        source="imagination.memory_callback",
        salience=0.8,
        tier_shift=1,
    )
    result = apply_salience_modulation(base, [imp])
    assert result.tier == base.tier + 1
    assert result.evilpet_preset != base.evilpet_preset


def test_multiple_impingements_compose_via_max_not_sum() -> None:
    """Two +1 impingements must NOT stack to +2."""
    base = apply_context_lookup(_state())
    imps = [
        ImpingementDelta(source="a", salience=0.5, tier_shift=1),
        ImpingementDelta(source="b", salience=0.5, tier_shift=1),
    ]
    result = apply_salience_modulation(base, imps)
    assert result.tier == base.tier + 1, "deltas must compose via max, not sum"


def test_stronger_impingement_dominates() -> None:
    """Mild +1 and strong +3 → result is +3 (not sum, not mild)."""
    base = apply_context_lookup(_state())
    imps = [
        ImpingementDelta(source="mild", salience=0.2, tier_shift=1),
        ImpingementDelta(source="strong", salience=0.9, tier_shift=3),
    ]
    result = apply_salience_modulation(base, imps)
    assert result.tier == base.tier + 3


def test_inactive_impingements_are_ignored() -> None:
    base = apply_context_lookup(_state())
    imps = [
        ImpingementDelta(source="stale", salience=0.9, tier_shift=3, active=False),
    ]
    result = apply_salience_modulation(base, imps)
    assert result.tier == base.tier


def test_salience_clamps_tier_to_0_6_range() -> None:
    base = apply_context_lookup(_state())
    imps = [ImpingementDelta(source="extreme", salience=1.0, tier_shift=99)]
    result = apply_salience_modulation(base, imps)
    assert 0 <= result.tier <= 6


# ═══ Integration: full arbitrate ═══


def test_default_nominal_state_yields_d2_split_t2() -> None:
    """The most common path: NOMINAL stance, no programme, no impingements,
    S-4 plugged in. Expected: D2 split with T2 + VOCAL-COMPANION + MUSIC-BED."""
    state = _state()
    intent = arbitrate(state)
    assert intent.topology == "D2_SPLIT"
    assert intent.tier == 2
    assert intent.evilpet_preset == "hapax-broadcast-ghost"
    assert intent.s4_vocal_scene == "VOCAL-COMPANION"
    assert intent.s4_music_scene == "MUSIC-BED"
    assert intent.clamp_reasons == []


def test_safety_clamps_win_over_context() -> None:
    """Consent-critical overrides programme + stance."""
    state = _state(
        stimmung=StimmungState(stance="ENGAGED"),
        programme=ProgrammeState(role="sonic_ritual", voice_tier_target=5),
        broadcaster=BroadcasterState(consent_critical_utterance_pending=True),
    )
    intent = arbitrate(state)
    assert intent.tier == 0
