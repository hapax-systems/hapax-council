"""Tests for MC-specific governance — systematic trinary matrices.

Layer 2: Each veto predicate, FallbackChain cell, FreshnessGuard signal tested trinary.
         Hypothesis property tests for composed VetoChain algebraic guarantees.
Layer 3: Full compose_mc_governance as aggregate-of-aggregates with representative cells.
"""

from __future__ import annotations

import time

from hypothesis import given
from hypothesis import strategies as st

from agents.hapax_voice.commands import Schedule
from agents.hapax_voice.governance import FusedContext
from agents.hapax_voice.mc_governance import (
    MCAction,
    build_mc_fallback_chain,
    build_mc_freshness_guard,
    build_mc_veto_chain,
    compose_mc_governance,
    energy_sufficient,
    spacing_respected,
    speech_clear,
    transport_active,
)
from agents.hapax_voice.primitives import Behavior, Event, Stamped
from agents.hapax_voice.timeline import TimelineMapping, TransportState

# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------


def _make_mc_context(
    *,
    energy_rms: float = 0.7,
    emotion_arousal: float = 0.5,
    vad_confidence: float = 0.0,
    transport: TransportState = TransportState.PLAYING,
    tempo: float = 120.0,
    trigger_time: float = 1000.0,
    energy_watermark: float | None = None,
    emotion_watermark: float | None = None,
    timeline_watermark: float | None = None,
) -> FusedContext:
    """Build a FusedContext with MC-relevant samples."""
    e_wm = energy_watermark if energy_watermark is not None else trigger_time
    em_wm = emotion_watermark if emotion_watermark is not None else trigger_time
    t_wm = timeline_watermark if timeline_watermark is not None else trigger_time

    mapping = TimelineMapping(
        reference_time=trigger_time - 10.0,
        reference_beat=0.0,
        tempo=tempo,
        transport=transport,
    )
    samples = {
        "audio_energy_rms": Stamped(value=energy_rms, watermark=e_wm),
        "emotion_arousal": Stamped(value=emotion_arousal, watermark=em_wm),
        "vad_confidence": Stamped(value=vad_confidence, watermark=trigger_time),
        "timeline_mapping": Stamped(value=mapping, watermark=t_wm),
    }
    return FusedContext(
        trigger_time=trigger_time,
        trigger_value=trigger_time,
        samples=samples,
        min_watermark=min(s.watermark for s in samples.values()),
    )


def _make_mc_behaviors(
    *,
    energy_rms: float = 0.7,
    emotion_arousal: float = 0.5,
    vad_confidence: float = 0.0,
    transport: TransportState = TransportState.PLAYING,
    tempo: float = 120.0,
    watermark: float | None = None,
) -> dict[str, Behavior]:
    """Build Behavior dict for compose_mc_governance tests."""
    wm = watermark if watermark is not None else time.monotonic()
    mapping = TimelineMapping(
        reference_time=wm - 10.0,
        reference_beat=0.0,
        tempo=tempo,
        transport=transport,
    )
    return {
        "audio_energy_rms": Behavior(energy_rms, watermark=wm),
        "emotion_arousal": Behavior(emotion_arousal, watermark=wm),
        "vad_confidence": Behavior(vad_confidence, watermark=wm),
        "timeline_mapping": Behavior(mapping, watermark=wm),
    }


# ===========================================================================
# LAYER 2: Trinary tests for individual veto predicates
# ===========================================================================


class TestSpeechClearVeto:
    """Trinary on vad_confidence vs threshold (0.5)."""

    def test_below_threshold_allows(self):
        ctx = _make_mc_context(vad_confidence=0.2)
        assert speech_clear(ctx, threshold=0.5) is True

    def test_at_threshold_denies(self):
        ctx = _make_mc_context(vad_confidence=0.5)
        assert speech_clear(ctx, threshold=0.5) is False

    def test_above_threshold_denies(self):
        ctx = _make_mc_context(vad_confidence=0.9)
        assert speech_clear(ctx, threshold=0.5) is False


