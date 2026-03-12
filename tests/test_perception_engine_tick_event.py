"""Tests for PerceptionEngine.tick_event — tick emits an Event for combinator wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.perception import PerceptionEngine
from agents.hapax_voice.primitives import Behavior


def _make_engine() -> PerceptionEngine:
    """Create a PerceptionEngine with minimal mocked dependencies."""
    presence = MagicMock()
    presence.latest_vad_confidence = 0.0
    presence.face_detected = False
    presence.face_count = 0
    presence.score = "likely_absent"
    workspace_monitor = MagicMock()
    return PerceptionEngine(presence=presence, workspace_monitor=workspace_monitor)


class TestPerceptionEngineTickEvent:
    def test_tick_emits_event(self):
        """Tick event fires on each tick()."""
        engine = _make_engine()
        received = []
        engine.tick_event.subscribe(lambda ts, val: received.append((ts, val)))

        engine.tick()
        assert len(received) == 1

        engine.tick()
        assert len(received) == 2

    def test_tick_event_timestamp_matches(self):
        """Tick event timestamp matches the EnvironmentState timestamp."""
        engine = _make_engine()
        received = []
        engine.tick_event.subscribe(lambda ts, val: received.append(ts))

        state = engine.tick()
        assert len(received) == 1
        assert received[0] == state.timestamp

    def test_tick_event_usable_with_combinator(self):
        """with_latest_from(tick_event, behaviors) produces FusedContext."""
        engine = _make_engine()
        extra = Behavior(42.0, watermark=1.0)
        fused_event = with_latest_from(engine.tick_event, {"extra": extra})

        received = []
        fused_event.subscribe(lambda ts, ctx: received.append(ctx))

        engine.tick()
        assert len(received) == 1
        ctx = received[0]
        assert ctx.samples["extra"].value == 42.0
