"""Tests for OBS livestream direction governance — systematic trinary matrices.

Layer 2: Each veto predicate, FallbackChain cell, FreshnessGuard signal tested trinary.
         Hypothesis property tests for composed VetoChain algebraic guarantees.
Layer 3: Full compose_obs_governance as aggregate-of-aggregates with representative cells.
"""

from __future__ import annotations

import time

from hypothesis import given
from hypothesis import strategies as st

from agents.hapax_voice.commands import Command
from agents.hapax_voice.governance import FusedContext
from agents.hapax_voice.obs_governance import (
    OBSScene,
    OBSTransition,
    build_obs_fallback_chain,
    build_obs_freshness_guard,
    build_obs_veto_chain,
    compose_obs_governance,
    dwell_time_respected,
    encoding_capacity_available,
    select_transition,
    stream_health_sufficient,
    transport_active,
)
from agents.hapax_voice.primitives import Behavior, Event, Stamped
from agents.hapax_voice.timeline import TimelineMapping, TransportState

# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------


def _make_obs_context(
    *,
    energy_rms: float = 0.7,
    emotion_arousal: float = 0.5,
    stream_bitrate: float = 4500.0,
    stream_encoding_lag: float = 30.0,
    stream_dropped_frames: float = 0.5,
    transport: TransportState = TransportState.PLAYING,
    tempo: float = 120.0,
    trigger_time: float = 1000.0,
    energy_watermark: float | None = None,
    emotion_watermark: float | None = None,
    stream_watermark: float | None = None,
    timeline_watermark: float | None = None,
) -> FusedContext:
    """Build a FusedContext with OBS-relevant samples."""
    e_wm = energy_watermark if energy_watermark is not None else trigger_time
    em_wm = emotion_watermark if emotion_watermark is not None else trigger_time
    s_wm = stream_watermark if stream_watermark is not None else trigger_time
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
        "stream_bitrate": Stamped(value=stream_bitrate, watermark=s_wm),
        "stream_encoding_lag": Stamped(value=stream_encoding_lag, watermark=s_wm),
        "stream_dropped_frames": Stamped(value=stream_dropped_frames, watermark=s_wm),
        "timeline_mapping": Stamped(value=mapping, watermark=t_wm),
    }
    return FusedContext(
        trigger_time=trigger_time,
        trigger_value=trigger_time,
        samples=samples,
        min_watermark=min(s.watermark for s in samples.values()),
    )


def _make_obs_behaviors(
    *,
    energy_rms: float = 0.7,
    emotion_arousal: float = 0.5,
    stream_bitrate: float = 4500.0,
    stream_encoding_lag: float = 30.0,
    stream_dropped_frames: float = 0.5,
    transport: TransportState = TransportState.PLAYING,
    tempo: float = 120.0,
    watermark: float | None = None,
) -> dict[str, Behavior]:
    """Build Behavior dict for compose_obs_governance tests."""
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
        "stream_bitrate": Behavior(stream_bitrate, watermark=wm),
        "stream_encoding_lag": Behavior(stream_encoding_lag, watermark=wm),
        "stream_dropped_frames": Behavior(stream_dropped_frames, watermark=wm),
        "timeline_mapping": Behavior(mapping, watermark=wm),
    }


# ===========================================================================
# LAYER 2: Trinary tests for individual veto predicates
# ===========================================================================


class TestDwellTimeRespectedVeto:
    """Trinary on elapsed time vs dwell minimum (5.0s)."""

    def test_below_dwell_denies(self):
        ctx = _make_obs_context(trigger_time=1002.0)
        assert dwell_time_respected(ctx, min_dwell_s=5.0, last_switch_time=[1000.0]) is False

    def test_at_dwell_allows(self):
        ctx = _make_obs_context(trigger_time=1005.0)
        assert dwell_time_respected(ctx, min_dwell_s=5.0, last_switch_time=[1000.0]) is True

    def test_above_dwell_allows(self):
        ctx = _make_obs_context(trigger_time=1010.0)
        assert dwell_time_respected(ctx, min_dwell_s=5.0, last_switch_time=[1000.0]) is True

    def test_no_prior_switch_allows(self):
        ctx = _make_obs_context(trigger_time=1000.0)
        assert dwell_time_respected(ctx, min_dwell_s=5.0, last_switch_time=None) is True

    def test_empty_list_allows(self):
        ctx = _make_obs_context(trigger_time=1000.0)
        assert dwell_time_respected(ctx, min_dwell_s=5.0, last_switch_time=[]) is True