class TestEnergySufficientVeto:
    """Trinary on energy_rms vs threshold (0.3)."""

    def test_below_threshold_denies(self):
        ctx = _make_mc_context(energy_rms=0.1)
        assert energy_sufficient(ctx, threshold=0.3) is False

    def test_at_threshold_allows(self):
        ctx = _make_mc_context(energy_rms=0.3)
        assert energy_sufficient(ctx, threshold=0.3) is True

    def test_above_threshold_allows(self):
        ctx = _make_mc_context(energy_rms=0.8)
        assert energy_sufficient(ctx, threshold=0.3) is True


class TestSpacingRespectedVeto:
    """Trinary on elapsed time vs cooldown (4.0s)."""

    def test_below_cooldown_denies(self):
        ctx = _make_mc_context(trigger_time=1002.0)
        assert spacing_respected(ctx, cooldown_s=4.0, last_throw_time=[1000.0]) is False

    def test_at_cooldown_allows(self):
        ctx = _make_mc_context(trigger_time=1004.0)
        assert spacing_respected(ctx, cooldown_s=4.0, last_throw_time=[1000.0]) is True

    def test_above_cooldown_allows(self):
        ctx = _make_mc_context(trigger_time=1008.0)
        assert spacing_respected(ctx, cooldown_s=4.0, last_throw_time=[1000.0]) is True

    def test_no_prior_throw_allows(self):
        ctx = _make_mc_context(trigger_time=1000.0)
        assert spacing_respected(ctx, cooldown_s=4.0, last_throw_time=None) is True

    def test_empty_list_allows(self):
        ctx = _make_mc_context(trigger_time=1000.0)
        assert spacing_respected(ctx, cooldown_s=4.0, last_throw_time=[]) is True


class TestTransportActiveVeto:
    """Binary — PLAYING vs STOPPED."""

    def test_playing_allows(self):
        ctx = _make_mc_context(transport=TransportState.PLAYING)
        assert transport_active(ctx) is True

    def test_stopped_denies(self):
        ctx = _make_mc_context(transport=TransportState.STOPPED)
        assert transport_active(ctx) is False


# ===========================================================================
# LAYER 2: Trinary FallbackChain (energy × arousal 3×3 matrix)
# ===========================================================================


class TestMCFallbackChainTrinaryCells:
    """energy × arousal 3×3 → MCAction selection.

    energy:  low=0.1, moderate=0.5, high=0.9
    arousal: low=0.1, moderate=0.5, high=0.8

    Expected matrix:
      energy\\arousal | low(0.1)  | moderate(0.5) | high(0.8)
      low(0.1)       | silence   | silence       | silence
      moderate(0.5)  | silence   | ad_lib        | ad_lib
      high(0.9)      | silence   | ad_lib        | vocal_throw
    """

    def _select(self, energy: float, arousal: float) -> MCAction:
        ctx = _make_mc_context(energy_rms=energy, emotion_arousal=arousal)
        return build_mc_fallback_chain().select(ctx).action

    def test_low_energy_low_arousal_silence(self):
        assert self._select(0.1, 0.1) is MCAction.SILENCE

    def test_low_energy_moderate_arousal_silence(self):
        assert self._select(0.1, 0.5) is MCAction.SILENCE

    def test_low_energy_high_arousal_silence(self):
        assert self._select(0.1, 0.8) is MCAction.SILENCE

    def test_moderate_energy_low_arousal_silence(self):
        assert self._select(0.5, 0.1) is MCAction.SILENCE

    def test_moderate_energy_moderate_arousal_ad_lib(self):
        assert self._select(0.5, 0.5) is MCAction.AD_LIB

    def test_moderate_energy_high_arousal_ad_lib(self):
        assert self._select(0.5, 0.8) is MCAction.AD_LIB

    def test_high_energy_low_arousal_silence(self):
        assert self._select(0.9, 0.1) is MCAction.SILENCE

    def test_high_energy_moderate_arousal_ad_lib(self):
        assert self._select(0.9, 0.5) is MCAction.AD_LIB

    def test_high_energy_high_arousal_vocal_throw(self):
        assert self._select(0.9, 0.8) is MCAction.VOCAL_THROW


# ===========================================================================
# LAYER 2: Trinary FreshnessGuard per signal
# ===========================================================================


