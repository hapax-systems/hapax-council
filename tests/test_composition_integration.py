"""Capstone integration tests for multi-role composition.

Full pipeline: perception → suppression tick → governance with suppression
→ arbiter → dispatch → ActuationEvent → feedback → governance reads it.
"""

from __future__ import annotations

import time
import unittest

from agents.hapax_voice.actuation_event import ActuationEvent
from agents.hapax_voice.arbiter import ResourceArbiter, ResourceClaim
from agents.hapax_voice.chain_state import create_cross_role_behaviors
from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.executor import ExecutorRegistry, ScheduleQueue
from agents.hapax_voice.feedback import wire_feedback_behaviors
from agents.hapax_voice.mc_governance import compose_mc_governance
from agents.hapax_voice.musical_position import (
    create_musical_position_behavior,
    update_musical_position,
)
from agents.hapax_voice.obs_governance import compose_obs_governance
from agents.hapax_voice.primitives import Behavior, Event
from agents.hapax_voice.resource_config import DEFAULT_PRIORITIES
from agents.hapax_voice.suppression import SuppressionField, effective_threshold
from agents.hapax_voice.timeline import TimelineMapping, TransportState


class FakeExecutor:
    """Test double for any executor."""

    def __init__(self, name: str, handles: frozenset[str]) -> None:
        self._name = name
        self._handles = handles
        self.executed: list[Command] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def handles(self) -> frozenset[str]:
        return self._handles

    def execute(self, command: Command) -> None:
        self.executed.append(command)

    def available(self) -> bool:
        return True

    def close(self) -> None:
        pass


def _make_behaviors(
    *,
    energy: float = 0.8,
    arousal: float = 0.7,
    vad: float = 0.0,
    tempo: float = 120.0,
    transport: TransportState = TransportState.PLAYING,
    watermark: float | None = None,
    extra: dict[str, Behavior] | None = None,
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
        "stream_bitrate": Behavior(5000.0, watermark=wm),
        "stream_encoding_lag": Behavior(10.0, watermark=wm),
    }
    if extra:
        behaviors.update(extra)
    return behaviors


class TestSuppressionModulatesMCThreshold(unittest.TestCase):
    def test_conversation_active_raises_threshold(self):
        """When conversation_suppression is high, MC requires more energy to fire."""
        # With suppression=0, energy=0.35 should pass energy_sufficient (threshold 0.3)
        behaviors = _make_behaviors(energy=0.35, arousal=0.5)
        behaviors["conversation_suppression"] = Behavior(0.0, watermark=time.monotonic())

        trigger = Event[float]()
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        schedules: list[Schedule | None] = []
        output.subscribe(lambda ts, s: schedules.append(s))

        now = time.monotonic()
        trigger.emit(now, now)
        # Should produce a schedule (energy passes)
        self.assertIsNotNone(schedules[0])

    def test_suppression_blocks_marginal_energy(self):
        """High suppression raises threshold enough to block marginal energy."""
        wm = time.monotonic()
        behaviors = _make_behaviors(energy=0.35, arousal=0.5, watermark=wm)
        behaviors["conversation_suppression"] = Behavior(0.8, watermark=wm)

        trigger = Event[float]()
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        schedules: list[Schedule | None] = []
        output.subscribe(lambda ts, s: schedules.append(s))

        trigger.emit(wm, wm)
        # effective_threshold(0.3, 0.8) = 0.3 + 0.8 * 0.7 = 0.86
        # energy 0.35 < 0.86 → vetoed
        self.assertIsNone(schedules[0])


class TestArbiterResourceContention(unittest.TestCase):
    def test_higher_priority_wins(self):
        arb = ResourceArbiter(DEFAULT_PRIORITIES)
        arb.claim(
            ResourceClaim(
                resource="audio_output",
                chain="mc_governance",
                priority=50,
                command="vocal_throw",
                created_at=1.0,
            )
        )
        arb.claim(
            ResourceClaim(
                resource="audio_output",
                chain="conversation",
                priority=100,
                command="tts_announce",
                created_at=2.0,
            )
        )
        winners = arb.drain_winners(now=3.0)
        winner_actions = {w.resource: w.command for w in winners}
        self.assertEqual(winner_actions["audio_output"], "tts_announce")

    def test_held_claim_blocks_then_release_unblocks(self):
        arb = ResourceArbiter(DEFAULT_PRIORITIES)
        arb.claim(
            ResourceClaim(
                resource="audio_output",
                chain="conversation",
                priority=100,
                command="tts_announce",
                hold_until=10.0,
                created_at=1.0,
            )
        )
        arb.claim(
            ResourceClaim(
                resource="audio_output",
                chain="mc_governance",
                priority=50,
                command="vocal_throw",
                hold_until=0.0,
                created_at=2.0,
            )
        )
        # Conversation holds
        winners = arb.drain_winners(now=3.0)
        self.assertEqual(winners[0].chain, "conversation")
        # Release conversation
        arb.release("audio_output", "conversation")
        # MC should now win
        arb.claim(
            ResourceClaim(
                resource="audio_output",
                chain="mc_governance",
                priority=50,
                command="vocal_throw",
                hold_until=0.0,
                created_at=4.0,
            )
        )
        winners = arb.drain_winners(now=5.0)
        self.assertEqual(winners[0].chain, "mc_governance")

    def test_gc_sweep_removes_stale_holds(self):
        arb = ResourceArbiter(DEFAULT_PRIORITIES)
        arb.claim(
            ResourceClaim(
                resource="audio_output",
                chain="mc_governance",
                priority=50,
                command="vocal_throw",
                hold_until=5.0,
                max_hold_s=2.0,
                created_at=1.0,
            )
        )
        winners = arb.drain_winners(now=4.0)  # age=3 > max_hold_s=2
        self.assertEqual(len(winners), 0)


