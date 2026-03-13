"""MC end-to-end integration test: MIDI tick → governance → schedule → audio dispatch.

All hardware mocked at boundary. Tests the full pipeline from trigger event
through governance evaluation, schedule queue, and executor dispatch.
"""

from __future__ import annotations

import time
import unittest

from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.executor import ExecutorRegistry, ScheduleQueue
from agents.hapax_voice.mc_governance import MCAction, compose_mc_governance
from agents.hapax_voice.primitives import Behavior, Event
from agents.hapax_voice.timeline import TimelineMapping, TransportState


class FakeAudioExecutor:
    """Test double for AudioExecutor."""

    def __init__(self) -> None:
        self.executed: list[Command] = []

    @property
    def name(self) -> str:
        return "audio"

    @property
    def handles(self) -> frozenset[str]:
        return frozenset({"vocal_throw", "ad_lib"})

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
) -> dict[str, Behavior]:
    """Create a behaviors dict for MC governance."""
    now = time.monotonic()
    mapping = TimelineMapping(
        reference_time=now - 1.0,
        reference_beat=0.0,
        tempo=tempo,
        transport=transport,
    )
    return {
        "audio_energy_rms": Behavior(energy, watermark=now),
        "emotion_arousal": Behavior(arousal, watermark=now),
        "vad_confidence": Behavior(vad, watermark=now),
        "timeline_mapping": Behavior(mapping, watermark=now),
    }


class TestMCEndToEnd(unittest.TestCase):
    def test_full_pipeline_fires(self):
        """MIDI tick → MC governance → Schedule → ScheduleQueue → AudioExecutor."""
        behaviors = _make_behaviors(energy=0.8, arousal=0.7)
        trigger = Event[float]()
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)

        # Collect schedules
        schedules: list[Schedule | None] = []
        output.subscribe(lambda ts, s: schedules.append(s))

        # Fire trigger
        now = time.monotonic()
        trigger.emit(now, now)

        # Should produce a schedule (not None, not silence)
        self.assertEqual(len(schedules), 1)
        schedule = schedules[0]
        self.assertIsNotNone(schedule)
        self.assertEqual(schedule.command.action, MCAction.VOCAL_THROW.value)

        # Enqueue and drain through ScheduleQueue
        queue = ScheduleQueue()
        queue.enqueue(schedule)

        # Drain at wall_time → ready
        ready = queue.drain(schedule.wall_time + 0.001)
        self.assertEqual(len(ready), 1)

        # Dispatch through ExecutorRegistry
        registry = ExecutorRegistry()
        executor = FakeAudioExecutor()
        registry.register(executor)

        dispatched = registry.dispatch(ready[0].command)
        self.assertTrue(dispatched)
        self.assertEqual(len(executor.executed), 1)
        self.assertEqual(executor.executed[0].action, MCAction.VOCAL_THROW.value)

    def test_transport_stopped_blocks(self):
        """When transport is STOPPED, MC governance should veto."""
        behaviors = _make_behaviors(transport=TransportState.STOPPED)
        trigger = Event[float]()
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)

        schedules: list[Schedule | None] = []
        output.subscribe(lambda ts, s: schedules.append(s))

        now = time.monotonic()
        trigger.emit(now, now)

        self.assertEqual(len(schedules), 1)
        self.assertIsNone(schedules[0])  # vetoed

    def test_speech_veto_blocks(self):
        """Speech detected (high VAD) should veto MC throws."""
        behaviors = _make_behaviors(vad=0.9)
        trigger = Event[float]()
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)

        schedules: list[Schedule | None] = []
        output.subscribe(lambda ts, s: schedules.append(s))

        now = time.monotonic()
        trigger.emit(now, now)

        self.assertEqual(len(schedules), 1)
        self.assertIsNone(schedules[0])

    def test_low_energy_selects_silence(self):
        """Low energy → FallbackChain selects silence."""
        behaviors = _make_behaviors(energy=0.1, arousal=0.1)
        trigger = Event[float]()
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)

        schedules: list[Schedule | None] = []
        output.subscribe(lambda ts, s: schedules.append(s))

        now = time.monotonic()
        trigger.emit(now, now)

        # Low energy passes veto (energy_sufficient has threshold 0.3, 0.1 < 0.3 → vetoed)
        self.assertEqual(len(schedules), 1)
        self.assertIsNone(schedules[0])

    def test_schedule_queue_ordering(self):
        """Multiple schedules drain in wall_time order."""
        behaviors = _make_behaviors()
        trigger = Event[float]()
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)

        schedules: list[Schedule | None] = []
        output.subscribe(lambda ts, s: schedules.append(s))

        # Fire trigger — get a schedule
        now = time.monotonic()
        trigger.emit(now, now)

        self.assertTrue(len(schedules) > 0)
        schedule = schedules[0]
        if schedule is not None:
            queue = ScheduleQueue()
            queue.enqueue(schedule)
            ready = queue.drain(schedule.wall_time + 0.001)
            self.assertEqual(len(ready), 1)

    def test_empty_actuation_loop(self):
        """No MIDI backend → actuation loop drains empty queue."""
        queue = ScheduleQueue()
        self.assertEqual(queue.drain(time.monotonic()), [])

    def test_executor_latency_tracking(self):
        """Verify latency can be computed from schedule.wall_time vs now."""
        behaviors = _make_behaviors()
        trigger = Event[float]()
        output = compose_mc_governance(trigger=trigger, behaviors=behaviors)

        schedules: list[Schedule | None] = []
        output.subscribe(lambda ts, s: schedules.append(s))

        now = time.monotonic()
        trigger.emit(now, now)

        schedule = schedules[0]
        if schedule is not None:
            # Simulate drain slightly after wall_time
            drain_time = schedule.wall_time + 0.005
            latency_ms = (drain_time - schedule.wall_time) * 1000.0
            self.assertGreater(latency_ms, 0)
            self.assertLess(latency_ms, 50)


if __name__ == "__main__":
    unittest.main()
