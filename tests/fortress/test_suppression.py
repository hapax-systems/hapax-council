"""Tests for fortress suppression field creation and timing behavior."""

from __future__ import annotations

import unittest

from agents.fortress.config import SuppressionConfig
from agents.fortress.suppression import create_fortress_suppression_fields


class TestSuppressionFieldCreation(unittest.TestCase):
    """Test that create_fortress_suppression_fields produces 4 fields with correct config."""

    def test_creates_five_fields(self) -> None:
        fields = create_fortress_suppression_fields()
        self.assertEqual(len(fields), 5)
        expected = {
            "crisis_suppression",
            "military_alert",
            "resource_pressure",
            "planner_activity",
            "creativity_suppression",
        }
        self.assertEqual(set(fields.keys()), expected)

    def test_all_fields_start_at_zero(self) -> None:
        fields = create_fortress_suppression_fields()
        for name, field in fields.items():
            self.assertEqual(field.value, 0.0, f"{name} should start at 0.0")

    def test_default_timing_matches_config(self) -> None:
        cfg = SuppressionConfig()
        fields = create_fortress_suppression_fields(cfg)
        self.assertEqual(fields["crisis_suppression"]._attack_s, cfg.crisis_attack_s)
        self.assertEqual(fields["crisis_suppression"]._release_s, cfg.crisis_release_s)
        self.assertEqual(fields["military_alert"]._attack_s, cfg.military_attack_s)
        self.assertEqual(fields["military_alert"]._release_s, cfg.military_release_s)
        self.assertEqual(fields["resource_pressure"]._attack_s, cfg.resource_attack_s)
        self.assertEqual(fields["resource_pressure"]._release_s, cfg.resource_release_s)
        self.assertEqual(fields["planner_activity"]._attack_s, cfg.planner_attack_s)
        self.assertEqual(fields["planner_activity"]._release_s, cfg.planner_release_s)

    def test_custom_timing(self) -> None:
        cfg = SuppressionConfig(crisis_attack_s=0.05, crisis_release_s=10.0)
        fields = create_fortress_suppression_fields(cfg)
        self.assertEqual(fields["crisis_suppression"]._attack_s, 0.05)
        self.assertEqual(fields["crisis_suppression"]._release_s, 10.0)


class TestSuppressionFieldTiming(unittest.TestCase):
    """Test temporal behavior of suppression fields."""

    def test_attack_ramp_reaches_target(self) -> None:
        fields = create_fortress_suppression_fields()
        crisis = fields["crisis_suppression"]  # attack=0.1s
        now = 100.0
        crisis.set_target(1.0, now)
        # After attack_s (0.1s), should reach target
        level = crisis.tick(now + 0.15)
        self.assertAlmostEqual(level, 1.0, places=2)

    def test_release_ramp_slower_than_attack(self) -> None:
        fields = create_fortress_suppression_fields()
        crisis = fields["crisis_suppression"]  # attack=0.1s, release=5.0s
        now = 100.0
        # Ramp up instantly
        crisis.set_target(1.0, now)
        crisis.tick(now + 0.2)
        self.assertAlmostEqual(crisis.value, 1.0, places=2)
        # Now release — after 1 second should only drop by 1/5 = 0.2
        crisis.set_target(0.0, now + 0.2)
        level = crisis.tick(now + 1.2)
        self.assertAlmostEqual(level, 0.8, places=1)

    def test_tick_without_set_target_stays_zero(self) -> None:
        fields = create_fortress_suppression_fields()
        military = fields["military_alert"]
        now = 100.0
        level = military.tick(now)
        self.assertEqual(level, 0.0)
        level = military.tick(now + 1.0)
        self.assertEqual(level, 0.0)

    def test_partial_ramp(self) -> None:
        cfg = SuppressionConfig(resource_attack_s=1.0)
        fields = create_fortress_suppression_fields(cfg)
        resource = fields["resource_pressure"]
        now = 100.0
        resource.set_target(1.0, now)
        # After 0.5s of 1.0s attack, should be about 0.5
        level = resource.tick(now + 0.5)
        self.assertAlmostEqual(level, 0.5, places=1)

    def test_multiple_fields_independent(self) -> None:
        fields = create_fortress_suppression_fields()
        now = 100.0
        fields["crisis_suppression"].set_target(1.0, now)
        fields["crisis_suppression"].tick(now + 0.2)
        # Other fields should remain at 0
        self.assertEqual(fields["military_alert"].tick(now + 0.2), 0.0)
        self.assertEqual(fields["resource_pressure"].tick(now + 0.2), 0.0)
        self.assertEqual(fields["planner_activity"].tick(now + 0.2), 0.0)


if __name__ == "__main__":
    unittest.main()
