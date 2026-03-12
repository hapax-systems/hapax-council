"""Tests for Combinator (withLatestFrom)."""

from __future__ import annotations

from agents.hapax_voice.combinator import with_latest_from
from agents.hapax_voice.governance import FusedContext
from agents.hapax_voice.primitives import Behavior, Event


class TestWithLatestFrom:
    def test_fuses_trigger_with_behaviors(self):
        trigger: Event[str] = Event()
        b1 = Behavior(10, watermark=1.0)
        b2 = Behavior("hello", watermark=2.0)

        received: list[FusedContext] = []
        output = with_latest_from(trigger, {"count": b1, "greeting": b2})
        output.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(3.0, "go")
        assert len(received) == 1
        ctx = received[0]
        assert ctx.trigger_time == 3.0
        assert ctx.trigger_value == "go"
        assert ctx.get_sample("count").value == 10
        assert ctx.get_sample("greeting").value == "hello"

    def test_min_watermark_is_stalest(self):
        trigger: Event[None] = Event()
        b_fresh = Behavior(1.0, watermark=9.0)
        b_stale = Behavior(2.0, watermark=3.0)

        received: list[FusedContext] = []
        output = with_latest_from(trigger, {"fresh": b_fresh, "stale": b_stale})
        output.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(10.0, None)
        assert received[0].min_watermark == 3.0

    def test_output_fires_at_trigger_times(self):
        trigger: Event[int] = Event()
        b = Behavior(0, watermark=0.0)

        timestamps: list[float] = []
        output = with_latest_from(trigger, {"val": b})
        output.subscribe(lambda ts, ctx: timestamps.append(ts))

        trigger.emit(1.0, 1)
        trigger.emit(2.5, 2)
        trigger.emit(7.0, 3)
        assert timestamps == [1.0, 2.5, 7.0]

    def test_samples_latest_behavior_value(self):
        trigger: Event[None] = Event()
        b = Behavior(0, watermark=0.0)

        received: list[FusedContext] = []
        output = with_latest_from(trigger, {"val": b})
        output.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(1.0, None)
        assert received[0].get_sample("val").value == 0

        b.update(42, 2.0)
        trigger.emit(3.0, None)
        assert received[1].get_sample("val").value == 42

    def test_empty_behaviors(self):
        trigger: Event[str] = Event()

        received: list[FusedContext] = []
        output = with_latest_from(trigger, {})
        output.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(1.0, "tick")
        assert len(received) == 1
        assert received[0].samples == {}
        assert received[0].min_watermark == 1.0  # defaults to trigger timestamp

    def test_rate_independence(self):
        """Behavior updates don't trigger output; only trigger fires do."""
        trigger: Event[None] = Event()
        b = Behavior(0, watermark=0.0)

        fire_count = 0

        def count_fires(ts, ctx):
            nonlocal fire_count
            fire_count += 1

        output = with_latest_from(trigger, {"val": b})
        output.subscribe(count_fires)

        # Update behavior many times — no output fires
        for i in range(100):
            b.update(i, float(i))
        assert fire_count == 0

        # Only trigger fires cause output
        trigger.emit(200.0, None)
        assert fire_count == 1

    def test_watermarks_propagate_through_samples(self):
        trigger: Event[None] = Event()
        b = Behavior("initial", watermark=5.0)

        received: list[FusedContext] = []
        output = with_latest_from(trigger, {"text": b})
        output.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(10.0, None)
        assert received[0].get_sample("text").watermark == 5.0

        b.update("updated", 8.0)
        trigger.emit(11.0, None)
        assert received[1].get_sample("text").watermark == 8.0

    def test_with_perception_behaviors(self):
        """Integration: uses PerceptionEngine's behaviors dict."""
        from unittest.mock import MagicMock

        from agents.hapax_voice.perception import PerceptionEngine

        presence = MagicMock()
        presence.latest_vad_confidence = 0.7
        presence.face_detected = True
        presence.face_count = 1
        engine = PerceptionEngine(presence=presence, workspace_monitor=MagicMock())
        engine.tick()

        trigger: Event[str] = Event()
        received: list[FusedContext] = []
        output = with_latest_from(trigger, engine.behaviors)
        output.subscribe(lambda ts, ctx: received.append(ctx))

        trigger.emit(100.0, "midi_clock")
        assert len(received) == 1
        ctx = received[0]
        assert ctx.get_sample("vad_confidence").value == 0.7
        assert ctx.get_sample("operator_present").value is True
        assert ctx.get_sample("face_count").value == 1

    def test_late_subscriber_no_history(self):
        trigger: Event[None] = Event()
        b = Behavior(0, watermark=0.0)
        output = with_latest_from(trigger, {"val": b})

        trigger.emit(1.0, None)  # fires before subscriber

        received: list[FusedContext] = []
        output.subscribe(lambda ts, ctx: received.append(ctx))
        assert received == []

    def test_subscriber_exception_isolation(self):
        trigger: Event[None] = Event()
        b = Behavior(0, watermark=0.0)
        output = with_latest_from(trigger, {"val": b})

        good: list[FusedContext] = []

        def bad_sub(ts, ctx):
            raise RuntimeError("boom")

        output.subscribe(bad_sub)
        output.subscribe(lambda ts, ctx: good.append(ctx))

        trigger.emit(1.0, None)
        assert len(good) == 1
