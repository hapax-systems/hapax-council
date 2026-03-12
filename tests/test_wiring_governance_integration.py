"""Integration tests: multi-source wiring → governance chains.

Aggregate-of-aggregates: full source-to-governance pipeline.
Verifies source selection, cross-domain isolation, and source failure isolation.
"""

from __future__ import annotations

import time

from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.mc_governance import MCAction, compose_mc_governance
from agents.hapax_voice.obs_governance import OBSScene, compose_obs_governance
from agents.hapax_voice.primitives import Behavior, Event
from agents.hapax_voice.source_naming import qualify
from agents.hapax_voice.timeline import TimelineMapping, TransportState
from agents.hapax_voice.wiring import (
    GovernanceBinding,
    aggregate_max,
    build_behavior_alias,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_multi_source_behaviors(
    *,
    monitor_mix_energy: float = 0.7,
    oxi_one_energy: float = 0.3,
    face_cam_arousal: float = 0.6,
    overhead_gear_arousal: float = 0.1,
    vad_confidence: float = 0.0,
    transport: TransportState = TransportState.PLAYING,
    tempo: float = 120.0,
    watermark: float | None = None,
    stream_bitrate: float = 4500.0,
    stream_encoding_lag: float = 30.0,
) -> dict[str, Behavior]:
    """Build a multi-source behaviors dict simulating parameterized backends."""
    wm = watermark if watermark is not None else time.monotonic()
    mapping = TimelineMapping(
        reference_time=wm - 10.0, reference_beat=0.0, tempo=tempo, transport=transport
    )
    return {
        # Audio energy — two sources
        qualify("audio_energy_rms", "monitor_mix"): Behavior(monitor_mix_energy, watermark=wm),
        qualify("audio_onset", "monitor_mix"): Behavior(False, watermark=wm),
        qualify("audio_energy_rms", "oxi_one"): Behavior(oxi_one_energy, watermark=wm),
        qualify("audio_onset", "oxi_one"): Behavior(False, watermark=wm),
        # Emotion — two cameras
        qualify("emotion_valence", "face_cam"): Behavior(0.2, watermark=wm),
        qualify("emotion_arousal", "face_cam"): Behavior(face_cam_arousal, watermark=wm),
        qualify("emotion_dominant", "face_cam"): Behavior("neutral", watermark=wm),
        qualify("emotion_valence", "overhead_gear"): Behavior(0.0, watermark=wm),
        qualify("emotion_arousal", "overhead_gear"): Behavior(overhead_gear_arousal, watermark=wm),
        qualify("emotion_dominant", "overhead_gear"): Behavior("neutral", watermark=wm),
        # Singletons
        "vad_confidence": Behavior(vad_confidence, watermark=wm),
        "timeline_mapping": Behavior(mapping, watermark=wm),
        # Stream health
        "stream_bitrate": Behavior(stream_bitrate, watermark=wm),
        "stream_encoding_lag": Behavior(stream_encoding_lag, watermark=wm),
        "stream_dropped_frames": Behavior(0.5, watermark=wm),
    }


def _wire_mc(
    all_behaviors: dict[str, Behavior],
    binding: GovernanceBinding | None = None,
) -> tuple[Event[float], Event[Schedule | None]]:
    """Wire MC governance through the aliasing layer. Returns (trigger, output)."""
    b = binding or GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
    alias = build_behavior_alias(all_behaviors, b)
    trigger: Event[float] = Event()
    output = compose_mc_governance(trigger, alias)
    return trigger, output


def _wire_obs(
    all_behaviors: dict[str, Behavior],
    binding: GovernanceBinding | None = None,
) -> tuple[Event[float], Event[Command | None]]:
    """Wire OBS governance through the aliasing layer. Returns (trigger, output)."""
    b = binding or GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
    stream_behaviors = {k: v for k, v in all_behaviors.items() if k.startswith("stream_")}
    alias = build_behavior_alias(all_behaviors, b, stream_behaviors=stream_behaviors)
    trigger: Event[float] = Event()
    output = compose_obs_governance(trigger, alias)
    return trigger, output


def _fire(trigger: Event, output: Event, trigger_time: float | None = None):
    """Fire a trigger and return the governance output."""
    received = []
    output.subscribe(lambda ts, val: received.append(val))
    t = trigger_time if trigger_time is not None else time.monotonic()
    trigger.emit(t, t)
    assert len(received) == 1
    return received[0]


# ===========================================================================
# MC governance with multi-source wiring
# ===========================================================================


class TestMCGovernanceWithMultiSource:
    def test_monitor_mix_high_energy_produces_vocal_throw(self):
        """High energy on monitor_mix (MC-bound source) → vocal throw."""
        behaviors = _make_multi_source_behaviors(monitor_mix_energy=0.9, face_cam_arousal=0.8)
        trigger, output = _wire_mc(behaviors)
        result = _fire(trigger, output)
        assert result is not None
        assert result.command.action == MCAction.VOCAL_THROW.value

    def test_oxi_one_high_energy_does_not_affect_mc(self):
        """High energy on oxi_one but low on monitor_mix → MC sees low energy → vetoed."""
        behaviors = _make_multi_source_behaviors(
            monitor_mix_energy=0.1,  # below MC threshold
            oxi_one_energy=0.9,  # irrelevant to MC
            face_cam_arousal=0.8,
        )
        trigger, output = _wire_mc(behaviors)
        result = _fire(trigger, output)
        assert result is None  # vetoed — energy_sufficient fails on monitor_mix

    def test_face_cam_arousal_enables_vocal_throw(self):
        """Arousal from face_cam (MC-bound emotion source) enables high-energy action."""
        behaviors = _make_multi_source_behaviors(
            monitor_mix_energy=0.9,
            face_cam_arousal=0.8,
            overhead_gear_arousal=0.1,  # irrelevant
        )
        trigger, output = _wire_mc(behaviors)
        result = _fire(trigger, output)
        assert result is not None
        assert result.command.action == MCAction.VOCAL_THROW.value

    def test_overhead_cam_arousal_does_not_affect_mc(self):
        """High arousal on overhead but low on face_cam → MC sees low arousal → ad_lib not vocal_throw."""
        behaviors = _make_multi_source_behaviors(
            monitor_mix_energy=0.9,
            face_cam_arousal=0.1,  # below vocal_throw threshold
            overhead_gear_arousal=0.9,  # irrelevant to MC
        )
        trigger, output = _wire_mc(behaviors)
        result = _fire(trigger, output)
        # Energy passes but low arousal → ad_lib at best (energy 0.9 >= ad_lib 0.3, arousal 0.1 < 0.3)
        # Actually: ad_lib requires arousal >= 0.3, arousal is 0.1 → silence
        # But silence would be vetoed by energy_sufficient? No — energy IS sufficient.
        # The chain: energy veto passes (0.9 >= 0.3), then FallbackChain selects.
        # vocal_throw: 0.9 >= 0.7 AND 0.1 >= 0.6? No.
        # ad_lib: 0.9 >= 0.3 AND 0.1 >= 0.3? No.
        # default: SILENCE
        assert result is not None  # not vetoed, just silence action
        assert result.command.action == MCAction.SILENCE.value


# ===========================================================================
# OBS governance with multi-source wiring
# ===========================================================================


class TestOBSGovernanceWithMultiSource:
    def test_monitor_mix_peak_energy_produces_rapid_cut(self):
        behaviors = _make_multi_source_behaviors(monitor_mix_energy=0.9, face_cam_arousal=0.8)
        trigger, output = _wire_obs(behaviors)
        result = _fire(trigger, output)
        assert result is not None
        assert result.action == OBSScene.RAPID_CUT.value

    def test_face_cam_arousal_drives_scene_selection(self):
        """Low arousal + moderate energy → gear_closeup (not face_cam scene)."""
        behaviors = _make_multi_source_behaviors(monitor_mix_energy=0.4, face_cam_arousal=0.1)
        trigger, output = _wire_obs(behaviors)
        result = _fire(trigger, output)
        assert result is not None
        assert result.action == OBSScene.GEAR_CLOSEUP.value

    def test_aggregate_energy_mode(self):
        """When OBS is wired to aggregate_max, any instrument peaking triggers response."""
        behaviors = _make_multi_source_behaviors(
            monitor_mix_energy=0.3,  # low
            oxi_one_energy=0.9,  # high
            face_cam_arousal=0.8,
        )
        # Create aggregate behavior from all audio sources
        agg = aggregate_max(behaviors, "audio_energy_rms")
        assert agg.value == 0.9  # oxi_one wins

        # Wire OBS with a custom alias that uses aggregate for energy
        binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        stream_behaviors = {k: v for k, v in behaviors.items() if k.startswith("stream_")}
        alias = build_behavior_alias(behaviors, binding, stream_behaviors=stream_behaviors)
        # Override energy with aggregate
        alias["audio_energy_rms"] = agg

        trigger: Event[float] = Event()
        output = compose_obs_governance(trigger, alias)
        received: list[Command | None] = []
        output.subscribe(lambda ts, val: received.append(val))
        now = time.monotonic()
        trigger.emit(now, now)

        assert len(received) == 1
        assert received[0] is not None
        # 0.9 energy + 0.8 arousal → rapid_cut
        assert received[0].action == OBSScene.RAPID_CUT.value


# ===========================================================================
# Cross-domain isolation with multi-source
# ===========================================================================


class TestCrossDomainIsolationWithMultiSource:
    def test_mc_and_obs_can_use_different_emotion_sources(self):
        """MC wired to face_cam, OBS wired to overhead_gear — different arousal readings."""
        behaviors = _make_multi_source_behaviors(
            monitor_mix_energy=0.9,
            face_cam_arousal=0.1,  # low — MC sees low
            overhead_gear_arousal=0.8,  # high — OBS sees high
        )
        mc_binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        obs_binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="overhead_gear")

        mc_trigger, mc_output = _wire_mc(behaviors, mc_binding)
        obs_trigger, obs_output = _wire_obs(behaviors, obs_binding)

        mc_result = _fire(mc_trigger, mc_output)
        obs_result = _fire(obs_trigger, obs_output)

        # MC: high energy but low arousal → silence
        assert mc_result is not None
        assert mc_result.command.action == MCAction.SILENCE.value

        # OBS: high energy + high arousal → rapid_cut
        assert obs_result is not None
        assert obs_result.action == OBSScene.RAPID_CUT.value

    def test_mc_and_obs_share_timeline_without_interference(self):
        """Both chains use the same unqualified timeline_mapping."""
        behaviors = _make_multi_source_behaviors(monitor_mix_energy=0.9, face_cam_arousal=0.8)
        mc_binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        obs_binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")

        mc_alias = build_behavior_alias(behaviors, mc_binding)
        stream_behaviors = {k: v for k, v in behaviors.items() if k.startswith("stream_")}
        obs_alias = build_behavior_alias(behaviors, obs_binding, stream_behaviors=stream_behaviors)

        # Both see the same timeline_mapping object
        assert mc_alias["timeline_mapping"] is obs_alias["timeline_mapping"]

    def test_source_failure_isolates_to_one_chain(self):
        """If face_cam goes stale, MC (bound to face_cam) is affected but OBS (bound to overhead_gear) isn't."""
        now = time.monotonic()
        stale_wm = now - 5.0  # 5s stale (MC emotion max staleness is 3.0s)

        # Build behaviors with face_cam already stale at creation time
        mapping = TimelineMapping(
            reference_time=now - 10.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.PLAYING,
        )
        behaviors = {
            # Audio energy — fresh
            qualify("audio_energy_rms", "monitor_mix"): Behavior(0.9, watermark=now),
            qualify("audio_onset", "monitor_mix"): Behavior(False, watermark=now),
            qualify("audio_energy_rms", "oxi_one"): Behavior(0.3, watermark=now),
            qualify("audio_onset", "oxi_one"): Behavior(False, watermark=now),
            # face_cam emotion — STALE
            qualify("emotion_valence", "face_cam"): Behavior(0.2, watermark=stale_wm),
            qualify("emotion_arousal", "face_cam"): Behavior(0.8, watermark=stale_wm),
            qualify("emotion_dominant", "face_cam"): Behavior("neutral", watermark=stale_wm),
            # overhead_gear emotion — fresh
            qualify("emotion_valence", "overhead_gear"): Behavior(0.0, watermark=now),
            qualify("emotion_arousal", "overhead_gear"): Behavior(0.8, watermark=now),
            qualify("emotion_dominant", "overhead_gear"): Behavior("neutral", watermark=now),
            # Singletons — fresh
            "vad_confidence": Behavior(0.0, watermark=now),
            "timeline_mapping": Behavior(mapping, watermark=now),
            "stream_bitrate": Behavior(4500.0, watermark=now),
            "stream_encoding_lag": Behavior(30.0, watermark=now),
            "stream_dropped_frames": Behavior(0.5, watermark=now),
        }

        # MC bound to face_cam
        mc_binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="face_cam")
        mc_trigger, mc_output = _wire_mc(behaviors, mc_binding)

        # OBS bound to overhead_gear (which is fresh)
        obs_binding = GovernanceBinding(energy_source="monitor_mix", emotion_source="overhead_gear")
        obs_trigger, obs_output = _wire_obs(behaviors, obs_binding)

        mc_result = _fire(mc_trigger, mc_output, trigger_time=now)
        obs_result = _fire(obs_trigger, obs_output, trigger_time=now)

        # MC: face_cam emotion is 5s stale, max is 3s → freshness rejection
        assert mc_result is None

        # OBS: overhead_gear emotion is fresh → produces command
        assert obs_result is not None
        assert obs_result.action == OBSScene.RAPID_CUT.value

    def test_stream_health_only_affects_obs(self):
        """Low stream bitrate vetoes OBS but MC is unaffected."""
        behaviors = _make_multi_source_behaviors(
            monitor_mix_energy=0.9,
            face_cam_arousal=0.8,
            stream_bitrate=500.0,  # below OBS threshold
        )
        mc_trigger, mc_output = _wire_mc(behaviors)
        obs_trigger, obs_output = _wire_obs(behaviors)

        mc_result = _fire(mc_trigger, mc_output)
        obs_result = _fire(obs_trigger, obs_output)

        # MC doesn't consume stream_bitrate → unaffected
        assert mc_result is not None
        assert mc_result.command.action == MCAction.VOCAL_THROW.value

        # OBS stream_health_sufficient veto fires
        assert obs_result is None
