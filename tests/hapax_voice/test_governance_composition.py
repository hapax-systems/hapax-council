"""L7 matrix tests for compose_mc_governance and compose_obs_governance.

Fills dimensions A (construction), B (invariants), D (boundaries) to bring
L7 from partial → matrix-complete. See agents/hapax_voice/LAYER_STATUS.yaml.

Self-contained, unittest.mock only, asyncio_mode="auto".
"""

from __future__ import annotations

import time
import unittest

from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.mc_governance import (
    MCConfig,
    build_mc_fallback_chain,
    build_mc_freshness_guard,
    build_mc_veto_chain,
    compose_mc_governance,
)
from agents.hapax_voice.obs_governance import (
    OBSConfig,
    OBSTransition,
    build_obs_fallback_chain,
    build_obs_freshness_guard,
    build_obs_veto_chain,
    compose_obs_governance,
    select_transition,
)
from agents.hapax_voice.primitives import Behavior, Event
from agents.hapax_voice.timeline import TimelineMapping, TransportState

# ── Helpers ────────────────────────────────────────────────────────────

# Config with very lenient freshness — for tests that need to fire at
# various offsets from watermark without freshness rejection.
_LENIENT_MC = MCConfig(
    energy_max_staleness_s=999.0,
    emotion_max_staleness_s=999.0,
    timeline_max_staleness_s=999.0,
)
_LENIENT_OBS = OBSConfig(
    energy_max_staleness_s=999.0,
    emotion_max_staleness_s=999.0,
    stream_health_max_staleness_s=999.0,
)


def _mc_behaviors(
    *,
    energy: float = 0.8,
    arousal: float = 0.7,
    vad: float = 0.0,
    tempo: float = 120.0,
    transport: TransportState = TransportState.PLAYING,
    suppression: float | None = None,
    watermark: float | None = None,
) -> dict[str, Behavior]:
    wm = watermark if watermark is not None else time.monotonic()
    mapping = TimelineMapping(
        reference_time=wm - 1.0,
        reference_beat=0.0,
        tempo=tempo,
        transport=transport,
    )
    behaviors: dict[str, Behavior] = {
        "audio_energy_rms": Behavior(energy, watermark=wm),
        "emotion_arousal": Behavior(arousal, watermark=wm),
        "vad_confidence": Behavior(vad, watermark=wm),
        "timeline_mapping": Behavior(mapping, watermark=wm),
    }
    if suppression is not None:
        behaviors["conversation_suppression"] = Behavior(suppression, watermark=wm)
    return behaviors


def _obs_behaviors(
    *,
    energy: float = 0.5,
    arousal: float = 0.5,
    bitrate: float = 5000.0,
    encoding_lag: float = 10.0,
    tempo: float = 120.0,
    transport: TransportState = TransportState.PLAYING,
    last_mc_fire: float | None = None,
    watermark: float | None = None,
) -> dict[str, Behavior]:
    wm = watermark if watermark is not None else time.monotonic()
    mapping = TimelineMapping(
        reference_time=wm - 1.0,
        reference_beat=0.0,
        tempo=tempo,
        transport=transport,
    )
    behaviors: dict[str, Behavior] = {
        "audio_energy_rms": Behavior(energy, watermark=wm),
        "emotion_arousal": Behavior(arousal, watermark=wm),
        "timeline_mapping": Behavior(mapping, watermark=wm),
        "stream_bitrate": Behavior(bitrate, watermark=wm),
        "stream_encoding_lag": Behavior(encoding_lag, watermark=wm),
    }
    if last_mc_fire is not None:
        behaviors["last_mc_fire"] = Behavior(last_mc_fire, watermark=wm)
    return behaviors


def _fire_once(trigger, output_event, timestamp: float | None = None):
    """Fire trigger once and return what the output emitted."""
    results = []
    output_event.subscribe(lambda ts, v: results.append(v))
    ts = timestamp if timestamp is not None else time.monotonic()
    trigger.emit(ts, ts)
    return results


# ── A: Construction ────────────────────────────────────────────────────