class TestStreamHealthSufficientVeto:
    """Trinary on stream_bitrate vs threshold (2000 kbps)."""

    def test_below_threshold_denies(self):
        ctx = _make_obs_context(stream_bitrate=1000.0)
        assert stream_health_sufficient(ctx, min_bitrate_kbps=2000.0) is False

    def test_at_threshold_allows(self):
        ctx = _make_obs_context(stream_bitrate=2000.0)
        assert stream_health_sufficient(ctx, min_bitrate_kbps=2000.0) is True

    def test_above_threshold_allows(self):
        ctx = _make_obs_context(stream_bitrate=4500.0)
        assert stream_health_sufficient(ctx, min_bitrate_kbps=2000.0) is True


class TestEncodingCapacityAvailableVeto:
    """Trinary on stream_encoding_lag vs max (100ms)."""

    def test_below_max_allows(self):
        ctx = _make_obs_context(stream_encoding_lag=30.0)
        assert encoding_capacity_available(ctx, max_lag_ms=100.0) is True

    def test_at_max_allows(self):
        ctx = _make_obs_context(stream_encoding_lag=100.0)
        assert encoding_capacity_available(ctx, max_lag_ms=100.0) is True

    def test_above_max_denies(self):
        ctx = _make_obs_context(stream_encoding_lag=150.0)
        assert encoding_capacity_available(ctx, max_lag_ms=100.0) is False


class TestOBSTransportActiveVeto:
    """Binary — PLAYING vs STOPPED (same predicate as MC, revalidated in OBS context)."""

    def test_playing_allows(self):
        ctx = _make_obs_context(transport=TransportState.PLAYING)
        assert transport_active(ctx) is True

    def test_stopped_denies(self):
        ctx = _make_obs_context(transport=TransportState.STOPPED)
        assert transport_active(ctx) is False


# ===========================================================================
# LAYER 2: Trinary FallbackChain (energy × arousal 4×3 → OBSScene)
# ===========================================================================


class TestOBSFallbackChainTrinaryCells:
    """energy × arousal → OBSScene selection.

    energy:  low=0.1, moderate=0.4, high=0.6, peak=0.9
    arousal: low=0.1, moderate=0.5, high=0.8

    Expected matrix:
      energy\\arousal | low(0.1)     | moderate(0.5) | high(0.8)
      low(0.1)       | wide_ambient | wide_ambient  | wide_ambient
      moderate(0.4)  | gear_closeup | gear_closeup  | gear_closeup
      high(0.6)      | gear_closeup | face_cam      | face_cam
      peak(0.9)      | gear_closeup | face_cam      | rapid_cut
    """

    def _select(self, energy: float, arousal: float) -> OBSScene:
        ctx = _make_obs_context(energy_rms=energy, emotion_arousal=arousal)
        return build_obs_fallback_chain().select(ctx).action

    # Low energy row — always wide_ambient
    def test_low_energy_low_arousal_wide(self):
        assert self._select(0.1, 0.1) is OBSScene.WIDE_AMBIENT

    def test_low_energy_moderate_arousal_wide(self):
        assert self._select(0.1, 0.5) is OBSScene.WIDE_AMBIENT

    def test_low_energy_high_arousal_wide(self):
        assert self._select(0.1, 0.8) is OBSScene.WIDE_AMBIENT

    # Moderate energy row — gear_closeup (energy passes gear threshold, not face_cam)
    def test_moderate_energy_low_arousal_gear(self):
        assert self._select(0.4, 0.1) is OBSScene.GEAR_CLOSEUP

    def test_moderate_energy_moderate_arousal_gear(self):
        assert self._select(0.4, 0.5) is OBSScene.GEAR_CLOSEUP

    def test_moderate_energy_high_arousal_gear(self):
        assert self._select(0.4, 0.8) is OBSScene.GEAR_CLOSEUP

    # High energy row — gear or face_cam depending on arousal
    def test_high_energy_low_arousal_gear(self):
        assert self._select(0.6, 0.1) is OBSScene.GEAR_CLOSEUP

    def test_high_energy_moderate_arousal_face(self):
        assert self._select(0.6, 0.5) is OBSScene.FACE_CAM

    def test_high_energy_high_arousal_face(self):
        assert self._select(0.6, 0.8) is OBSScene.FACE_CAM

    # Peak energy row — gear, face, or rapid_cut depending on arousal
    def test_peak_energy_low_arousal_gear(self):
        assert self._select(0.9, 0.1) is OBSScene.GEAR_CLOSEUP

    def test_peak_energy_moderate_arousal_face(self):
        assert self._select(0.9, 0.5) is OBSScene.FACE_CAM

    def test_peak_energy_high_arousal_rapid_cut(self):
        assert self._select(0.9, 0.8) is OBSScene.RAPID_CUT


