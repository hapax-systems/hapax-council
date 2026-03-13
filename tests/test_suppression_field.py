"""Tests for SuppressionField and effective_threshold."""

from __future__ import annotations

import unittest

from agents.hapax_voice.primitives import Behavior, Event
from agents.hapax_voice.suppression import SuppressionField, effective_threshold


class TestSuppressionFieldConstruction(unittest.TestCase):
    def test_default_construction(self):
        sf = SuppressionField(watermark=0.0)
        self.assertEqual(sf.value, 0.0)
        self.assertEqual(sf.target, 0.0)

    def test_custom_initial(self):
        sf = SuppressionField(initial=0.5, watermark=0.0)
        self.assertAlmostEqual(sf.value, 0.5)

    def test_initial_clamped_high(self):
        sf = SuppressionField(initial=2.0, watermark=0.0)
        self.assertAlmostEqual(sf.value, 1.0)

    def test_initial_clamped_low(self):
        sf = SuppressionField(initial=-0.5, watermark=0.0)
        self.assertAlmostEqual(sf.value, 0.0)

    def test_invalid_attack_raises(self):
        with self.assertRaises(ValueError):
            SuppressionField(attack_s=0.0)

    def test_invalid_release_raises(self):
        with self.assertRaises(ValueError):
            SuppressionField(release_s=-1.0)

    def test_behavior_property_returns_behavior(self):
        sf = SuppressionField(watermark=0.0)
        self.assertIsInstance(sf.behavior, Behavior)


class TestSuppressionFieldSetTarget(unittest.TestCase):
    def test_set_target_clamped_high(self):
        sf = SuppressionField(watermark=0.0)
        sf.set_target(1.5, now=1.0)
        self.assertAlmostEqual(sf.target, 1.0)

    def test_set_target_clamped_low(self):
        sf = SuppressionField(watermark=0.0)
        sf.set_target(-0.5, now=1.0)
        self.assertAlmostEqual(sf.target, 0.0)

    def test_set_target_establishes_reference(self):
        sf = SuppressionField(watermark=0.0)
        sf.set_target(0.5, now=1.0)
        # Now tick should not move on first call (reference established by set_target)
        val = sf.tick(1.0)
        self.assertAlmostEqual(val, 0.0)


class TestSuppressionFieldTick(unittest.TestCase):
    def test_first_tick_no_movement(self):
        sf = SuppressionField(watermark=0.0)
        sf.set_target(1.0, now=1.0)
        val = sf.tick(1.0)
        self.assertAlmostEqual(val, 0.0)  # reference established, no dt

    def test_first_tick_without_set_target(self):
        sf = SuppressionField(watermark=0.0)
        val = sf.tick(1.0)
        self.assertAlmostEqual(val, 0.0)  # first tick only establishes reference

    def test_attack_ramp(self):
        sf = SuppressionField(attack_s=1.0, release_s=1.0, watermark=0.0)
        sf.set_target(1.0, now=0.0)
        sf.tick(0.0)  # establish reference
        val = sf.tick(0.5)  # 0.5s at rate 1.0/s → 0.5
        self.assertAlmostEqual(val, 0.5)

    def test_attack_ramp_clamps_at_target(self):
        sf = SuppressionField(attack_s=0.5, watermark=0.0)
        sf.set_target(0.8, now=0.0)
        sf.tick(0.0)
        val = sf.tick(10.0)  # way past target
        self.assertAlmostEqual(val, 0.8)

    def test_release_ramp(self):
        sf = SuppressionField(attack_s=0.1, release_s=1.0, initial=1.0, watermark=0.0)
        sf.set_target(0.0, now=0.0)
        sf.tick(0.0)
        val = sf.tick(0.5)  # 0.5s at rate 1.0/s → 0.5 reduction
        self.assertAlmostEqual(val, 0.5)

    def test_release_ramp_clamps_at_target(self):
        sf = SuppressionField(release_s=0.5, initial=1.0, watermark=0.0)
        sf.set_target(0.3, now=0.0)
        sf.tick(0.0)
        val = sf.tick(10.0)
        self.assertAlmostEqual(val, 0.3)

    def test_steady_state_no_change(self):
        sf = SuppressionField(initial=0.5, watermark=0.0)
        sf.set_target(0.5, now=0.0)
        sf.tick(0.0)
        val = sf.tick(1.0)
        self.assertAlmostEqual(val, 0.5)

    def test_zero_dt_no_change(self):
        sf = SuppressionField(attack_s=1.0, watermark=0.0)
        sf.set_target(1.0, now=1.0)
        sf.tick(1.0)
        val = sf.tick(1.0)  # zero dt
        self.assertAlmostEqual(val, 0.0)

    def test_watermark_monotonicity(self):
        sf = SuppressionField(attack_s=1.0, watermark=0.0)
        sf.set_target(1.0, now=0.0)
        sf.tick(0.0)
        sf.tick(0.5)
        wm1 = sf.behavior.watermark
        sf.tick(1.0)
        wm2 = sf.behavior.watermark
        self.assertGreaterEqual(wm2, wm1)

    def test_multi_step_ramp(self):
        sf = SuppressionField(attack_s=1.0, watermark=0.0)
        sf.set_target(1.0, now=0.0)
        sf.tick(0.0)
        sf.tick(0.25)
        sf.tick(0.50)
        sf.tick(0.75)
        val = sf.tick(1.0)
        self.assertAlmostEqual(val, 1.0)


class TestEffectiveThreshold(unittest.TestCase):
    def test_zero_suppression(self):
        self.assertAlmostEqual(effective_threshold(0.3, 0.0), 0.3)

    def test_full_suppression(self):
        self.assertAlmostEqual(effective_threshold(0.3, 1.0), 1.0)

    def test_zero_base_zero_suppression(self):
        self.assertAlmostEqual(effective_threshold(0.0, 0.0), 0.0)

    def test_zero_base_full_suppression(self):
        self.assertAlmostEqual(effective_threshold(0.0, 1.0), 1.0)

    def test_one_base_any_suppression(self):
        self.assertAlmostEqual(effective_threshold(1.0, 0.5), 1.0)

    def test_partial_suppression(self):
        # 0.3 + 0.5 * (1 - 0.3) = 0.3 + 0.35 = 0.65
        self.assertAlmostEqual(effective_threshold(0.3, 0.5), 0.65)

    def test_monotonic_in_suppression(self):
        base = 0.3
        prev = effective_threshold(base, 0.0)
        for s in [0.1, 0.3, 0.5, 0.7, 1.0]:
            curr = effective_threshold(base, s)
            self.assertGreaterEqual(curr, prev)
            prev = curr


class TestSuppressionFieldWithCombinator(unittest.TestCase):
    def test_behavior_works_in_with_latest_from(self):
        """SuppressionField.behavior participates in Combinator sampling."""
        from agents.hapax_voice.combinator import with_latest_from
        from agents.hapax_voice.governance import FusedContext

        sf = SuppressionField(initial=0.5, watermark=1.0)
        trigger = Event[float]()
        behaviors = {"suppression": sf.behavior}
        fused_output = with_latest_from(trigger, behaviors)

        results: list[FusedContext] = []
        fused_output.subscribe(lambda ts, ctx: results.append(ctx))

        trigger.emit(2.0, 2.0)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0].get_sample("suppression").value, 0.5)


if __name__ == "__main__":
    unittest.main()
