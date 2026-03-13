"""Tests for Dog Star enforcement gap closures.

Validates that forbidden type sequences from the Dog Star spec are now
properly blocked by runtime enforcement.

Self-contained, unittest.mock only, asyncio_mode="auto".
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from agents.hapax_voice.commands import Command
from agents.hapax_voice.governance import VetoResult
from agents.hapax_voice.primitives import Behavior, Event

# ── D1.1: Denied Command Cannot Dispatch ───────────────────────────────


class TestD1_1_GovernanceDenialBlocks(unittest.TestCase):
    """dispatch() must refuse commands with governance_result.allowed=False."""

    def test_denied_command_returns_false(self):
        from agents.hapax_voice.executor import ExecutorRegistry

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
        from agents.hapax_voice.executor import ExecutorRegistry

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
        from agents.hapax_voice.resource_config import DEFAULT_PRIORITIES

        self.assertIn(("obs_scene", "obs_governance"), DEFAULT_PRIORITIES)
        self.assertEqual(DEFAULT_PRIORITIES[("obs_scene", "obs_governance")], 70)

    def test_resource_config_has_mc_governance_chain(self):
        """Priority map uses 'mc_governance' matching MC Command.trigger_source."""
        from agents.hapax_voice.resource_config import DEFAULT_PRIORITIES

        self.assertIn(("audio_output", "mc_governance"), DEFAULT_PRIORITIES)
        self.assertEqual(DEFAULT_PRIORITIES[("audio_output", "mc_governance")], 50)

    def test_obs_actions_mapped_to_obs_scene(self):
        """All OBS actions route to the obs_scene resource."""
        from agents.hapax_voice.resource_config import RESOURCE_MAP

        obs_actions = ["wide_ambient", "gear_closeup", "face_cam", "rapid_cut"]
        for action in obs_actions:
            self.assertEqual(RESOURCE_MAP[action], "obs_scene", f"{action} not mapped")

    def test_obs_priority_beats_mc_on_obs_scene(self):
        """OBS governance has higher priority than MC on obs_scene resource."""
        from agents.hapax_voice.resource_config import DEFAULT_PRIORITIES

        obs_priority = DEFAULT_PRIORITIES[("obs_scene", "obs_governance")]
        mc_priority = DEFAULT_PRIORITIES[("obs_scene", "mc_governance")]
        self.assertGreater(obs_priority, mc_priority)

    def test_arbiter_resolves_obs_over_mc_for_obs_scene(self):
        """When both OBS and MC claim obs_scene, OBS wins (priority 70 > 40)."""
        from agents.hapax_voice.arbiter import ResourceArbiter, ResourceClaim
        from agents.hapax_voice.resource_config import DEFAULT_PRIORITIES

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
        from agents.hapax_voice.perception import PerceptionEngine

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
        from agents.hapax_voice.perception import PerceptionEngine

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
        from agents.hapax_voice.mc_governance import compose_mc_governance

        trigger = Event[float]()
        with self.assertRaises(ValueError) as ctx:
            compose_mc_governance(trigger=trigger, behaviors={})
        self.assertIn("missing required behaviors", str(ctx.exception).lower())

    def test_mc_governance_rejects_partial_behaviors(self):
        from agents.hapax_voice.mc_governance import compose_mc_governance

        trigger = Event[float]()
        partial = {"audio_energy_rms": Behavior(0.0, watermark=0.0)}
        with self.assertRaises(ValueError) as ctx:
            compose_mc_governance(trigger=trigger, behaviors=partial)
        self.assertIn("missing required behaviors", str(ctx.exception).lower())

    def test_mc_governance_accepts_complete_behaviors(self):
        from agents.hapax_voice.mc_governance import compose_mc_governance

        trigger = Event[float]()
        behaviors = _full_mc_behaviors()
        # Should not raise
        result = compose_mc_governance(trigger=trigger, behaviors=behaviors)
        self.assertIsNotNone(result)

    def test_obs_governance_rejects_empty_behaviors(self):
        from agents.hapax_voice.obs_governance import compose_obs_governance

        trigger = Event[float]()
        with self.assertRaises(ValueError) as ctx:
            compose_obs_governance(trigger=trigger, behaviors={})
        self.assertIn("missing required behaviors", str(ctx.exception).lower())

    def test_obs_governance_accepts_complete_behaviors(self):
        from agents.hapax_voice.obs_governance import compose_obs_governance

        trigger = Event[float]()
        behaviors = _full_obs_behaviors()
        # Should not raise
        result = compose_obs_governance(trigger=trigger, behaviors=behaviors)
        self.assertIsNotNone(result)


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
    from agents.hapax_voice.timeline import TimelineMapping, TransportState

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
    from agents.hapax_voice.timeline import TimelineMapping, TransportState

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