# ===========================================================================
# LAYER 2: Transition selection (energy-based)
# ===========================================================================


class TestTransitionSelection:
    """Trinary on energy vs hard_cut threshold (0.6)."""

    def test_low_energy_dissolve(self):
        ctx = _make_obs_context(energy_rms=0.3)
        assert select_transition(ctx) is OBSTransition.DISSOLVE

    def test_at_threshold_cut(self):
        ctx = _make_obs_context(energy_rms=0.6)
        assert select_transition(ctx) is OBSTransition.CUT

    def test_high_energy_cut(self):
        ctx = _make_obs_context(energy_rms=0.9)
        assert select_transition(ctx) is OBSTransition.CUT


# ===========================================================================
# LAYER 2: Trinary FreshnessGuard per signal
# ===========================================================================


class TestOBSFreshnessGuardTrinaryCells:
    """Each signal at: fresh (well within), boundary (exactly at max), stale (over max).

    energy: max 3.0s, emotion: max 5.0s, stream_bitrate: max 10.0s
    """

    def _ctx_with_watermarks(
        self, *, energy_wm: float, emotion_wm: float, stream_wm: float, now: float = 100.0
    ):
        """Build context with explicit watermarks."""
        ctx = _make_obs_context(
            trigger_time=now,
            energy_watermark=energy_wm,
            emotion_watermark=emotion_wm,
            stream_watermark=stream_wm,
        )
        return build_obs_freshness_guard().check(ctx, now=now)

    # Energy trinary (max 3.0s): fresh=99.0, boundary=97.0, stale=95.0
    def test_energy_fresh(self):
        r = self._ctx_with_watermarks(energy_wm=99.0, emotion_wm=100.0, stream_wm=100.0)
        assert r.fresh_enough is True

    def test_energy_at_boundary(self):
        r = self._ctx_with_watermarks(energy_wm=97.0, emotion_wm=100.0, stream_wm=100.0)
        assert r.fresh_enough is True

    def test_energy_stale(self):
        r = self._ctx_with_watermarks(energy_wm=95.0, emotion_wm=100.0, stream_wm=100.0)
        assert r.fresh_enough is False
        assert any("audio_energy_rms" in v for v in r.violations)

    # Emotion trinary (max 5.0s): fresh=98.0, boundary=95.0, stale=93.0
    def test_emotion_fresh(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=98.0, stream_wm=100.0)
        assert r.fresh_enough is True

    def test_emotion_at_boundary(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=95.0, stream_wm=100.0)
        assert r.fresh_enough is True

    def test_emotion_stale(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=93.0, stream_wm=100.0)
        assert r.fresh_enough is False
        assert any("emotion_arousal" in v for v in r.violations)

    # Stream bitrate trinary (max 10.0s): fresh=95.0, boundary=90.0, stale=85.0
    def test_stream_fresh(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=100.0, stream_wm=95.0)
        assert r.fresh_enough is True

    def test_stream_at_boundary(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=100.0, stream_wm=90.0)
        assert r.fresh_enough is True

    def test_stream_stale(self):
        r = self._ctx_with_watermarks(energy_wm=100.0, emotion_wm=100.0, stream_wm=85.0)
        assert r.fresh_enough is False
        assert any("stream_bitrate" in v for v in r.violations)

    # Combinations
    def test_all_fresh_passes(self):
        r = self._ctx_with_watermarks(energy_wm=99.0, emotion_wm=98.0, stream_wm=95.0)
        assert r.fresh_enough is True
        assert len(r.violations) == 0

    def test_all_stale_fails(self):
        r = self._ctx_with_watermarks(energy_wm=90.0, emotion_wm=90.0, stream_wm=80.0)
        assert r.fresh_enough is False
        assert len(r.violations) == 3

    def test_one_stale_fails(self):
        r = self._ctx_with_watermarks(energy_wm=95.0, emotion_wm=100.0, stream_wm=100.0)
        assert r.fresh_enough is False
        assert len(r.violations) == 1


