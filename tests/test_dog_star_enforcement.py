"""Tests for Dog Star enforcement gap closures.

Validates that forbidden type sequences from the Dog Star spec are now
properly blocked by runtime enforcement.

Self-contained, unittest.mock only, asyncio_mode="auto".
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agents.hapax_daimonion.commands import Command
from agents.hapax_daimonion.governance import VetoResult
from agents.hapax_daimonion.primitives import Behavior, Event

# ── D1.1: Denied Command Cannot Dispatch ───────────────────────────────


class TestD1_1_GovernanceDenialBlocks(unittest.TestCase):
    """dispatch() must refuse commands with governance_result.allowed=False."""

    def test_denied_command_returns_false(self):
        from agents.hapax_daimonion.executor import ExecutorRegistry

        reg = ExecutorRegistry()
        ex = _fake_executor("audio", frozenset({"vocal_throw"}))
        reg.register(ex)
        cmd = Command(
            action="vocal_throw",
            governance_result=VetoResult(allowed=False, denied_by=("speech_clear",)),
        )
        self.assertFalse(reg.dispatch(cmd))
        self.assertEqual(len(ex.executed), 0)

    def test_allowed_command_dispatches(self):
        from agents.hapax_daimonion.executor import ExecutorRegistry

        reg = ExecutorRegistry()
        ex = _fake_executor("audio", frozenset({"vocal_throw"}))
        reg.register(ex)
        cmd = Command(
            action="vocal_throw",
            governance_result=VetoResult(allowed=True),
        )
        self.assertTrue(reg.dispatch(cmd))
        self.assertEqual(len(ex.executed), 1)


# ── D4.2: OBS Commands Route Through Arbiter ──────────────────────────


class TestD4_2_OBSArbiterWiring(unittest.TestCase):
    """OBS governance output must go through ResourceArbiter, not dispatch directly."""

    def test_resource_config_has_obs_governance_chain(self):
        """Priority map uses 'obs_governance' matching OBS Command.trigger_source."""
        from agents.hapax_daimonion.resource_config import DEFAULT_PRIORITIES

        self.assertIn(("obs_scene", "obs_governance"), DEFAULT_PRIORITIES)
        self.assertEqual(DEFAULT_PRIORITIES[("obs_scene", "obs_governance")], 70)

    def test_resource_config_has_mc_governance_chain(self):
        """Priority map uses 'mc_governance' matching MC Command.trigger_source."""
        from agents.hapax_daimonion.resource_config import DEFAULT_PRIORITIES

        self.assertIn(("audio_output", "mc_governance"), DEFAULT_PRIORITIES)
        self.assertEqual(DEFAULT_PRIORITIES[("audio_output", "mc_governance")], 50)

    def test_obs_actions_mapped_to_obs_scene(self):
        """All OBS actions route to the obs_scene resource."""
        from agents.hapax_daimonion.resource_config import RESOURCE_MAP

        obs_actions = ["wide_ambient", "gear_closeup", "face_cam", "rapid_cut"]
        for action in obs_actions:
            self.assertEqual(RESOURCE_MAP[action], "obs_scene", f"{action} not mapped")

    def test_obs_priority_beats_mc_on_obs_scene(self):
        """OBS governance has higher priority than MC on obs_scene resource."""
        from agents.hapax_daimonion.resource_config import DEFAULT_PRIORITIES

        obs_priority = DEFAULT_PRIORITIES[("obs_scene", "obs_governance")]
        mc_priority = DEFAULT_PRIORITIES[("obs_scene", "mc_governance")]
        self.assertGreater(obs_priority, mc_priority)

    def test_arbiter_resolves_obs_over_mc_for_obs_scene(self):
        """When both OBS and MC claim obs_scene, OBS wins (priority 70 > 40)."""
        from agents.hapax_daimonion.arbiter import ResourceArbiter, ResourceClaim
        from agents.hapax_daimonion.resource_config import DEFAULT_PRIORITIES

        arb = ResourceArbiter(DEFAULT_PRIORITIES)
        mc_cmd = Command(action="face_cam", trigger_source="mc_governance")
        obs_cmd = Command(action="face_cam", trigger_source="obs_governance")

        arb.claim(
            ResourceClaim(
                resource="obs_scene",
                chain="mc_governance",
                priority=DEFAULT_PRIORITIES[("obs_scene", "mc_governance")],
                command=mc_cmd,
                created_at=1.0,
            )
        )
        arb.claim(
            ResourceClaim(
                resource="obs_scene",
                chain="obs_governance",
                priority=DEFAULT_PRIORITIES[("obs_scene", "obs_governance")],
                command=obs_cmd,
                created_at=2.0,
            )
        )
        winners = arb.drain_winners(now=3.0)
        obs_winner = [w for w in winners if w.resource == "obs_scene"]
        self.assertEqual(len(obs_winner), 1)
        self.assertEqual(obs_winner[0].chain, "obs_governance")


# ── D5.2: Backend Writes Scoped to Declared Provides ──────────────────


class TestD5_2_ScopedBackendWrites(unittest.TestCase):
    """PerceptionBackend.contribute() must receive only its declared behaviors."""

    def test_backend_receives_scoped_dict(self):
        """contribute() gets only the behaviors in its provides set."""
        from agents.hapax_daimonion.perception import PerceptionEngine

        presence = MagicMock()
        presence.latest_vad_confidence = 0.0
        presence.face_detected = False
        presence.face_count = 0
        presence.score = "likely_absent"
        workspace = MagicMock()
        workspace.classify = MagicMock(return_value=("unknown", ""))

        engine = PerceptionEngine(presence=presence, workspace_monitor=workspace)

        # Create a backend that declares only "test_signal"
        backend = MagicMock()
        backend.name = "test_backend"
        backend.provides = frozenset({"test_signal"})
        backend.tier = MagicMock()
        backend.available = MagicMock(return_value=True)

        # Add the test_signal behavior to the engine
        test_behavior = Behavior(0.0, watermark=0.0)
        engine.behaviors["test_signal"] = test_behavior

        engine.register_backend(backend)

        # Tick should call contribute with only test_signal
        engine.tick()
        backend.contribute.assert_called_once()
        contributed_dict = backend.contribute.call_args[0][0]
        self.assertEqual(set(contributed_dict.keys()), {"test_signal"})
        self.assertNotIn("vad_confidence", contributed_dict)

    def test_backend_cannot_write_undeclared_behavior(self):
        """A rogue backend trying to access undeclared behaviors gets a filtered dict."""
        from agents.hapax_daimonion.perception import PerceptionEngine

        presence = MagicMock()
        presence.latest_vad_confidence = 0.5
        presence.face_detected = True
        presence.face_count = 1
        presence.score = "likely_present"
        workspace = MagicMock()
        workspace.classify = MagicMock(return_value=("unknown", ""))

        engine = PerceptionEngine(presence=presence, workspace_monitor=workspace)

        # Backend declares only "rogue_signal" but tries to write vad_confidence
        rogue_backend = MagicMock()
        rogue_backend.name = "rogue"
        rogue_backend.provides = frozenset({"rogue_signal"})
        rogue_backend.tier = MagicMock()
        rogue_backend.available = MagicMock(return_value=True)

        engine.behaviors["rogue_signal"] = Behavior(0.0, watermark=0.0)

        def rogue_contribute(behaviors):
            # Try to access vad_confidence — should not be in the dict
            assert "vad_confidence" not in behaviors

        rogue_backend.contribute = rogue_contribute
        engine.register_backend(rogue_backend)

        # Should not raise
        engine.tick()


# ── D6.3: Behavior Key Validation at Composition Time ─────────────────


class TestD6_3_CompositionTimeValidation(unittest.TestCase):
    """compose_*_governance() must raise ValueError for missing behaviors."""

    def test_mc_governance_rejects_empty_behaviors(self):
        from agents.hapax_daimonion.mc_governance import compose_mc_governance

        trigger = Event[float]()
        with self.assertRaises(ValueError) as ctx:
            compose_mc_governance(trigger=trigger, behaviors={})
        self.assertIn("missing required behaviors", str(ctx.exception).lower())

    def test_mc_governance_rejects_partial_behaviors(self):
        from agents.hapax_daimonion.mc_governance import compose_mc_governance

        trigger = Event[float]()
        partial = {"audio_energy_rms": Behavior(0.0, watermark=0.0)}
        with self.assertRaises(ValueError) as ctx:
            compose_mc_governance(trigger=trigger, behaviors=partial)
        self.assertIn("missing required behaviors", str(ctx.exception).lower())

    def test_mc_governance_accepts_complete_behaviors(self):
        from agents.hapax_daimonion.mc_governance import compose_mc_governance

        trigger = Event[float]()
        behaviors = _full_mc_behaviors()
        # Should not raise
        result = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        self.assertIsNotNone(result)

    def test_obs_governance_rejects_empty_behaviors(self):
        from agents.hapax_daimonion.obs_governance import compose_obs_governance

        trigger = Event[float]()
        with self.assertRaises(ValueError) as ctx:
            compose_obs_governance(trigger=trigger, behaviors={})
        self.assertIn("missing required behaviors", str(ctx.exception).lower())

    def test_obs_governance_accepts_complete_behaviors(self):
        from agents.hapax_daimonion.obs_governance import compose_obs_governance

        trigger = Event[float]()
        behaviors = _full_obs_behaviors()
        # Should not raise
        result = compose_obs_governance(trigger=trigger, behaviors=behaviors)
        self.assertIsNotNone(result)


# ── L1: Behavior Watermark Regression (D3) ────────────────────────────


class TestL1_D3_WatermarkRegression(unittest.TestCase):
    """Behavior.update() must reject regressing timestamps — forbidden sequence D3."""

    def test_regression_raises_value_error(self):
        """Updating with an older timestamp than current watermark is forbidden."""
        b = Behavior(0.0, watermark=10.0)
        with self.assertRaises(ValueError) as ctx:
            b.update(1.0, timestamp=5.0)
        self.assertIn("regression", str(ctx.exception).lower())
        # Value must not have changed
        self.assertEqual(b.value, 0.0)
        self.assertEqual(b.watermark, 10.0)

    def test_equal_timestamp_allowed(self):
        """Updating with the same timestamp is not a regression."""
        b = Behavior(0.0, watermark=10.0)
        b.update(1.0, timestamp=10.0)
        self.assertEqual(b.value, 1.0)

    def test_event_subscriber_exception_isolated(self):
        """A failing subscriber must not prevent other subscribers from receiving."""
        e = Event[int]()
        received = []

        def bad_sub(ts: float, val: int) -> None:
            raise RuntimeError("boom")

        def good_sub(ts: float, val: int) -> None:
            received.append(val)

        e.subscribe(bad_sub)
        e.subscribe(good_sub)
        e.emit(1.0, 42)
        self.assertEqual(received, [42])


# ── L3: Combinator Watermark Fidelity (D2) ───────────────────────────


class TestL3_D2_CombinatorWatermarkFidelity(unittest.TestCase):
    """with_latest_from must propagate watermarks faithfully — no phantom freshness."""

    def test_min_watermark_reflects_stalest_behavior(self):
        """FusedContext.min_watermark must equal the oldest behavior watermark."""
        from agents.hapax_daimonion.combinator import with_latest_from

        trigger = Event[float]()
        b_fresh = Behavior(1.0, watermark=100.0)
        b_stale = Behavior(2.0, watermark=50.0)
        behaviors = {"fresh": b_fresh, "stale": b_stale}

        fused_output = with_latest_from(trigger, behaviors)
        results = []
        fused_output.subscribe(lambda ts, ctx: results.append(ctx))

        trigger.emit(200.0, None)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].min_watermark, 50.0)

    def test_empty_behaviors_uses_trigger_time(self):
        """With no behaviors, min_watermark falls back to trigger timestamp."""
        from agents.hapax_daimonion.combinator import with_latest_from

        trigger = Event[float]()
        fused_output = with_latest_from(trigger, {})
        results = []
        fused_output.subscribe(lambda ts, ctx: results.append(ctx))

        trigger.emit(99.0, None)
        self.assertEqual(results[0].min_watermark, 99.0)

    def test_output_timestamp_matches_trigger(self):
        """Combinator must not fabricate timestamps — output matches trigger exactly."""
        from agents.hapax_daimonion.combinator import with_latest_from

        trigger = Event[float]()
        b = Behavior(0.0, watermark=1.0)
        fused_output = with_latest_from(trigger, {"x": b})
        timestamps = []
        fused_output.subscribe(lambda ts, ctx: timestamps.append(ts))

        trigger.emit(42.5, None)
        self.assertEqual(timestamps, [42.5])

    def test_no_emission_without_trigger(self):
        """Combinator must not emit spontaneously — only on trigger."""
        from agents.hapax_daimonion.combinator import with_latest_from

        trigger = Event[float]()
        b = Behavior(0.0, watermark=1.0)
        fused_output = with_latest_from(trigger, {"x": b})
        results = []
        fused_output.subscribe(lambda ts, ctx: results.append(ctx))

        # Update behavior but don't trigger
        b.update(99.0, 2.0)
        self.assertEqual(len(results), 0)


# ── L5: Timeline/Suppression Invalid State Rejection ─────────────────


class TestL5_TimelineSuppressionDogStar(unittest.TestCase):
    """Timeline and Suppression must reject invalid configurations."""

    def test_timeline_rejects_zero_tempo(self):
        """TimelineMapping with tempo=0 is a forbidden construction."""
        from agents.hapax_daimonion.timeline import TimelineMapping

        with self.assertRaises(ValueError):
            TimelineMapping(reference_time=0.0, reference_beat=0.0, tempo=0.0)

    def test_timeline_rejects_negative_tempo(self):
        """TimelineMapping with negative tempo is forbidden."""
        from agents.hapax_daimonion.timeline import TimelineMapping

        with self.assertRaises(ValueError):
            TimelineMapping(reference_time=0.0, reference_beat=0.0, tempo=-120.0)

    def test_stopped_transport_freezes_beat(self):
        """STOPPED transport must return reference_beat regardless of time — prevents stale scheduling."""
        from agents.hapax_daimonion.timeline import TimelineMapping, TransportState

        m = TimelineMapping(
            reference_time=0.0,
            reference_beat=0.0,
            tempo=120.0,
            transport=TransportState.STOPPED,
        )
        # Even at time=1000, beat stays at 0
        self.assertEqual(m.beat_at_time(1000.0), 0.0)
        # And time_at_beat returns reference_time
        self.assertEqual(m.time_at_beat(100.0), 0.0)

    def test_suppression_rejects_zero_attack(self):
        """SuppressionField with attack_s=0 is forbidden (division by zero)."""
        from agents.hapax_daimonion.suppression import SuppressionField

        with self.assertRaises(ValueError):
            SuppressionField(attack_s=0.0)

    def test_suppression_rejects_negative_release(self):
        """SuppressionField with negative release_s is forbidden."""
        from agents.hapax_daimonion.suppression import SuppressionField

        with self.assertRaises(ValueError):
            SuppressionField(release_s=-1.0)

    def test_full_suppression_makes_threshold_unreachable(self):
        """At suppression=1.0, effective_threshold must be 1.0 (impossible to exceed)."""
        from agents.hapax_daimonion.suppression import effective_threshold

        for base in [0.0, 0.3, 0.5, 0.7, 0.99]:
            self.assertEqual(
                effective_threshold(base, 1.0),
                1.0,
                f"base={base}: full suppression must yield threshold=1.0",
            )


# ── L9: Daemon Actuation Pipeline Dog Star ────────────────────────────


class TestL9_DaemonActuationDogStar(unittest.TestCase):
    """Daemon-level: denied commands must not reach executors through the actuation path."""

    def test_denied_schedule_not_dispatched_through_queue(self):
        """A Schedule whose Command has allowed=False must not trigger execute()."""
        from agents.hapax_daimonion.commands import Schedule
        from agents.hapax_daimonion.executor import ExecutorRegistry, ScheduleQueue

        queue = ScheduleQueue()
        registry = ExecutorRegistry()
        ex = _FakeExecutor("audio", frozenset({"vocal_throw"}))
        registry.register(ex)

        # Create a denied schedule
        denied_cmd = Command(
            action="vocal_throw",
            governance_result=VetoResult(allowed=False, denied_by=("speech_clear",)),
            trigger_source="mc_governance",
        )
        schedule = Schedule(
            command=denied_cmd,
            domain="beat",
            target_time=4.0,
            wall_time=10.0,
            tolerance_ms=1000,  # 1s window for test clarity
        )
        queue.enqueue(schedule)

        # Drain and dispatch — mirrors _actuation_loop logic
        ready = queue.drain(now=10.5)
        self.assertEqual(len(ready), 1)
        dispatched = registry.dispatch(ready[0].command, schedule=ready[0])
        self.assertFalse(dispatched)
        self.assertEqual(len(ex.executed), 0)

    def test_allowed_schedule_dispatches_through_queue(self):
        """A Schedule whose Command has allowed=True must reach the executor."""
        from agents.hapax_daimonion.commands import Schedule
        from agents.hapax_daimonion.executor import ExecutorRegistry, ScheduleQueue

        queue = ScheduleQueue()
        registry = ExecutorRegistry()
        ex = _FakeExecutor("audio", frozenset({"vocal_throw"}))
        registry.register(ex)

        allowed_cmd = Command(
            action="vocal_throw",
            governance_result=VetoResult(allowed=True),
            trigger_source="mc_governance",
        )
        schedule = Schedule(
            command=allowed_cmd,
            domain="beat",
            target_time=4.0,
            wall_time=10.0,
            tolerance_ms=1000,
        )
        queue.enqueue(schedule)

        ready = queue.drain(now=10.5)
        dispatched = registry.dispatch(ready[0].command, schedule=ready[0])
        self.assertTrue(dispatched)
        self.assertEqual(len(ex.executed), 1)

    def test_expired_schedule_never_reaches_executor(self):
        """A Schedule past its tolerance window must be silently dropped."""
        from agents.hapax_daimonion.commands import Schedule
        from agents.hapax_daimonion.executor import ExecutorRegistry, ScheduleQueue

        queue = ScheduleQueue()
        registry = ExecutorRegistry()
        ex = _FakeExecutor("audio", frozenset({"vocal_throw"}))
        registry.register(ex)

        cmd = Command(
            action="vocal_throw",
            governance_result=VetoResult(allowed=True),
            trigger_source="mc_governance",
        )
        schedule = Schedule(
            command=cmd,
            domain="beat",
            target_time=4.0,
            wall_time=10.0,
            tolerance_ms=100,  # 100ms window
        )
        queue.enqueue(schedule)

        # Drain way past tolerance
        ready = queue.drain(now=20.0)
        self.assertEqual(len(ready), 0)
        self.assertEqual(len(ex.executed), 0)


# ── Helpers ────────────────────────────────────────────────────────────


class _FakeExecutor:
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


def _fake_executor(name: str, handles: frozenset[str]) -> _FakeExecutor:
    return _FakeExecutor(name, handles)


def _full_mc_behaviors() -> dict[str, Behavior]:
    from agents.hapax_daimonion.timeline import TimelineMapping, TransportState

    return {
        "audio_energy_rms": Behavior(0.5, watermark=0.0),
        "emotion_arousal": Behavior(0.5, watermark=0.0),
        "vad_confidence": Behavior(0.0, watermark=0.0),
        "timeline_mapping": Behavior(
            TimelineMapping(
                reference_time=0.0,
                reference_beat=0.0,
                tempo=120.0,
                transport=TransportState.PLAYING,
            ),
            watermark=0.0,
        ),
        "conversation_suppression": Behavior(0.0, watermark=0.0),
    }


def _full_obs_behaviors() -> dict[str, Behavior]:
    from agents.hapax_daimonion.timeline import TimelineMapping, TransportState

    return {
        "audio_energy_rms": Behavior(0.5, watermark=0.0),
        "emotion_arousal": Behavior(0.5, watermark=0.0),
        "timeline_mapping": Behavior(
            TimelineMapping(
                reference_time=0.0,
                reference_beat=0.0,
                tempo=120.0,
                transport=TransportState.PLAYING,
            ),
            watermark=0.0,
        ),
        "stream_bitrate": Behavior(5000.0, watermark=0.0),
        "stream_encoding_lag": Behavior(10.0, watermark=0.0),
        "last_mc_fire": Behavior(0.0, watermark=0.0),
    }


if __name__ == "__main__":
    unittest.main()
