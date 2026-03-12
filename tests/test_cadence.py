"""Tests for CadenceGroup — multi-cadence dispatch for perception backends."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.hapax_voice.cadence import CadenceGroup
from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.perception import PerceptionEngine, PerceptionTier
from agents.hapax_voice.primitives import Behavior


def _mock_backend(name: str = "test", provides: frozenset[str] | None = None):
    """Create a mock PerceptionBackend."""
    backend = MagicMock()
    backend.name = name
    backend.provides = provides or frozenset()
    backend.tier = PerceptionTier.FAST
    backend.available.return_value = True
    return backend


class TestCadenceGroup:
    def test_poll_calls_all_backends(self):
        """All registered backends get contribute() called."""
        b1 = _mock_backend("b1")
        b2 = _mock_backend("b2")
        group = CadenceGroup(name="test", interval_s=0.1, backends=[b1, b2])
        behaviors: dict[str, Behavior] = {}

        group.poll(behaviors)

        b1.contribute.assert_called_once_with(behaviors)
        b2.contribute.assert_called_once_with(behaviors)

    def test_poll_emits_tick_event(self):
        """Tick event fires after polling."""
        group = CadenceGroup(name="test", interval_s=0.1)
        received = []
        group.tick_event.subscribe(lambda ts, val: received.append(ts))

        group.poll({})
        assert len(received) == 1

    def test_poll_survives_backend_error(self):
        """A failing backend doesn't crash the group or prevent tick event."""
        good = _mock_backend("good")
        bad = _mock_backend("bad")
        bad.contribute.side_effect = RuntimeError("boom")
        group = CadenceGroup(name="test", interval_s=0.1, backends=[bad, good])

        received = []
        group.tick_event.subscribe(lambda ts, val: received.append(ts))

        group.poll({})

        # Good backend still called despite bad one failing
        good.contribute.assert_called_once()
        # Tick event still fires
        assert len(received) == 1

    def test_register_adds_backend(self):
        group = CadenceGroup(name="test", interval_s=0.1)
        b = _mock_backend("new")
        group.register(b)
        assert b in group.backends

    def test_empty_group_poll_emits_event(self):
        """No backends — event still fires."""
        group = CadenceGroup(name="empty", interval_s=1.0)
        received = []
        group.tick_event.subscribe(lambda ts, val: received.append(ts))
        group.poll({})
        assert len(received) == 1


class TestMultiCadenceIntegration:
    def _make_engine(self) -> PerceptionEngine:
        presence = MagicMock()
        presence.latest_vad_confidence = 0.0
        presence.face_detected = False
        presence.face_count = 0
        presence.score = "likely_absent"
        workspace = MagicMock()
        return PerceptionEngine(presence=presence, workspace_monitor=workspace)

    def test_fast_cadence_updates_shared_behaviors(self):
        """CadenceGroup writes to engine.behaviors, visible to engine.tick()."""
        engine = self._make_engine()

        def _contribute(behaviors):
            import time as _t

            if "custom_signal" not in behaviors:
                behaviors["custom_signal"] = Behavior(0.0)
            behaviors["custom_signal"].update(99.0, _t.monotonic())

        backend = _mock_backend("fast_sensor")
        backend.contribute.side_effect = _contribute

        group = CadenceGroup(name="fast", interval_s=0.05, backends=[backend])
        group.poll(engine.behaviors)

        assert "custom_signal" in engine.behaviors
        assert engine.behaviors["custom_signal"].value == 99.0

    def test_slow_and_fast_coexist(self):
        """Multiple cadence groups can write to the same behaviors dict without conflict."""
        engine = self._make_engine()

        def _fast_contribute(behaviors):
            import time as _t

            if "fast_val" not in behaviors:
                behaviors["fast_val"] = Behavior(0.0)
            behaviors["fast_val"].update(1.0, _t.monotonic())

        def _slow_contribute(behaviors):
            import time as _t

            if "slow_val" not in behaviors:
                behaviors["slow_val"] = Behavior("")
            behaviors["slow_val"].update("enriched", _t.monotonic())

        fast_be = _mock_backend("fast")
        fast_be.contribute.side_effect = _fast_contribute
        slow_be = _mock_backend("slow")
        slow_be.contribute.side_effect = _slow_contribute

        fast_group = CadenceGroup(name="fast", interval_s=0.05, backends=[fast_be])
        slow_group = CadenceGroup(name="slow", interval_s=1.0, backends=[slow_be])

        fast_group.poll(engine.behaviors)
        slow_group.poll(engine.behaviors)

        assert engine.behaviors["fast_val"].value == 1.0
        assert engine.behaviors["slow_val"].value == "enriched"

    def test_cadence_group_tick_triggers_combinator(self):
        """with_latest_from(group.tick_event, behaviors) produces FusedContext."""
        engine = self._make_engine()
        engine.behaviors["test_b"] = Behavior(42.0, watermark=1.0)

        group = CadenceGroup(name="fast", interval_s=0.05)
        fused = with_latest_from(group.tick_event, {"test_b": engine.behaviors["test_b"]})

        received = []
        fused.subscribe(lambda ts, ctx: received.append(ctx))

        group.poll(engine.behaviors)
        assert len(received) == 1
        assert received[0].samples["test_b"].value == 42.0