# ===========================================================================
# LAYER 2: Hypothesis property tests for composed OBS VetoChain
# ===========================================================================


class TestOBSVetoChainProperties:
    """Algebraic property tests for the composed OBS VetoChain."""

    @given(
        st.floats(min_value=0.0, max_value=10000.0),
        st.floats(min_value=0.0, max_value=300.0),
    )
    def test_commutativity_health_and_encoding(self, bitrate: float, lag: float):
        """Veto outcome is independent of predicate evaluation order."""
        from agents.hapax_voice.governance import Veto, VetoChain

        ctx = _make_obs_context(stream_bitrate=bitrate, stream_encoding_lag=lag)
        chain_ab = VetoChain(
            [
                Veto(name="health", predicate=lambda c: stream_health_sufficient(c)),
                Veto(name="encoding", predicate=lambda c: encoding_capacity_available(c)),
            ]
        )
        chain_ba = VetoChain(
            [
                Veto(name="encoding", predicate=lambda c: encoding_capacity_available(c)),
                Veto(name="health", predicate=lambda c: stream_health_sufficient(c)),
            ]
        )
        assert chain_ab.evaluate(ctx).allowed == chain_ba.evaluate(ctx).allowed

    @given(st.floats(min_value=0.0, max_value=10000.0))
    def test_monotonicity_adding_veto_only_restricts(self, bitrate: float):
        """Adding transport_active veto can only make the system more restrictive."""
        from agents.hapax_voice.governance import Veto, VetoChain

        ctx = _make_obs_context(stream_bitrate=bitrate)
        base = VetoChain(
            [
                Veto(name="health", predicate=lambda c: stream_health_sufficient(c)),
            ]
        )
        extended = VetoChain(
            [
                Veto(name="health", predicate=lambda c: stream_health_sufficient(c)),
                Veto(name="transport", predicate=transport_active),
            ]
        )
        base_result = base.evaluate(ctx).allowed
        extended_result = extended.evaluate(ctx).allowed
        if extended_result:
            assert base_result is True

    @given(
        st.floats(min_value=0.0, max_value=10000.0),
        st.floats(min_value=0.0, max_value=300.0),
    )
    def test_or_composition_preserves_deny_wins(self, bitrate: float, lag: float):
        """(health_chain | encoding_chain) denies if either component denies."""
        from agents.hapax_voice.governance import Veto, VetoChain

        ctx = _make_obs_context(stream_bitrate=bitrate, stream_encoding_lag=lag)
        health_chain = VetoChain(
            [
                Veto(name="health", predicate=lambda c: stream_health_sufficient(c)),
            ]
        )
        encoding_chain = VetoChain(
            [
                Veto(name="encoding", predicate=lambda c: encoding_capacity_available(c)),
            ]
        )
        composed = health_chain | encoding_chain
        composed_result = composed.evaluate(ctx).allowed
        health_result = health_chain.evaluate(ctx).allowed
        encoding_result = encoding_chain.evaluate(ctx).allowed
        assert composed_result == (health_result and encoding_result)

    @given(
        st.floats(min_value=0.0, max_value=10000.0),
        st.floats(min_value=0.0, max_value=300.0),
        st.sampled_from([TransportState.PLAYING, TransportState.STOPPED]),
    )
    def test_idempotence(self, bitrate: float, lag: float, transport: TransportState):
        """chain | chain produces same allowed/denied outcome as chain alone."""
        ctx = _make_obs_context(
            stream_bitrate=bitrate, stream_encoding_lag=lag, transport=transport
        )
        chain = build_obs_veto_chain()
        doubled = chain | chain
        assert chain.evaluate(ctx).allowed == doubled.evaluate(ctx).allowed

    @given(st.floats(min_value=0.0, max_value=10000.0))
    def test_deny_absorbs(self, bitrate: float):
        """If transport is stopped, the full chain denies regardless of stream health."""
        ctx = _make_obs_context(stream_bitrate=bitrate, transport=TransportState.STOPPED)
        result = build_obs_veto_chain().evaluate(ctx)
        assert result.allowed is False
        assert "transport_active" in result.denied_by


