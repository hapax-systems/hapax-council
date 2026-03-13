"""Tests for cross-role state types and Behavior factory."""

from __future__ import annotations

import unittest

from agents.hapax_voice.chain_state import (
    ConversationState,
    GovernanceChainState,
    create_cross_role_behaviors,
)
from agents.hapax_voice.primitives import Behavior


class TestGovernanceChainState(unittest.TestCase):
    def test_all_values(self):
        expected = {"idle", "active", "suppressed", "firing"}
        self.assertEqual({s.value for s in GovernanceChainState}, expected)


class TestConversationState(unittest.TestCase):
    def test_all_values(self):
        expected = {"idle", "listening", "speaking", "processing"}
        self.assertEqual({s.value for s in ConversationState}, expected)


class TestCreateCrossRoleBehaviors(unittest.TestCase):
    def test_returns_all_expected_keys(self):
        b = create_cross_role_behaviors(watermark=0.0)
        expected = {
            "mc_state",
            "conversation_state",
            "current_scene",
            "conversation_suppression",
            "mc_activity",
            "monitoring_alert",
        }
        self.assertEqual(set(b.keys()), expected)

    def test_all_are_behaviors(self):
        b = create_cross_role_behaviors(watermark=0.0)
        for name, behavior in b.items():
            self.assertIsInstance(behavior, Behavior, f"{name} is not a Behavior")

    def test_all_sampleable_immediately(self):
        b = create_cross_role_behaviors(watermark=0.0)
        for name, behavior in b.items():
            stamped = behavior.sample()
            self.assertIsNotNone(stamped.value, f"{name} sample is None")

    def test_sentinel_types(self):
        b = create_cross_role_behaviors(watermark=0.0)
        self.assertIsInstance(b["mc_state"].value, GovernanceChainState)
        self.assertIsInstance(b["conversation_state"].value, ConversationState)
        self.assertIsInstance(b["current_scene"].value, str)
        self.assertIsInstance(b["conversation_suppression"].value, float)
        self.assertIsInstance(b["mc_activity"].value, float)
        self.assertIsInstance(b["monitoring_alert"].value, float)

    def test_default_sentinel_values(self):
        b = create_cross_role_behaviors(watermark=0.0)
        self.assertEqual(b["mc_state"].value, GovernanceChainState.IDLE)
        self.assertEqual(b["conversation_state"].value, ConversationState.IDLE)
        self.assertEqual(b["current_scene"].value, "wide_ambient")
        self.assertAlmostEqual(b["conversation_suppression"].value, 0.0)
        self.assertAlmostEqual(b["mc_activity"].value, 0.0)
        self.assertAlmostEqual(b["monitoring_alert"].value, 0.0)

    def test_custom_watermark(self):
        b = create_cross_role_behaviors(watermark=42.0)
        for behavior in b.values():
            self.assertAlmostEqual(behavior.watermark, 42.0)

    def test_behaviors_are_updatable(self):
        b = create_cross_role_behaviors(watermark=0.0)
        b["mc_state"].update(GovernanceChainState.FIRING, 1.0)
        self.assertEqual(b["mc_state"].value, GovernanceChainState.FIRING)


if __name__ == "__main__":
    unittest.main()