class TestMCGovernanceConstruction(unittest.TestCase):
    """Dimension A: compose_mc_governance factory and sub-factories."""

    def test_default_config_produces_output_event(self):
        trigger = Event[float]()
        behaviors = _mc_behaviors()
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        self.assertIsInstance(output, Event)

    def test_custom_config_propagates(self):
        cfg = MCConfig(energy_min_threshold=0.9, vocal_throw_energy_min=0.95)
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors, cfg=cfg)
        results = _fire_once(trigger, output)
        # Energy 0.8 < 0.9 threshold → vetoed
        self.assertIsNone(results[0])

    def test_build_mc_veto_chain_returns_four_vetoes(self):
        chain = build_mc_veto_chain()
        self.assertEqual(len(chain.vetoes), 4)

    def test_build_mc_fallback_chain_returns_two_candidates(self):
        chain = build_mc_fallback_chain()
        self.assertEqual(len(chain.candidates), 2)

    def test_build_mc_freshness_guard_returns_three_requirements(self):
        guard = build_mc_freshness_guard()
        self.assertEqual(len(guard._requirements), 3)

    def test_mc_config_defaults_sensible(self):
        cfg = MCConfig()
        self.assertEqual(cfg.speech_vad_threshold, 0.5)
        self.assertEqual(cfg.energy_min_threshold, 0.3)
        self.assertEqual(cfg.spacing_cooldown_s, 4.0)


class TestOBSGovernanceConstruction(unittest.TestCase):
    """Dimension A: compose_obs_governance factory and sub-factories."""

    def test_default_config_produces_output_event(self):
        trigger = Event[float]()
        behaviors = _obs_behaviors()
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors)
        self.assertIsInstance(output, Event)

    def test_custom_config_propagates(self):
        cfg = OBSConfig(face_cam_energy_min=0.99)
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.5)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors, cfg=cfg)
        results = _fire_once(trigger, output)
        self.assertIsNotNone(results[0])
        self.assertNotEqual(results[0].action, "face_cam")

    def test_build_obs_veto_chain_returns_four_vetoes(self):
        chain = build_obs_veto_chain()
        self.assertEqual(len(chain.vetoes), 4)

    def test_build_obs_fallback_chain_returns_four_candidates(self):
        chain = build_obs_fallback_chain()
        self.assertEqual(len(chain.candidates), 4)

    def test_build_obs_freshness_guard_returns_three_requirements(self):
        guard = build_obs_freshness_guard()
        self.assertEqual(len(guard._requirements), 3)

    def test_obs_config_defaults_sensible(self):
        cfg = OBSConfig()
        self.assertEqual(cfg.dwell_min_s, 5.0)
        self.assertEqual(cfg.stream_health_min_bitrate_kbps, 2000.0)


# ── B: Invariants ──────────────────────────────────────────────────────


class TestMCGovernanceInvariants(unittest.TestCase):
    """Dimension B: output type and provenance invariants."""

    def test_output_is_schedule_when_allowed(self):
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], Schedule)

    def test_output_is_none_when_vetoed(self):
        trigger = Event[float]()
        behaviors = _mc_behaviors(transport=TransportState.STOPPED)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertIsNone(results[0])

    def test_trigger_source_always_mc_governance(self):
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertEqual(results[0].command.trigger_source, "mc_governance")

    def test_governance_result_always_present(self):
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertTrue(results[0].command.governance_result.allowed)

    def test_selected_by_always_present(self):
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertIn(results[0].command.selected_by, {"vocal_throw", "ad_lib", "default"})

    def test_schedule_domain_always_beat(self):
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertEqual(results[0].domain, "beat")

    def test_min_watermark_propagated(self):
        wm = time.monotonic()
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7, watermark=wm)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertEqual(results[0].command.min_watermark, wm)

    def test_spacing_cooldown_enforced_across_emissions(self):
        """Second trigger within cooldown is vetoed (spacing_respected)."""
        wm = 100.0
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7, watermark=wm)
        cfg = MCConfig(
            spacing_cooldown_s=10.0,
            energy_max_staleness_s=999.0,
            emotion_max_staleness_s=999.0,
            timeline_max_staleness_s=999.0,
        )
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors, cfg=cfg)

        results = []
        output.subscribe(lambda ts, v: results.append(v))

        trigger.emit(wm, wm)
        self.assertIsNotNone(results[0])

        trigger.emit(wm + 1.0, wm + 1.0)
        self.assertIsNone(results[1])

        trigger.emit(wm + 11.0, wm + 11.0)
        self.assertIsNotNone(results[2])