# ===========================================================================
# LAYER 3: Aggregate-of-aggregates — compose_obs_governance
# ===========================================================================


class TestOBSComposeAggregateOfAggregates:
    """Full compose_obs_governance tested with representative cross-product cells."""

    def _fire(self, behaviors, cfg=None, trigger_time=None):
        """Wire compose, fire one trigger, return emitted Command or None."""
        trigger: Event[float] = Event()
        output = compose_obs_governance(trigger, behaviors, cfg)
        received: list[Command | None] = []
        output.subscribe(lambda ts, val: received.append(val))
        t = trigger_time if trigger_time is not None else time.monotonic()
        trigger.emit(t, t)
        assert len(received) == 1
        return received[0]

    def test_all_clear_peak_energy_produces_rapid_cut_command(self):
        behaviors = _make_obs_behaviors(energy_rms=0.9, emotion_arousal=0.8)
        result = self._fire(behaviors)
        assert result is not None
        assert result.action == OBSScene.RAPID_CUT.value
        assert result.selected_by == "rapid_cut"
        assert result.params["transition"] == OBSTransition.CUT.value

    def test_all_clear_high_energy_produces_face_cam_command(self):
        behaviors = _make_obs_behaviors(energy_rms=0.6, emotion_arousal=0.6)
        result = self._fire(behaviors)
        assert result is not None
        assert result.action == OBSScene.FACE_CAM.value
        assert result.selected_by == "face_cam"

    def test_all_clear_moderate_energy_produces_gear_closeup_command(self):
        behaviors = _make_obs_behaviors(energy_rms=0.4, emotion_arousal=0.1)
        result = self._fire(behaviors)
        assert result is not None
        assert result.action == OBSScene.GEAR_CLOSEUP.value
        assert result.selected_by == "gear_closeup"

    def test_all_clear_low_energy_produces_wide_ambient_command(self):
        behaviors = _make_obs_behaviors(energy_rms=0.1, emotion_arousal=0.1)
        result = self._fire(behaviors)
        assert result is not None
        assert result.action == OBSScene.WIDE_AMBIENT.value
        assert result.selected_by == "default"

    def test_low_bitrate_vetoes_command(self):
        behaviors = _make_obs_behaviors(energy_rms=0.9, emotion_arousal=0.8, stream_bitrate=500.0)
        result = self._fire(behaviors)
        assert result is None

    def test_high_encoding_lag_vetoes_command(self):
        behaviors = _make_obs_behaviors(
            energy_rms=0.9, emotion_arousal=0.8, stream_encoding_lag=200.0
        )
        result = self._fire(behaviors)
        assert result is None

    def test_transport_stopped_vetoes_command(self):
        behaviors = _make_obs_behaviors(
            energy_rms=0.9, emotion_arousal=0.8, transport=TransportState.STOPPED
        )
        result = self._fire(behaviors)
        assert result is None

    def test_stale_energy_rejects_before_veto(self):
        now = time.monotonic()
        behaviors = _make_obs_behaviors(energy_rms=0.9, emotion_arousal=0.8, watermark=now - 5.0)
        result = self._fire(behaviors, trigger_time=now)
        # energy is 5.0s stale, max is 3.0s → freshness rejection
        assert result is None

    def test_dwell_cooldown_vetoes_rapid_switches(self):
        """Two triggers <5s apart → second vetoed by dwell time."""
        trigger: Event[float] = Event()
        behaviors = _make_obs_behaviors(energy_rms=0.9, emotion_arousal=0.8)
        output = compose_obs_governance(trigger, behaviors)
        received: list[Command | None] = []
        output.subscribe(lambda ts, val: received.append(val))

        now = time.monotonic()
        trigger.emit(now, now)  # first switch — allowed
        trigger.emit(now + 2.0, now + 2.0)  # 2s later — dwell cooldown blocks

        assert len(received) == 2
        assert received[0] is not None  # first allowed
        assert received[1] is None  # second vetoed

    def test_command_carries_governance_provenance(self):
        behaviors = _make_obs_behaviors(energy_rms=0.9, emotion_arousal=0.8)
        result = self._fire(behaviors)
        assert result is not None
        assert result.trigger_source == "obs_governance"
        assert result.governance_result.allowed is True
        assert len(result.governance_result.denied_by) == 0
        assert result.selected_by == "rapid_cut"

    def test_command_includes_transition_style(self):
        """High energy → cut transition, low energy → dissolve."""
        high_behaviors = _make_obs_behaviors(energy_rms=0.9, emotion_arousal=0.8)
        high_result = self._fire(high_behaviors)
        assert high_result is not None
        assert high_result.params["transition"] == OBSTransition.CUT.value

        low_behaviors = _make_obs_behaviors(energy_rms=0.3, emotion_arousal=0.1)
        low_result = self._fire(low_behaviors)
        assert low_result is not None
        assert low_result.params["transition"] == OBSTransition.DISSOLVE.value

    def test_multiple_triggers_with_sufficient_dwell(self):
        """Three triggers with enough spacing produce independent commands."""
        trigger: Event[float] = Event()
        behaviors = _make_obs_behaviors(energy_rms=0.9, emotion_arousal=0.8)
        output = compose_obs_governance(trigger, behaviors)
        received: list[Command | None] = []
        output.subscribe(lambda ts, val: received.append(val))

        now = time.monotonic()
        trigger.emit(now, now)
        for b in behaviors.values():
            b.update(b.value, now + 6.0)
        trigger.emit(now + 6.0, now + 6.0)  # past dwell time
        for b in behaviors.values():
            b.update(b.value, now + 12.0)
        trigger.emit(now + 12.0, now + 12.0)  # past dwell time

        assert len(received) == 3
        assert all(r is not None for r in received)
        assert all(r.action == OBSScene.RAPID_CUT.value for r in received)


