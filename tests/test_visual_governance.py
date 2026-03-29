"""Tests for visual governance composition."""

from __future__ import annotations

import unittest

from agents.effect_graph.visual_governance import VisualGovernance
from shared.capability import SystemContext


def _make_ctx(**overrides) -> SystemContext:
    defaults = {
        "stimmung_stance": "nominal",
        "consent_state": {},
        "guest_present": False,
        "active_backends": frozenset(),
        "working_mode": "rnd",
        "experiment_flags": {},
        "tpn_active": False,
    }
    defaults.update(overrides)
    return SystemContext(**defaults)


class TestVisualGovernance(unittest.TestCase):
    def test_nominal_delegates_to_atmospheric(self):
        gov = VisualGovernance()
        result = gov.evaluate(_make_ctx(), "nominal", "medium", ["ambient", "trails"])
        assert result is not None  # atmospheric selector picks something

    def test_consent_pending_suppresses(self):
        gov = VisualGovernance()
        result = gov.evaluate(
            _make_ctx(consent_state={"phase": "consent_pending"}),
            "nominal",
            "medium",
            ["ambient"],
        )
        assert result is None

    def test_critical_forces_silhouette(self):
        gov = VisualGovernance()
        result = gov.evaluate(
            _make_ctx(stimmung_stance="critical"),
            "critical",
            "low",
            ["silhouette", "ambient"],
        )
        assert result == "silhouette"

    def test_consent_pending_overrides_critical(self):
        """Consent veto fires before fallback can select silhouette."""
        gov = VisualGovernance()
        result = gov.evaluate(
            _make_ctx(
                stimmung_stance="critical",
                consent_state={"phase": "consent_pending"},
            ),
            "critical",
            "low",
            ["silhouette"],
        )
        assert result is None
