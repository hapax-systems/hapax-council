"""Tests for ExpressionCoordinator wiring in impingement consumer."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from shared.expression import ExpressionCoordinator


class TestExpressionCoordinatorWiring(unittest.TestCase):
    def test_single_modality_produces_one_activation(self):
        coordinator = ExpressionCoordinator()
        recruited = [("speech_production", MagicMock())]
        activations = coordinator.coordinate({"narrative": "test"}, recruited)
        assert len(activations) == 1

    def test_multi_modality_produces_coordinated_activations(self):
        coordinator = ExpressionCoordinator()
        speech = MagicMock()
        visual = MagicMock()
        visual.modality = "visual"
        recruited = [("speech_production", speech), ("shader_graph", visual)]
        activations = coordinator.coordinate({"narrative": "a warm amber glow"}, recruited)
        assert len(activations) == 2
        fragments = {a["modality"] for a in activations}
        assert len(fragments) == 2

    def test_no_fragment_returns_empty(self):
        coordinator = ExpressionCoordinator()
        recruited = [("speech_production", MagicMock())]
        activations = coordinator.coordinate({"metric": "cpu_load"}, recruited)
        assert len(activations) == 0


if __name__ == "__main__":
    unittest.main()