# ===========================================================================
# CROSS-DOMAIN: OBS governance doesn't interfere with MC perception
# ===========================================================================


class TestCrossDomainIndependence:
    """Verify OBS and MC governance chains share Behaviors without interference."""

    def test_stream_health_only_affects_obs_not_mc(self):
        """Low bitrate vetoes OBS but MC-relevant signals are unaffected."""
        ctx = _make_obs_context(
            energy_rms=0.9,
            emotion_arousal=0.8,
            stream_bitrate=500.0,  # below OBS threshold
        )
        obs_chain = build_obs_veto_chain()
        result = obs_chain.evaluate(ctx)
        assert result.allowed is False
        assert "stream_health_sufficient" in result.denied_by

    def test_obs_dwell_independent_of_mc_spacing(self):
        """OBS dwell time and MC spacing are independent governance constraints."""
        obs_last = [1000.0]
        mc_last = [1000.0]

        ctx = _make_obs_context(trigger_time=1003.0)

        # OBS dwell (5s) not met at 1003
        assert dwell_time_respected(ctx, min_dwell_s=5.0, last_switch_time=obs_last) is False

        # MC spacing (4s) also not met — but these are independent clocks
        from agents.hapax_voice.mc_governance import spacing_respected

        mc_ctx = FusedContext(
            trigger_time=1003.0,
            trigger_value=1003.0,
            samples=ctx.samples,
            min_watermark=ctx.min_watermark,
        )
        assert spacing_respected(mc_ctx, cooldown_s=4.0, last_throw_time=mc_last) is False

        # Advance to 1005 — OBS dwell met, MC spacing also met
        ctx2 = _make_obs_context(trigger_time=1005.0)
        assert dwell_time_respected(ctx2, min_dwell_s=5.0, last_switch_time=obs_last) is True

        mc_ctx2 = FusedContext(
            trigger_time=1005.0,
            trigger_value=1005.0,
            samples=ctx2.samples,
            min_watermark=ctx2.min_watermark,
        )
        assert spacing_respected(mc_ctx2, cooldown_s=4.0, last_throw_time=mc_last) is True
