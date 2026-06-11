"""Scripted rapid-alternation pumping receipt for the duck handoff.

cc-task voice-p2-duck-handoff-20260610 (CASE-VOICE-FOUNDATION-20260610).
Interview-bar criterion (v2 execution spec §0.2): "Duck handoff — no
pumping under rapid turn alternation — dB-domain compose, hysteresis,
pre-wet sidechain, fail-open-to-unity (rebuild design §ducking)."

Three layers under test:

1. ``compose_duck_target_db`` — the dB-domain composition (the pinned
   Phase 1 call-site swap of ``shared/audio_duck_compose``): genuinely
   concurrent (hot) sources SUM in dB, clamped at MAX_TOTAL_ATTEN_DB; a
   source latched only by hysteresis/hold-open (a handoff tail or a
   syllable gap, instantaneously below the release threshold) sustains
   its OWN depth without stacking onto the next speaker. Without that
   distinction, naive dB-summing dips the bed ~12 dB at every handoff
   (the tail's depth + the fresh speaker's depth) — the downward
   pumping mode.

2. ``HandoffHold`` — duck-layer release hysteresis: deepening is always
   immediate (speech-onset protection), but when the composed target
   rises toward unity the deeper value holds for DUCK_HANDOFF_HOLD_MS,
   so inter-turn gaps never release the bed toward unity — the upward
   pumping mode. Fail-open resets the hold: a blocker must force unity
   instantly, never wait out a hold window.

3. The scripted rapid-alternation receipt: real ``EnvelopeState`` VAD
   (hysteresis + hold-open) + composer + hold + ``ramp_gain`` run over
   a deterministic operator↔TTS turn script at the daemon's 20 ms tick.
   No pumping = the bed stays inside the engaged depth band for the
   whole conversation and recovers to unity only after it ends.

The bench A/B listen rides the next operator session; this receipt is
the headless gate.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agents.audio_ducker.__main__ import (
    TRIGGER_OFF_DBFS,
    TRIGGER_ON_DBFS,
    UNITY,
    EnvelopeState,
    compute_targets,
    lin_to_db,
    ramp_gain,
)
from agents.audio_ducker.handoff import (
    DuckTrigger,
    HandoffHold,
    compose_duck_target_db,
    music_duck_triggers,
)
from shared.audio_duck_compose import MAX_TOTAL_ATTEN_DB, amplitude_from_db
from shared.audio_loudness import (
    DUCK_DEPTH_OPERATOR_VOICE_DB,
    DUCK_DEPTH_TOLERANCE_DB,
    DUCK_DEPTH_TTS_DB,
    DUCK_HANDOFF_HOLD_MS,
)
from tests.agents.audio_ducker.test_fsm_transitions import _samples_at_dbfs

SPEECH_DBFS = TRIGGER_ON_DBFS + 10.0  # comfortably above the ON threshold
SILENCE_DBFS = TRIGGER_OFF_DBFS - 25.0  # comfortably below the OFF threshold


def _rode(active: bool, hot: bool) -> DuckTrigger:
    return DuckTrigger(name="rode", depth_db=DUCK_DEPTH_OPERATOR_VOICE_DB, active=active, hot=hot)


def _tts(active: bool, hot: bool) -> DuckTrigger:
    return DuckTrigger(name="tts", depth_db=DUCK_DEPTH_TTS_DB, active=active, hot=hot)


# ── dB-domain composition ────────────────────────────────────────────


class TestComposeDuckTargetDb:
    def test_two_hot_sources_sum_in_db(self) -> None:
        """Genuine double-talk composes -12 + -8 = -20 dB (sum, not min)."""
        composed = compose_duck_target_db([_rode(True, True), _tts(True, True)])
        assert composed == pytest.approx(DUCK_DEPTH_OPERATOR_VOICE_DB + DUCK_DEPTH_TTS_DB)

    def test_sum_clamps_at_max_total_attenuation(self) -> None:
        triggers = [_rode(True, True), _tts(True, True), _tts(True, True)]
        assert compose_duck_target_db(triggers) == MAX_TOTAL_ATTEN_DB

    def test_latched_tail_does_not_stack_onto_fresh_speaker(self) -> None:
        """Handoff tail: rode latched by hold-open (not hot) while TTS is
        hot must NOT sum to -20 — the bed sustains the deeper single
        depth. This is the phantom-overlap dip guard."""
        composed = compose_duck_target_db([_rode(True, False), _tts(True, True)])
        assert composed == DUCK_DEPTH_OPERATOR_VOICE_DB

    def test_latched_only_source_sustains_own_depth(self) -> None:
        """Syllable gap: active-but-not-hot alone holds its own depth."""
        composed = compose_duck_target_db([_rode(True, False), _tts(False, False)])
        assert composed == DUCK_DEPTH_OPERATOR_VOICE_DB

    def test_no_active_sources_is_unity(self) -> None:
        composed = compose_duck_target_db([_rode(False, False), _tts(False, False)])
        assert composed == 0.0

    def test_hot_without_active_is_ignored(self) -> None:
        """A source above the OFF threshold that never crossed ON is not
        activated — hysteresis decides activation, hotness only decides
        stacking."""
        composed = compose_duck_target_db([_rode(False, True)])
        assert composed == 0.0


class TestComputeTargetsDbCompose:
    """The ratified call-site swap: compute_targets composes in dB."""

    def test_both_active_composes_sum_not_min(self) -> None:
        music, _tts_gain = compute_targets(rode_active=True, tts_active=True)
        assert music == pytest.approx(
            amplitude_from_db(DUCK_DEPTH_OPERATOR_VOICE_DB + DUCK_DEPTH_TTS_DB)
        )

    def test_rode_plus_segment_composes(self) -> None:
        music, _tts_gain = compute_targets(rode_active=True, tts_active=False, segment_active=True)
        assert music == pytest.approx(
            amplitude_from_db(DUCK_DEPTH_OPERATOR_VOICE_DB + DUCK_DEPTH_TTS_DB)
        )

    def test_fortress_combined_still_uses_operator_only(self) -> None:
        music, _tts_gain = compute_targets(
            rode_active=True, tts_active=True, allow_tts_into_broadcast=False
        )
        assert music == pytest.approx(amplitude_from_db(DUCK_DEPTH_OPERATOR_VOICE_DB))


# ── Handoff hold (duck-layer release hysteresis) ─────────────────────


class TestHandoffHold:
    def test_deepening_is_immediate(self) -> None:
        hold = HandoffHold()
        assert hold.apply(-8.0, now_ms=0.0) == -8.0
        assert hold.apply(-20.0, now_ms=20.0) == -20.0

    def test_release_within_hold_window_holds_depth(self) -> None:
        hold = HandoffHold()
        hold.apply(-12.0, now_ms=0.0)
        held = hold.apply(0.0, now_ms=DUCK_HANDOFF_HOLD_MS - 1.0)
        assert held == -12.0
        assert hold.is_holding is True

    def test_release_after_hold_window_follows_composed(self) -> None:
        hold = HandoffHold()
        hold.apply(-12.0, now_ms=0.0)
        released = hold.apply(0.0, now_ms=DUCK_HANDOFF_HOLD_MS + 1.0)
        assert released == 0.0
        assert hold.is_holding is False

    def test_shallower_depth_is_held_then_followed(self) -> None:
        """Handoff -12 → -8: the deeper value holds for the window, then
        the shallower target is followed (never an excursion to unity)."""
        hold = HandoffHold()
        hold.apply(-12.0, now_ms=0.0)
        assert hold.apply(-8.0, now_ms=100.0) == -12.0
        assert hold.apply(-8.0, now_ms=DUCK_HANDOFF_HOLD_MS + 1.0) == -8.0

    def test_redeepening_during_hold_attacks_immediately(self) -> None:
        hold = HandoffHold()
        hold.apply(-8.0, now_ms=0.0)
        hold.apply(0.0, now_ms=100.0)  # release begins, held at -8
        assert hold.apply(-12.0, now_ms=150.0) == -12.0

    def test_hold_window_counts_from_last_moment_at_depth(self) -> None:
        """Sustained speech keeps refreshing the window: the hold expires
        DUCK_HANDOFF_HOLD_MS after the LAST at-depth tick, not the first."""
        hold = HandoffHold()
        hold.apply(-12.0, now_ms=0.0)
        hold.apply(-12.0, now_ms=500.0)  # still speaking
        held = hold.apply(0.0, now_ms=500.0 + DUCK_HANDOFF_HOLD_MS - 1.0)
        assert held == -12.0

    def test_reset_clears_hold_for_fail_open(self) -> None:
        """Fail-open must force unity instantly — a blocker can never
        wait out a hold window."""
        hold = HandoffHold()
        hold.apply(-12.0, now_ms=0.0)
        hold.reset()
        assert hold.apply(0.0, now_ms=20.0) == 0.0
        assert hold.is_holding is False


# ── Scripted rapid-alternation pumping receipt ───────────────────────

TICK_MS = 20.0


@dataclass
class _TraceSample:
    t_ms: float
    gain_db: float
    in_conversation: bool


def _run_alternation_script(
    turns: list[tuple[str, float, float]],
    tail_ms: float,
) -> list[_TraceSample]:
    """Run the real VAD → compose → hold → ramp chain over a turn script.

    ``turns`` is a list of (speaker, speech_ms, gap_ms) entries; speaker is
    "operator" or "tts". The glue mirrors the daemon main loop exactly:
    per 20 ms tick, feed each EnvelopeState a synthesized RMS frame, build
    the trigger set, compose in dB, apply the handoff hold, ramp the bed
    gain. Returns the gain trace in dB.
    """
    rode = EnvelopeState(name="rode")
    tts = EnvelopeState(name="tts")
    hold = HandoffHold()
    gain = UNITY
    trace: list[_TraceSample] = []

    schedule: list[tuple[float, float]] = []  # (rode_dbfs, tts_dbfs) per tick
    for speaker, speech_ms, gap_ms in turns:
        for _ in range(int(speech_ms / TICK_MS)):
            rode_dbfs = SPEECH_DBFS if speaker == "operator" else SILENCE_DBFS
            tts_dbfs = SPEECH_DBFS if speaker == "tts" else SILENCE_DBFS
            schedule.append((rode_dbfs, tts_dbfs))
        schedule.extend([(SILENCE_DBFS, SILENCE_DBFS)] * int(gap_ms / TICK_MS))
    conversation_ticks = len(schedule)
    schedule.extend([(SILENCE_DBFS, SILENCE_DBFS)] * int(tail_ms / TICK_MS))

    now_ms = 0.0
    for tick_idx, (rode_dbfs, tts_dbfs) in enumerate(schedule):
        now_ms += TICK_MS
        rode.update(_samples_at_dbfs(rode_dbfs), now_ms=now_ms)
        tts.update(_samples_at_dbfs(tts_dbfs), now_ms=now_ms)
        triggers = music_duck_triggers(
            rode.is_active,
            rode.is_hot,
            tts.is_active,
            tts.is_hot,
            segment_active=False,
            allow_tts_into_broadcast=True,
        )
        target_db = hold.apply(compose_duck_target_db(triggers), now_ms=now_ms)
        gain = ramp_gain(gain, amplitude_from_db(target_db), dt_ms=TICK_MS)
        trace.append(
            _TraceSample(
                t_ms=now_ms,
                gain_db=lin_to_db(gain),
                in_conversation=tick_idx < conversation_ticks,
            )
        )
    return trace


# Rapid alternation per the interview bar: short turns, inter-turn gaps
# both above and below the VAD hold-open window, three full
# operator↔TTS cycles. Gaps of 300 ms exceed HOLD_OPEN_MS (200 ms) so
# the VAD genuinely releases mid-gap — the handoff hold must carry the
# bed. Gaps of 160 ms exercise the latched-tail (phantom overlap) path.
RAPID_ALTERNATION = [
    ("operator", 400.0, 300.0),
    ("tts", 400.0, 160.0),
    ("operator", 300.0, 300.0),
    ("tts", 300.0, 160.0),
    ("operator", 400.0, 300.0),
    ("tts", 400.0, 0.0),
]
SETTLE_MS = 100.0  # initial attack transient excluded from the band check
TAIL_MS = 2_000.0


class TestRapidAlternationPumpingReceipt:
    def test_no_pumping_under_rapid_turn_alternation(self) -> None:
        """THE receipt: across the whole conversation the bed gain stays
        inside the engaged depth band — it never recovers toward unity in
        a gap (upward pump) and never dips below the deepest single depth
        plus tolerance (downward pump / phantom-overlap dip)."""
        trace = _run_alternation_script(RAPID_ALTERNATION, tail_ms=TAIL_MS)
        span = [s for s in trace if s.in_conversation and s.t_ms >= SETTLE_MS]
        assert span, "script produced no conversation span"

        ceiling_db = DUCK_DEPTH_TTS_DB + DUCK_DEPTH_TOLERANCE_DB
        floor_db = DUCK_DEPTH_OPERATOR_VOICE_DB - DUCK_DEPTH_TOLERANCE_DB
        worst_high = max(span, key=lambda s: s.gain_db)
        worst_low = min(span, key=lambda s: s.gain_db)
        assert worst_high.gain_db <= ceiling_db, (
            f"upward pump: bed rose to {worst_high.gain_db:.1f} dB at "
            f"t={worst_high.t_ms:.0f}ms (ceiling {ceiling_db:.1f} dB)"
        )
        assert worst_low.gain_db >= floor_db, (
            f"downward pump: bed dipped to {worst_low.gain_db:.1f} dB at "
            f"t={worst_low.t_ms:.0f}ms (floor {floor_db:.1f} dB)"
        )

    def test_pumping_amplitude_bounded_to_depth_handoff(self) -> None:
        """Peak-to-peak gain movement during the conversation is at most
        the -12 ↔ -8 depth handoff plus tolerance — no full-range swings."""
        trace = _run_alternation_script(RAPID_ALTERNATION, tail_ms=TAIL_MS)
        span = [s.gain_db for s in trace if s.in_conversation and s.t_ms >= SETTLE_MS]
        peak_to_peak = max(span) - min(span)
        depth_step = abs(DUCK_DEPTH_TTS_DB - DUCK_DEPTH_OPERATOR_VOICE_DB)
        assert peak_to_peak <= depth_step + 2 * DUCK_DEPTH_TOLERANCE_DB, (
            f"pumping amplitude {peak_to_peak:.1f} dB exceeds the depth "
            f"handoff bound {depth_step + 2 * DUCK_DEPTH_TOLERANCE_DB:.1f} dB"
        )

    def test_bed_recovers_to_unity_after_conversation(self) -> None:
        """Fail-open-to-unity spirit at end-of-conversation: once the
        script ends, hold-open + handoff hold + release all expire and the
        bed returns to unity — the duck never sticks."""
        trace = _run_alternation_script(RAPID_ALTERNATION, tail_ms=TAIL_MS)
        assert trace[-1].gain_db == pytest.approx(0.0, abs=0.1)