class TestOBSGovernanceInvariants(unittest.TestCase):
    """Dimension B: output type and provenance invariants."""

    def test_output_is_command_when_allowed(self):
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.5)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertIsInstance(results[0], Command)
        self.assertNotIsInstance(results[0], Schedule)

    def test_output_is_none_when_vetoed(self):
        trigger = Event[float]()
        behaviors = _obs_behaviors(transport=TransportState.STOPPED)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertIsNone(results[0])

    def test_trigger_source_always_obs_governance(self):
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.5)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertEqual(results[0].trigger_source, "obs_governance")

    def test_transition_param_always_present(self):
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.5)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertIn("transition", results[0].params)
        self.assertIn(results[0].params["transition"], {"cut", "dissolve", "fade"})

    def test_dwell_cooldown_enforced_across_emissions(self):
        wm = 100.0
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.5, watermark=wm)
        cfg = OBSConfig(
            dwell_min_s=5.0,
            energy_max_staleness_s=999.0,
            emotion_max_staleness_s=999.0,
            stream_health_max_staleness_s=999.0,
        )
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors, cfg=cfg)

        results = []
        output.subscribe(lambda ts, v: results.append(v))

        trigger.emit(wm, wm)
        self.assertIsNotNone(results[0])

        trigger.emit(wm + 1.0, wm + 1.0)
        self.assertIsNone(results[1])

        trigger.emit(wm + 6.0, wm + 6.0)
        self.assertIsNotNone(results[2])


# ── D: Boundaries ──────────────────────────────────────────────────────


class TestMCGovernanceBoundaries(unittest.TestCase):
    """Dimension D: edge-case inputs."""

    def test_all_zero_behaviors_vetoed(self):
        """All behaviors at zero → energy_sufficient veto."""
        wm = 100.0
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.0, arousal=0.0, vad=0.0, watermark=wm)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_MC)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNone(results[0])

    def test_max_energy_max_arousal_selects_vocal_throw(self):
        wm = 100.0
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=1.0, arousal=1.0, vad=0.0, watermark=wm)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_MC)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNotNone(results[0])
        self.assertEqual(results[0].command.action, "vocal_throw")

    def test_energy_at_exact_ad_lib_threshold(self):
        """Energy=0.3, arousal=0.3 at exact ad_lib threshold → ad_lib."""
        wm = 100.0
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.3, arousal=0.3, vad=0.0, watermark=wm)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_MC)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNotNone(results[0])
        self.assertEqual(results[0].command.action, "ad_lib")

    def test_vad_at_exact_threshold_blocks(self):
        """VAD=0.5 at speech_clear threshold → blocked (predicate is <, not <=)."""
        wm = 100.0
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7, vad=0.5, watermark=wm)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_MC)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNone(results[0])

    def test_vad_just_below_threshold_allows(self):
        wm = 100.0
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7, vad=0.499, watermark=wm)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_MC)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNotNone(results[0])

    def test_full_suppression_blocks_marginal_energy(self):
        """Suppression=1.0 raises effective threshold to 1.0, blocking energy=0.5."""
        wm = 100.0
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.5, arousal=0.5, vad=0.0, suppression=1.0, watermark=wm)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_MC)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNone(results[0])

    def test_energy_below_min_vetoed(self):
        """Energy 0.29 < 0.3 threshold → energy_sufficient veto."""
        wm = 100.0
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.29, arousal=0.29, vad=0.0, watermark=wm)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_MC)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNone(results[0])

    def test_stale_behaviors_rejected(self):
        """Behaviors with old watermark → freshness veto (default config)."""
        wm = 1.0
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7, watermark=wm)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)

        results = []
        output.subscribe(lambda ts, v: results.append(v))
        now = time.monotonic()
        trigger.emit(now, now)
        self.assertIsNone(results[0])