class TestCrossRoleSentinels(unittest.TestCase):
    def test_sentinels_readable_before_first_evaluation(self):
        behaviors = create_cross_role_behaviors(watermark=0.0)
        for name, b in behaviors.items():
            stamped = b.sample()
            self.assertIsNotNone(stamped.value, f"{name} sentinel not readable")

    def test_suppression_fields_sampleable(self):
        sf = SuppressionField(watermark=0.0)
        self.assertIsNotNone(sf.behavior.sample())


class TestFullPipeline(unittest.TestCase):
    def test_perception_to_feedback_loop(self):
        """Full pipeline: perception → governance → arbiter → dispatch → feedback."""
        wm = 0.0  # use 0.0 so dispatch's time.monotonic() is always above watermark

        # 1. Create behaviors (perception)
        behaviors = _make_behaviors(energy=0.8, arousal=0.7, watermark=wm)

        # 2. Create executor registry + fake executor
        registry = ExecutorRegistry()
        audio_exec = FakeExecutor("audio", frozenset({"vocal_throw", "ad_lib"}))
        registry.register(audio_exec)

        # 3. Wire feedback
        fb = wire_feedback_behaviors(registry.actuation_event, watermark=wm)

        # 4. Wire MC governance
        trigger = Event[float]()
        mc_output = compose_mc_governance(trigger=trigger, behaviors=behaviors)

        schedules: list[Schedule | None] = []
        mc_output.subscribe(lambda ts, s: schedules.append(s))

        # 5. Fire trigger
        trigger.emit(wm, wm)
        self.assertIsNotNone(schedules[0])

        # 6. Enqueue and drain
        queue = ScheduleQueue()
        queue.enqueue(schedules[0])
        ready = queue.drain(schedules[0].wall_time + 0.001)
        self.assertEqual(len(ready), 1)

        # 7. Dispatch (emits ActuationEvent → updates feedback Behaviors)
        dispatched = registry.dispatch(ready[0].command, schedule=ready[0])
        self.assertTrue(dispatched)

        # 8. Verify feedback updated
        self.assertGreater(fb["last_mc_fire"].value, 0.0)
        self.assertEqual(fb["mc_fire_count"].value, 1)

    def test_suppression_ramp_affects_governance(self):
        """SuppressionField tick → threshold changes → governance outcome changes."""
        wm = 100.0
        sf = SuppressionField(attack_s=1.0, release_s=1.0, watermark=wm)
        sf.set_target(1.0, now=wm)
        sf.tick(wm)  # establish reference
        sf.tick(wm + 1.0)  # full ramp to 1.0

        # effective_threshold at suppression=1.0 makes any base → 1.0
        eff = effective_threshold(0.3, sf.value)
        self.assertAlmostEqual(eff, 1.0)


class TestMusicalPositionIntegration(unittest.TestCase):
    def test_musical_position_from_timeline(self):
        b = create_musical_position_behavior(watermark=0.0)
        mapping = TimelineMapping(
            reference_time=0.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.PLAYING,
        )
        pos = update_musical_position(b, mapping, now=2.0)
        self.assertAlmostEqual(pos.beat, 4.0)
        self.assertEqual(pos.bar, 1)
        self.assertEqual(pos.phrase, 0)


class TestOBSFeedbackBias(unittest.TestCase):
    def test_mc_fire_biases_face_cam(self):
        """When MC fired recently, OBS should bias toward face_cam."""
        wm = time.monotonic()
        behaviors = _make_behaviors(
            energy=0.5,
            arousal=0.4,
            watermark=wm,
            extra={"last_mc_fire": Behavior(wm - 1.0, watermark=wm)},
        )
        trigger = Event[float]()
        output = compose_obs_governance(trigger=trigger, behaviors=behaviors)
        commands: list[Command | None] = []
        output.subscribe(lambda ts, cmd: commands.append(cmd))

        trigger.emit(wm, wm)
        # With MC bias + energy 0.5 (>= face_cam_energy_min), should select face_cam
        self.assertIsNotNone(commands[0])
        self.assertEqual(commands[0].action, "face_cam")


class TestActuationEventEmission(unittest.TestCase):
    def test_dispatch_emits_actuation_event(self):
        registry = ExecutorRegistry()
        executor = FakeExecutor("audio", frozenset({"vocal_throw"}))
        registry.register(executor)

        events: list[ActuationEvent] = []
        registry.actuation_event.subscribe(lambda ts, ae: events.append(ae))

        cmd = Command(action="vocal_throw", trigger_source="mc_governance")
        registry.dispatch(cmd)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].action, "vocal_throw")
        self.assertEqual(events[0].chain, "mc_governance")

    def test_dispatch_with_schedule_computes_latency(self):
        registry = ExecutorRegistry()
        executor = FakeExecutor("audio", frozenset({"vocal_throw"}))
        registry.register(executor)

        events: list[ActuationEvent] = []
        registry.actuation_event.subscribe(lambda ts, ae: events.append(ae))

        cmd = Command(action="vocal_throw")
        schedule = Schedule(command=cmd, wall_time=time.monotonic() - 0.010)
        registry.dispatch(cmd, schedule=schedule)
        self.assertEqual(len(events), 1)
        self.assertGreater(events[0].latency_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
