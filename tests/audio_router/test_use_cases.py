"""UC1-UC10 narrative integration tests (Phase B6).

Each test assembles a narrative scenario from the spec §6 use-case
catalog and verifies the arbiter produces the expected routing intent.
Tests are hardware-independent; they exercise the policy layers only.
Full router tests (MIDI emit, /dev/shm watch) arrive when the tick
loop ships with B1/B2 hardware.
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
    arbitrate,
)


def _state(**kw: object) -> AudioRouterState:
    return AudioRouterState(
        stimmung=kw.get("stimmung", StimmungState()),  # type: ignore[arg-type]
        programme=kw.get("programme", ProgrammeState()),  # type: ignore[arg-type]
        broadcaster=kw.get("broadcaster", BroadcasterState()),  # type: ignore[arg-type]
        hardware=kw.get("hardware", HardwareState(s4_usb_enumerated=True)),  # type: ignore[arg-type]
        intelligibility=kw.get("intelligibility", IntelligibilityBudget()),  # type: ignore[arg-type]
        impingements=kw.get("impingements", []),  # type: ignore[arg-type]
    )


# ═══ UC1 — Dual voice character (operator-blended dual-engine TTS) ═══


def test_uc1_dual_voice_character_via_programme_override() -> None:
    """Operator gestures into UC1 via programme.topology_override=D1."""
    state = _state(
        programme=ProgrammeState(
            role="livestream_director",
            topology_override="D1_DUAL_VOICE",
        ),
    )
    intent = arbitrate(state)
    assert intent.topology == "D1_DUAL_VOICE"
    assert intent.evilpet_preset == "hapax-broadcast-ghost"
    assert intent.s4_vocal_scene == "VOCAL-COMPANION"


# ═══ UC2 — Default livestream (complementary split) ═══


def test_uc2_default_livestream_is_d2_split_t2() -> None:
    """The baseline: NOMINAL stance, no programme override, S-4 present.
    Voice→EP, music→S-4, simultaneous (§5.9 D2)."""
    state = _state()
    intent = arbitrate(state)
    assert intent.topology == "D2_SPLIT"
    assert intent.tier == 2
    assert intent.evilpet_preset == "hapax-broadcast-ghost"
    assert intent.s4_vocal_scene == "VOCAL-COMPANION"
    assert intent.s4_music_scene == "MUSIC-BED"
    assert intent.clamp_reasons == []


def test_uc2_s4_absent_degrades_to_ep_linear() -> None:
    """Hardware degradation: S-4 unplugged → EP_LINEAR without penalty."""
    state = _state(
        hardware=HardwareState(evilpet_midi_reachable=True, s4_usb_enumerated=False),
    )
    intent = arbitrate(state)
    assert intent.topology == "EP_LINEAR"
    assert intent.evilpet_preset == "hapax-broadcast-ghost"
    assert intent.s4_vocal_scene is None
    assert intent.s4_music_scene is None


# ═══ UC3 — SEEKING-stance exploration (cross-character swap) ═══


def test_uc3_seeking_stance_engages_d3_cross_character_swap() -> None:
    """SEEKING + exploration_deficit > 0.6 → voice routes to S-4 Mosaic,
    Evil Pet drops to tier-3 coloration role."""
    state = _state(stimmung=StimmungState(stance="SEEKING", exploration_deficit=0.8))
    intent = arbitrate(state)
    assert intent.topology == "D3_SWAP"
    assert intent.s4_vocal_scene == "VOCAL-MOSAIC"
    assert intent.tier == 3


def test_uc3_seeking_with_low_deficit_stays_d2() -> None:
    """SEEKING without exploration pressure stays on D2_SPLIT default."""
    state = _state(stimmung=StimmungState(stance="SEEKING", exploration_deficit=0.2))
    intent = arbitrate(state)
    assert intent.topology == "D2_SPLIT"


# ═══ UC4 — Operator duet (simultaneous operator + Hapax voice) ═══


def test_uc4_operator_duet_with_d1_topology_override() -> None:
    """Operator duet: TTS gets dual voice character (D1), operator voice
    on Rode runs in parallel on CH5. Policy-layer concern is only the
    TTS path (D1); operator voice is a separate physical channel."""
    state = _state(
        broadcaster=BroadcasterState(operator_voice_active=True),
        programme=ProgrammeState(topology_override="D1_DUAL_VOICE"),
    )
    intent = arbitrate(state)
    assert intent.topology == "D1_DUAL_VOICE"


# ═══ UC5 — Live performance (S-4 sequencer + vinyl Mode D + TTS dry) ═══


def test_uc5_live_performance_tts_is_t0_dry() -> None:
    """Programme live_performance forces TTS to T0 so beat + vinyl take
    the FX space; S-4 Track 2 runs BEAT-1 scene for sequenced percussion."""
    state = _state(
        stimmung=StimmungState(stance="ENGAGED"),
        programme=ProgrammeState(role="live_performance"),
    )
    intent = arbitrate(state)
    assert intent.tier == 0
    assert intent.evilpet_preset == "hapax-unadorned"
    assert intent.s4_music_scene == "BEAT-1"


def test_uc5_live_performance_mode_d_active_keeps_tts_dry() -> None:
    """Mode D claims Evil Pet granular for vinyl while TTS stays dry."""
    state = _state(
        stimmung=StimmungState(stance="ENGAGED"),
        programme=ProgrammeState(role="live_performance"),
        broadcaster=BroadcasterState(mode_d_active=True),
    )
    intent = arbitrate(state)
    assert intent.tier == 0
    # TTS at T0 is below Mode D mutex threshold; no re-route needed.
    assert "mode_d_mutex" not in intent.rerouted_reasons


# ═══ UC6 — Research capture (S-4 RECORD-DRY + Evil Pet character) ═══


def test_uc6_research_mode_drops_tts_to_t0_records_stems() -> None:
    """Programme research_mode → TTS dry + S-4 Track 1 records clean stems
    while Evil Pet applies broadcast character (preserved via separate
    physical path — not visible at policy layer)."""
    state = _state(
        programme=ProgrammeState(role="research_mode"),
    )
    intent = arbitrate(state)
    assert intent.tier == 0
    assert intent.s4_vocal_scene == "RECORD-DRY"


# ═══ UC7 — Emergency clean fallback (bypass all FX) ═══


def test_uc7_fortress_stance_bypasses_all_fx() -> None:
    """FORTRESS stance → EP_LINEAR + T0. Emergency governance fallback."""
    state = _state(stimmung=StimmungState(stance="FORTRESS"))
    intent = arbitrate(state)
    assert intent.topology == "EP_LINEAR"
    assert intent.tier == 0
    assert intent.evilpet_preset == "hapax-unadorned"


def test_uc7_fortress_overrides_even_with_programme_ritual() -> None:
    """FORTRESS stance (safety clamp §6 UC7) overrides programme ritual."""
    state = _state(
        stimmung=StimmungState(stance="FORTRESS"),
        programme=ProgrammeState(
            role="sonic_ritual",
            voice_tier_target=5,
            monetization_opt_ins=["voice_tier_granular", "dual_granular_simultaneous"],
        ),
    )
    intent = arbitrate(state)
    assert intent.tier == 0
    assert intent.evilpet_preset == "hapax-unadorned"
    assert "fortress_stance" in intent.clamp_reasons


# ═══ UC8 — Monitor-only preview (dry-run) ═══
# UC8 is a routing concern (preview sink ≠ broadcast sink), not a
# policy concern. Covered by Phase C4 dry-run sink implementation.
# No policy test needed at this phase.


# ═══ UC9 — Impingement-driven tier shift ═══


def test_uc9_memory_callback_impingement_shifts_tier_up() -> None:
    """Imagination fragment with high salience tagged memory_callback →
    tier shift toward T3. Director emits this during narrative passages."""
    state = _state(
        impingements=[
            ImpingementDelta(
                source="imagination.memory_callback",
                salience=0.84,
                tier_shift=1,
            ),
        ],
    )
    intent = arbitrate(state)
    # NOMINAL base tier = 2, +1 from impingement = 3
    assert intent.tier == 3
    assert intent.evilpet_preset == "hapax-memory"


def test_uc9_multiple_mild_impingements_do_not_stack() -> None:
    """MAX composition prevents mild events from stacking into T5+."""
    state = _state(
        impingements=[
            ImpingementDelta(source=f"mild_{i}", salience=0.3, tier_shift=1) for i in range(5)
        ],
    )
    intent = arbitrate(state)
    # Even five +1 impingements → only +1 shift (MAX, not SUM)
    assert intent.tier == 3


# ═══ UC10 — Programme-gated texture unlock (SONIC-RITUAL) ═══


def test_uc10_sonic_ritual_with_full_opt_ins_unlocks_t5_dual_granular() -> None:
    """Programme sonic_ritual + voice_tier_granular opt-in +
    dual_granular_simultaneous opt-in → T5 on Evil Pet + SONIC-RITUAL
    on S-4 (dual-granular, governance-gated)."""
    state = _state(
        programme=ProgrammeState(
            role="sonic_ritual",
            voice_tier_target=5,
            monetization_opt_ins=[
                "voice_tier_granular",
                "dual_granular_simultaneous",
            ],
        ),
    )
    intent = arbitrate(state)
    assert intent.tier == 5
    assert intent.evilpet_preset == "hapax-granular-wash"
    assert intent.s4_vocal_scene == "SONIC-RITUAL"
    assert intent.clamp_reasons == []


def test_uc10_sonic_ritual_without_opt_in_clamps_to_t4() -> None:
    """Missing voice_tier_granular opt-in → monetization gate clamps T5→T4."""
    state = _state(
        programme=ProgrammeState(
            role="sonic_ritual",
            voice_tier_target=5,
            monetization_opt_ins=[],
        ),
    )
    intent = arbitrate(state)
    assert intent.tier == 4
    assert "monetization_gate" in intent.clamp_reasons


def test_uc10_budget_exhausted_clamps_t5_to_t3() -> None:
    """Intelligibility budget exhausted → clamps T5→T3. Tested without
    the sonic_ritual programme so only the budget clamp fires (not
    dual_granular_simultaneous monetization gate)."""
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


# ═══ Arbitration precedence (cross-UC) ═══


def test_consent_critical_wins_over_everything() -> None:
    """Highest-priority clamp: consent_critical → T0 absolute, regardless
    of programme / stance / impingement."""
    state = _state(
        stimmung=StimmungState(stance="ENGAGED"),
        programme=ProgrammeState(
            role="sonic_ritual",
            voice_tier_target=6,
            monetization_opt_ins=["voice_tier_granular", "dual_granular_simultaneous"],
        ),
        broadcaster=BroadcasterState(consent_critical_utterance_pending=True),
        impingements=[
            ImpingementDelta(source="spike", salience=1.0, tier_shift=5),
        ],
    )
    intent = arbitrate(state)
    assert intent.tier == 0
    assert "consent_critical" in intent.clamp_reasons


def test_mode_d_reroute_preserves_voice_character_via_s4() -> None:
    """When Mode D holds Evil Pet granular, voice-T5+ re-routes to S-4
    Mosaic rather than silencing the character. Operator still hears
    granular on voice, just from a different engine."""
    state = _state(
        programme=ProgrammeState(
            voice_tier_target=5,
            monetization_opt_ins=["voice_tier_granular"],
        ),
        broadcaster=BroadcasterState(mode_d_active=True),
    )
    intent = arbitrate(state)
    # Evil Pet NOT on granular (that engine claimed by Mode D)
    assert intent.evilpet_preset != "hapax-granular-wash"
    # S-4 takes the granular role
    assert intent.s4_vocal_scene == "VOCAL-MOSAIC"
    assert "mode_d_mutex" in intent.rerouted_reasons
