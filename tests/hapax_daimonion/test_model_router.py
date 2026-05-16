"""Tests for model_router — source-conditioned framing + fallback observability."""

from __future__ import annotations

import logging

from agents.hapax_daimonion.model_router import (
    ModelTier,
    RoutingDecision,
    TIER_ROUTES,
    fallback_on_local_unavailable,
    route,
)


class TestSourceConditionedFraming:
    """AC1: Routing uses 'source-conditioned' not 'non-RLHF'."""

    def test_local_tier_route_is_source_conditioned(self):
        """LOCAL tier should be described as source-conditioned in module."""
        import agents.hapax_daimonion.model_router as mod

        docstring = mod.__doc__
        assert "source-conditioned" in docstring
        assert "non-RLHF" not in docstring


class TestFallbackOnLocalUnavailable:
    """AC2: TabbyAPI fallback emits observable event."""

    def test_fallback_returns_fast_tier(self):
        original = RoutingDecision(
            tier=ModelTier.LOCAL,
            model=TIER_ROUTES[ModelTier.LOCAL],
            reason="simple",
            canned_response="",
        )
        fallback = fallback_on_local_unavailable(original)
        assert fallback.tier == ModelTier.FAST
        assert fallback.model == TIER_ROUTES[ModelTier.FAST]

    def test_fallback_reason_includes_source_conditioned_fallback(self):
        original = RoutingDecision(
            tier=ModelTier.LOCAL,
            model=TIER_ROUTES[ModelTier.LOCAL],
            reason="simple",
            canned_response="",
        )
        fallback = fallback_on_local_unavailable(original)
        assert "source_conditioned_fallback" in fallback.reason

    def test_fallback_preserves_original_reason(self):
        original = RoutingDecision(
            tier=ModelTier.LOCAL,
            model=TIER_ROUTES[ModelTier.LOCAL],
            reason="coding+simple",
            canned_response="",
        )
        fallback = fallback_on_local_unavailable(original)
        assert "coding+simple" in fallback.reason

    def test_fallback_emits_warning_log(self, caplog):
        original = RoutingDecision(
            tier=ModelTier.LOCAL,
            model=TIER_ROUTES[ModelTier.LOCAL],
            reason="simple",
            canned_response="",
        )
        with caplog.at_level(logging.WARNING, logger="agents.hapax_daimonion.model_router"):
            fallback_on_local_unavailable(original)
        assert any("source_conditioned_fallback" in r.message for r in caplog.records)
        assert any("cloud" in r.message.lower() for r in caplog.records)

    def test_fallback_returns_egress_to_cloud_true(self):
        original = RoutingDecision(
            tier=ModelTier.LOCAL,
            model=TIER_ROUTES[ModelTier.LOCAL],
            reason="simple",
            canned_response="",
        )
        fallback = fallback_on_local_unavailable(original)
        assert fallback.egress_to_cloud is True

    def test_local_routing_has_egress_to_cloud_false(self):
        decision = route("hey", turn_count=0)
        if decision.tier == ModelTier.LOCAL:
            assert decision.egress_to_cloud is False

    def test_cloud_routing_has_egress_to_cloud_true(self):
        decision = route(
            "explain the theory of relativity in detail please",
            turn_count=6,
        )
        if decision.tier in (ModelTier.FAST, ModelTier.STRONG, ModelTier.CAPABLE):
            assert decision.egress_to_cloud is True

    def test_canned_routing_has_egress_to_cloud_false(self):
        decision = route("thanks", turn_count=2)
        assert decision.tier == ModelTier.CANNED
        assert decision.egress_to_cloud is False

    def test_fallback_on_non_local_raises(self):
        """Fallback only makes sense for LOCAL tier."""
        original = RoutingDecision(
            tier=ModelTier.FAST,
            model=TIER_ROUTES[ModelTier.FAST],
            reason="tools",
            canned_response="",
        )
        import pytest

        with pytest.raises(ValueError, match="LOCAL"):
            fallback_on_local_unavailable(original)