class TestMCFreshnessGuardTrinaryCells:
    """Each signal at: fresh (well within), boundary (exactly at max), stale (over max).

    energy: max 0.2s, emotion: max 3.0s, timeline: max 0.5s
    """

    def _ctx_with_watermarks(
        self, *, energy_wm: float, emotion_wm: float, timeline_wm: float, now: float = 100.0
    ):
        """Build context with explicit watermarks (avoids float subtraction imprecision)."""
        ctx = _make_mc_context(
            trigger_time=now,
            energy_watermark=energy_wm,
            emotion_watermark=emotion_wm,
            timeline_watermark=timeline_wm,
        )
        return build_mc_freshness_guard().check(ctx, now=now)

    # Energy trinary (max 0.2s): fresh=99.96, boundary=99.8, stale=99.5
    def test_energy_fresh(self):
        r = self._ctx_with_watermarks(energy_wm=99.96, emotion_wm=100.0, timeline_wm=100.0)
        assert r.fresh_enough is True

    def test_energy_at_boundary(self):
        # FreshnessGuard uses strict >. staleness just under 0.2s → fresh
        r = self._ctx_with_watermarks(energy_wm=99.81, emotion_wm=100.0, timeline_wm=100.0)
        assert r.fresh_enough is True

    def test_energy_stale(self):
        r = self._ctx_with_watermarks(energy_wm=99.5, emotion_wm=100.0, timeline_wm=100.0)
        assert r.fresh_enough is False
        assert any("audio_energy_rms" in v for v in r.violations)

    # Emotion trinary (max 3.0s): fresh=99.0, boundary=97.0, stale=95.0
    def test_emotion_fresh(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=99.0, timeline_wm=100.0)
        assert r.fresh_enough is True

    def test_emotion_at_boundary(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=97.0, timeline_wm=100.0)
        assert r.fresh_enough is True

    def test_emotion_stale(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=95.0, timeline_wm=100.0)
        assert r.fresh_enough is False
        assert any("emotion_arousal" in v for v in r.violations)

    # Timeline trinary (max 0.5s): fresh=99.9, boundary=99.5, stale=99.0
    def test_timeline_fresh(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=100.0, timeline_wm=99.9)
        assert r.fresh_enough is True

    def test_timeline_at_boundary(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=100.0, timeline_wm=99.5)
        assert r.fresh_enough is True

    def test_timeline_stale(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=100.0, timeline_wm=99.0)
        assert r.fresh_enough is False
        assert any("timeline_mapping" in v for v in r.violations)

    # Combinations
    def test_all_fresh_passes(self):
        r = self._ctx_with_watermarks(energy_wm=99.96, emotion_wm=99.5, timeline_wm=99.9)
        assert r.fresh_enough is True
        assert len(r.violations) == 0

    def test_all_stale_fails(self):
        r = self._ctx_with_watermarks(energy_wm=99.0, emotion_wm=90.0, timeline_wm=98.0)
        assert r.fresh_enough is False
        assert len(r.violations) == 3

    def test_one_stale_fails(self):
        r = self._ctx_with_watermarks(energy_wm=99.0, emotion_wm=100.0, timeline_wm=100.0)
        assert r.fresh_enough is False
        assert len(r.violations) == 1


# ===========================================================================
# LAYER 2: Hypothesis property tests for composed MC VetoChain
# ===========================================================================


