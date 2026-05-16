"""Tests for routing provenance struct — every LLM call carries tier/reason/egress."""

from __future__ import annotations

from agents.hapax_daimonion.model_router import (
    ModelTier,
    RoutingDecision,
    RoutingProvenance,
    TIER_ROUTES,
    route,
)


class TestRoutingProvenance:
    """AC1-4: Provenance struct carries tier, reason, egress_to_cloud."""

    def test_provenance_from_routing_decision(self):
        decision = RoutingDecision(
            tier=ModelTier.LOCAL,
            model=TIER_ROUTES[ModelTier.LOCAL],
            reason="simple",
            canned_response="",
            egress_to_cloud=False,
        )
        prov = decision.provenance
        assert isinstance(prov, RoutingProvenance)
        assert prov.tier == "LOCAL"
        assert prov.reason == "simple"
        assert prov.egress_to_cloud is False

    def test_provenance_cloud_tier(self):
        decision = RoutingDecision(
            tier=ModelTier.STRONG,
            model=TIER_ROUTES[ModelTier.STRONG],
            reason="ramping",
            canned_response="",
            egress_to_cloud=True,
        )
        prov = decision.provenance
        assert prov.tier == "STRONG"
        assert prov.egress_to_cloud is True

    def test_provenance_is_serializable(self):
        decision = route("explain quantum mechanics", turn_count=6)
        prov = decision.provenance
        d = prov.to_dict()
        assert isinstance(d, dict)
        assert "tier" in d
        assert "reason" in d
        assert "egress_to_cloud" in d
        assert isinstance(d["egress_to_cloud"], bool)

    def test_provenance_from_route_call(self):
        decision = route("hey", turn_count=0)
        prov = decision.provenance
        assert prov.tier in ("CANNED", "LOCAL")

    def test_provenance_canned_not_egress(self):
        decision = route("thanks", turn_count=2)
        assert decision.provenance.egress_to_cloud is False

    def test_provenance_governance_override_is_cloud(self):
        decision = route("anything", consent_phase="refused")
        prov = decision.provenance
        assert prov.tier == "CAPABLE"
        assert prov.egress_to_cloud is True

    def test_provenance_model_field(self):
        decision = RoutingDecision(
            tier=ModelTier.FAST,
            model=TIER_ROUTES[ModelTier.FAST],
            reason="tools",
            canned_response="",
            egress_to_cloud=True,
        )
        prov = decision.provenance
        assert prov.model == "gemini-flash"
