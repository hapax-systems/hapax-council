"""Tests for feedback loop wiring."""

from __future__ import annotations

import unittest

from agents.hapax_voice.actuation_event import ActuationEvent
from agents.hapax_voice.feedback import wire_feedback_behaviors
from agents.hapax_voice.primitives import Behavior, Event


class TestWireFeedbackBehaviors(unittest.TestCase):
    def test_factory_returns_expected_keys(self):
        event = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(event, watermark=0.0)
        expected = {"last_mc_fire", "mc_fire_count", "last_obs_switch", "last_tts_end"}
        self.assertEqual(set(behaviors.keys()), expected)

    def test_all_are_behaviors(self):
        event = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(event, watermark=0.0)
        for name, b in behaviors.items():
            self.assertIsInstance(b, Behavior, f"{name} is not a Behavior")

    def test_mc_event_updates_last_mc_fire(self):
        event = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(event, watermark=0.0)
        ae = ActuationEvent(action="vocal_throw", wall_time=10.0)
        event.emit(1.0, ae)
        self.assertAlmostEqual(behaviors["last_mc_fire"].value, 10.0)

    def test_mc_event_increments_count(self):
        event = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(event, watermark=0.0)
        event.emit(1.0, ActuationEvent(action="vocal_throw", wall_time=10.0))
        event.emit(2.0, ActuationEvent(action="ad_lib", wall_time=11.0))
        self.assertEqual(behaviors["mc_fire_count"].value, 2)

    def test_obs_event_updates_last_obs_switch(self):
        event = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(event, watermark=0.0)
        event.emit(1.0, ActuationEvent(action="face_cam", wall_time=10.0))
        self.assertAlmostEqual(behaviors["last_obs_switch"].value, 10.0)

    def test_tts_event_updates_last_tts_end(self):
        event = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(event, watermark=0.0)
        event.emit(1.0, ActuationEvent(action="tts_announce", wall_time=10.0))
        self.assertAlmostEqual(behaviors["last_tts_end"].value, 10.0)

    def test_unrelated_action_no_update(self):
        event = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(event, watermark=0.0)
        event.emit(1.0, ActuationEvent(action="unknown_action", wall_time=10.0))
        self.assertAlmostEqual(behaviors["last_mc_fire"].value, 0.0)
        self.assertEqual(behaviors["mc_fire_count"].value, 0)
        self.assertAlmostEqual(behaviors["last_obs_switch"].value, 0.0)
        self.assertAlmostEqual(behaviors["last_tts_end"].value, 0.0)

    def test_watermarks_advance(self):
        event = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(event, watermark=0.0)
        event.emit(1.0, ActuationEvent(action="vocal_throw", wall_time=10.0))
        wm1 = behaviors["last_mc_fire"].watermark
        event.emit(2.0, ActuationEvent(action="vocal_throw", wall_time=11.0))
        wm2 = behaviors["last_mc_fire"].watermark
        self.assertGreater(wm2, wm1)

    def test_integration_with_with_latest_from(self):
        """Feedback Behaviors can be sampled via Combinator."""
        from agents.hapax_voice.combinator import with_latest_from
        from agents.hapax_voice.governance import FusedContext

        actuation = Event[ActuationEvent]()
        fb = wire_feedback_behaviors(actuation, watermark=0.0)

        trigger = Event[float]()
        fused = with_latest_from(trigger, fb)
        results: list[FusedContext] = []
        fused.subscribe(lambda ts, ctx: results.append(ctx))

        # Fire an actuation event
        actuation.emit(1.0, ActuationEvent(action="vocal_throw", wall_time=10.0))
        # Then trigger sampling
        trigger.emit(2.0, 2.0)

        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0].get_sample("last_mc_fire").value, 10.0)
        self.assertEqual(results[0].get_sample("mc_fire_count").value, 1)

    def test_multiple_mc_actions(self):
        """Both vocal_throw and ad_lib update MC feedback."""
        event = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(event, watermark=0.0)
        event.emit(1.0, ActuationEvent(action="vocal_throw", wall_time=10.0))
        event.emit(2.0, ActuationEvent(action="ad_lib", wall_time=11.0))
        self.assertAlmostEqual(behaviors["last_mc_fire"].value, 11.0)
        self.assertEqual(behaviors["mc_fire_count"].value, 2)

    def test_multiple_obs_actions(self):
        """All OBS scene actions update last_obs_switch."""
        event = Event[ActuationEvent]()
        behaviors = wire_feedback_behaviors(event, watermark=0.0)
        for i, action in enumerate(["wide_ambient", "gear_closeup", "face_cam", "rapid_cut"]):
            event.emit(float(i + 1), ActuationEvent(action=action, wall_time=float(10 + i)))
        self.assertAlmostEqual(behaviors["last_obs_switch"].value, 13.0)


if __name__ == "__main__":
    unittest.main()