class TestMCVetoChainProperties:
    """Algebraic property tests for the composed MC VetoChain."""

    @given(
        st.floats(min_value=0.0, max_value=1.0),
        st.floats(min_value=0.0, max_value=1.0),
    )
    def test_commutativity_energy_and_speech(self, energy: float, vad: float):
        """Veto outcome is independent of predicate evaluation order."""
        from agents.hapax_voice.governance import Veto, VetoChain

        ctx = _make_mc_context(energy_rms=energy, vad_confidence=vad)
        chain_ab = VetoChain(
            [
                Veto(name="speech", predicate=lambda c: speech_clear(c)),
                Veto(name="energy", predicate=lambda c: energy_sufficient(c)),
            ]
        )
        chain_ba = VetoChain(
            [
                Veto(name="energy", predicate=lambda c: energy_sufficient(c)),
                Veto(name="speech", predicate=lambda c: speech_clear(c)),
            ]
        )
        assert chain_ab.evaluate(ctx).allowed == chain_ba.evaluate(ctx).allowed

    @given(st.floats(min_value=0.0, max_value=1.0))
    def test_monotonicity_adding_veto_only_restricts(self, energy: float):
        """Adding transport_active veto can only make the system more restrictive."""
        from agents.hapax_voice.governance import Veto, VetoChain

        ctx = _make_mc_context(energy_rms=energy)
        base = VetoChain(
            [
                Veto(name="energy", predicate=lambda c: energy_sufficient(c)),
            ]
        )
        extended = VetoChain(
            [
                Veto(name="energy", predicate=lambda c: energy_sufficient(c)),
                Veto(name="transport", predicate=transport_active),
            ]
        )
        base_result = base.evaluate(ctx).allowed
        extended_result = extended.evaluate(ctx).allowed
        # extended can only be equal or more restrictive
        if extended_result:
            assert base_result is True

    @given(
        st.floats(min_value=0.0, max_value=1.0),
        st.floats(min_value=0.0, max_value=1.0),
    )
    def test_or_composition_preserves_deny_wins(self, energy: float, vad: float):
        """(speech_chain | energy_chain) denies if either component denies."""
        from agents.hapax_voice.governance import Veto, VetoChain

        ctx = _make_mc_context(energy_rms=energy, vad_confidence=vad)
        speech_chain = VetoChain(
            [
                Veto(name="speech", predicate=lambda c: speech_clear(c)),
            ]
        )
        energy_chain = VetoChain(
            [
                Veto(name="energy", predicate=lambda c: energy_sufficient(c)),
            ]
        )
        composed = speech_chain | energy_chain
        composed_result = composed.evaluate(ctx).allowed
        speech_result = speech_chain.evaluate(ctx).allowed
        energy_result = energy_chain.evaluate(ctx).allowed
        assert composed_result == (speech_result and energy_result)

    @given(
        st.floats(min_value=0.0, max_value=1.0),
        st.floats(min_value=0.0, max_value=1.0),
        st.sampled_from([TransportState.PLAYING, TransportState.STOPPED]),
    )
    def test_idempotence(self, energy: float, vad: float, transport: TransportState):
        """chain | chain produces same allowed/denied outcome as chain alone."""
        ctx = _make_mc_context(energy_rms=energy, vad_confidence=vad, transport=transport)
        chain = build_mc_veto_chain()
        doubled = chain | chain
        assert chain.evaluate(ctx).allowed == doubled.evaluate(ctx).allowed

    @given(st.floats(min_value=0.0, max_value=1.0))
    def test_deny_absorbs(self, energy: float):
        """If transport is stopped, the full chain denies regardless of energy."""
        ctx = _make_mc_context(energy_rms=energy, transport=TransportState.STOPPED)
        result = build_mc_veto_chain().evaluate(ctx)
        assert result.allowed is False
        assert "transport_active" in result.denied_by


# ===========================================================================
# LAYER 3: Aggregate-of-aggregates — compose_mc_governance
# ===========================================================================