class TestOBSGovernanceBoundaries(unittest.TestCase):
    """Dimension D: edge-case inputs."""

    def test_all_zero_behaviors_selects_wide_ambient(self):
        """Zero energy/arousal → wide_ambient (default fallback)."""
        wm = 100.0
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.0, arousal=0.0, watermark=wm)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_OBS)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNotNone(results[0])
        self.assertEqual(results[0].action, "wide_ambient")

    def test_max_energy_max_arousal_selects_rapid_cut(self):
        wm = 100.0
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=1.0, arousal=1.0, watermark=wm)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_OBS)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNotNone(results[0])
        self.assertEqual(results[0].action, "rapid_cut")

    def test_low_bitrate_blocks(self):
        wm = 100.0
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.5, bitrate=100.0, watermark=wm)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_OBS)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNone(results[0])

    def test_high_encoding_lag_blocks(self):
        wm = 100.0
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.5, encoding_lag=200.0, watermark=wm)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_OBS)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNone(results[0])

    def test_mc_bias_face_cam_with_recent_fire(self):
        """MC fired recently + moderate energy → face_cam via mc_bias candidate."""
        wm = 100.0
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.3, last_mc_fire=wm - 1.0, watermark=wm)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_OBS)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNotNone(results[0])
        self.assertEqual(results[0].action, "face_cam")

    def test_no_mc_fire_behavior_falls_to_normal_selection(self):
        """No last_mc_fire → no mc bias; energy=0.5, arousal=0.3 → gear_closeup."""
        wm = 100.0
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.3, watermark=wm)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors, cfg=_LENIENT_OBS)
        results = _fire_once(trigger, output, timestamp=wm)
        self.assertIsNotNone(results[0])
        self.assertEqual(results[0].action, "gear_closeup")

    def test_stale_behaviors_rejected(self):
        wm = 1.0
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.5, watermark=wm)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors)

        results = []
        output.subscribe(lambda ts, v: results.append(v))
        now = time.monotonic()
        trigger.emit(now, now)
        self.assertIsNone(results[0])


# ── B+D: Transition Selection ──────────────────────────────────────────


class TestTransitionSelection(unittest.TestCase):
    """Boundary tests for select_transition."""

    def test_high_energy_selects_cut(self):
        from agents.hapax_voice.governance import FusedContext
        from agents.hapax_voice.primitives import Stamped

        ctx = FusedContext(
            trigger_time=1.0,
            trigger_value=None,
            samples={"audio_energy_rms": Stamped(value=0.8, watermark=1.0)},
        )
        self.assertEqual(select_transition(ctx), OBSTransition.CUT)

    def test_low_energy_selects_dissolve(self):
        from agents.hapax_voice.governance import FusedContext
        from agents.hapax_voice.primitives import Stamped

        ctx = FusedContext(
            trigger_time=1.0,
            trigger_value=None,
            samples={"audio_energy_rms": Stamped(value=0.3, watermark=1.0)},
        )
        self.assertEqual(select_transition(ctx), OBSTransition.DISSOLVE)

    def test_exact_threshold_selects_cut(self):
        from agents.hapax_voice.governance import FusedContext
        from agents.hapax_voice.primitives import Stamped

        ctx = FusedContext(
            trigger_time=1.0,
            trigger_value=None,
            samples={"audio_energy_rms": Stamped(value=0.6, watermark=1.0)},
        )
        self.assertEqual(select_transition(ctx), OBSTransition.CUT)


# ── G: Composition Contracts ───────────────────────────────────────────


class TestGovernanceCompositionContracts(unittest.TestCase):
    """Dimension G: output of L7 is valid input to L6 (arbiter/executor)."""

    def test_mc_schedule_command_dispatchable(self):
        """MC output Schedule.command has valid MC action."""
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        cmd = results[0].command
        self.assertIn(cmd.action, {"vocal_throw", "ad_lib", "silence"})
        self.assertTrue(cmd.governance_result.allowed)

    def test_obs_command_has_resource_mappable_action(self):
        """OBS output Command.action is in RESOURCE_MAP (except hold)."""
        from agents.hapax_voice.resource_config import RESOURCE_MAP

        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.5)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        action = results[0].action
        if action != "hold":
            self.assertIn(action, RESOURCE_MAP)

    def test_mc_schedule_wall_time_in_future(self):
        """MC schedules 4 beats ahead → wall_time > trigger time."""
        trigger = Event[float]()
        behaviors = _mc_behaviors(energy=0.8, arousal=0.7)
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        schedule = results[0]
        self.assertGreater(schedule.wall_time, schedule.command.trigger_time)

    def test_obs_command_governance_result_is_allowed(self):
        """Non-vetoed OBS command carries allowed=True governance_result."""
        trigger = Event[float]()
        behaviors = _obs_behaviors(energy=0.5, arousal=0.5)
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors)
        results = _fire_once(trigger, output)
        self.assertTrue(results[0].governance_result.allowed)
        self.assertEqual(results[0].governance_result.denied_by, ())


if __name__ == "__main__":
    unittest.main()