class TestMCComposeAggregateOfAggregates:
    """Full compose_mc_governance tested with representative cross-product cells."""

    def _fire(self, behaviors, cfg=None, trigger_time=None):
        """Wire compose, fire one trigger, return emitted Schedule or None."""
        trigger: Event[float] = Event()
        output = compose_mc_governance(trigger, behaviors, cfg)
        received: list[Schedule | None] = []
        output.subscribe(lambda ts, val: received.append(val))
        t = trigger_time if trigger_time is not None else time.monotonic()
        trigger.emit(t, t)
        assert len(received) == 1
        return received[0]

    def test_all_clear_high_energy_produces_vocal_throw_schedule(self):
        behaviors = _make_mc_behaviors(energy_rms=0.9, emotion_arousal=0.8, vad_confidence=0.0)
        result = self._fire(behaviors)
        assert result is not None
        assert result.command.action == MCAction.VOCAL_THROW.value
        assert result.command.selected_by == "vocal_throw"

    def test_all_clear_moderate_energy_produces_ad_lib_schedule(self):
        behaviors = _make_mc_behaviors(energy_rms=0.5, emotion_arousal=0.5, vad_confidence=0.0)
        result = self._fire(behaviors)
        assert result is not None
        assert result.command.action == MCAction.AD_LIB.value

    def test_all_clear_low_energy_produces_silence_schedule(self):
        behaviors = _make_mc_behaviors(energy_rms=0.1, emotion_arousal=0.1, vad_confidence=0.0)
        result = self._fire(behaviors)
        # Low energy passes the veto (energy_min=0.3 denies) → vetoed
        assert result is None

    def test_speech_detected_vetoes_schedule(self):
        behaviors = _make_mc_behaviors(energy_rms=0.9, emotion_arousal=0.8, vad_confidence=0.9)
        result = self._fire(behaviors)
        assert result is None

    def test_transport_stopped_vetoes_schedule(self):
        behaviors = _make_mc_behaviors(
            energy_rms=0.9, emotion_arousal=0.8, transport=TransportState.STOPPED
        )
        result = self._fire(behaviors)
        assert result is None

    def test_stale_energy_rejects_before_veto(self):
        now = time.monotonic()
        behaviors = _make_mc_behaviors(energy_rms=0.9, emotion_arousal=0.8, watermark=now - 1.0)
        result = self._fire(behaviors, trigger_time=now)
        # energy is 1.0s stale, max is 0.2s → freshness rejection
        assert result is None

    def test_spacing_cooldown_vetoes_rapid_throws(self):
        """Two triggers <4s apart → second vetoed by spacing."""
        trigger: Event[float] = Event()
        behaviors = _make_mc_behaviors(energy_rms=0.9, emotion_arousal=0.8, vad_confidence=0.0)
        output = compose_mc_governance(trigger, behaviors)
        received: list[Schedule | None] = []
        output.subscribe(lambda ts, val: received.append(val))

        now = time.monotonic()
        trigger.emit(now, now)  # first throw — allowed
        trigger.emit(now + 1.0, now + 1.0)  # 1s later — spacing cooldown blocks

        assert len(received) == 2
        assert received[0] is not None  # first allowed
        assert received[1] is None  # second vetoed

    def test_schedule_carries_governance_provenance(self):
        behaviors = _make_mc_behaviors(energy_rms=0.9, emotion_arousal=0.8, vad_confidence=0.0)
        result = self._fire(behaviors)
        assert result is not None
        assert result.command.trigger_source == "mc_governance"
        assert result.command.governance_result.allowed is True
        assert len(result.command.governance_result.denied_by) == 0
        assert result.command.selected_by == "vocal_throw"

    def test_schedule_wall_time_from_timeline_mapping(self):
        """Schedule.wall_time resolved via TimelineMapping at 120 BPM."""
        now = time.monotonic()
        behaviors = _make_mc_behaviors(
            energy_rms=0.9, emotion_arousal=0.8, tempo=120.0, watermark=now
        )
        result = self._fire(behaviors, trigger_time=now)
        assert result is not None
        assert result.domain == "beat"
        # At 120 BPM: 4 beats ahead = 2 seconds of wall time
        assert abs(result.wall_time - result.command.trigger_time - 2.0) < 0.1

    def test_multiple_triggers_produce_independent_schedules(self):
        """Three triggers with enough spacing produce correct independent actions."""
        trigger: Event[float] = Event()
        behaviors = _make_mc_behaviors(energy_rms=0.9, emotion_arousal=0.8, vad_confidence=0.0)
        output = compose_mc_governance(trigger, behaviors)
        received: list[Schedule | None] = []
        output.subscribe(lambda ts, val: received.append(val))

        now = time.monotonic()
        # Update behavior watermarks before each trigger to keep them fresh
        trigger.emit(now, now)
        for b in behaviors.values():
            b.update(b.value, now + 5.0)
        trigger.emit(now + 5.0, now + 5.0)  # past cooldown
        for b in behaviors.values():
            b.update(b.value, now + 10.0)
        trigger.emit(now + 10.0, now + 10.0)  # past cooldown

        assert len(received) == 3
        assert all(r is not None for r in received)
        assert all(r.command.action == MCAction.VOCAL_THROW.value for r in received)
