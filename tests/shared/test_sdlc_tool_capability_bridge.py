"""Tests for the SDLC provider/tool route-supply bridge."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from shared.capability_classification_inventory import load_capability_classification_inventory
from shared.platform_capability_registry import (
    PlatformCapabilityRegistry,
    load_platform_capability_registry,
)
from shared.route_metadata_schema import SourceGroundingNeed
from shared.sdlc_tool_capability_bridge import (
    ProviderSpendPosture,
    RouteSupplyRole,
    SdlcRouteDemand,
    SdlcRouteSupplyFact,
    bridge_policy_summary,
    project_provider_gateway_supply_facts,
    project_provider_tool_route_supply_fact,
    project_sdlc_route_supply_facts,
)
from shared.world_surface_provider_tool_health import load_provider_tool_health_fixtures


def _fact(facts: list[SdlcRouteSupplyFact], supply_id: str) -> SdlcRouteSupplyFact:
    return next(fact for fact in facts if fact.supply_id == supply_id)


def _registry_with_active_provider_gateway() -> PlatformCapabilityRegistry:
    registry = load_platform_capability_registry()
    payload: dict[str, Any] = registry.model_dump(mode="json")
    checked_at = "2026-06-25T16:30:00Z"

    for route in payload["routes"]:
        if route["route_id"] != "api.headless.provider_gateway":
            continue

        route["route_state"] = "active"
        route["blocked_reasons"] = []
        freshness = route["freshness"]
        for surface in ("capability", "quota", "resource"):
            freshness[f"{surface}_checked_at"] = checked_at
            freshness["evidence"][surface]["evidence_refs"] = [
                f"test:provider-gateway:{surface}:observed"
            ]
            freshness["evidence"][surface]["blocked_reasons"] = []
        break
    else:  # pragma: no cover - registry contract pins this route.
        raise AssertionError("api.headless.provider_gateway missing from registry")

    return PlatformCapabilityRegistry.model_validate(payload)


def test_bridge_projects_expected_roles_and_visible_held_rows() -> None:
    facts = project_sdlc_route_supply_facts()
    roles = {fact.role for fact in facts}

    assert {
        RouteSupplyRole.SOURCE_ACQUISITION,
        RouteSupplyRole.SUPPLIED_EVIDENCE_RECALL,
        RouteSupplyRole.VERIFIER_FLOOR_CHECKING,
        RouteSupplyRole.PUBLICATION_EGRESS,
        RouteSupplyRole.AVSDLC_AUDIO_TOOL,
        RouteSupplyRole.TELEMETRY_RESOURCE,
        RouteSupplyRole.PROVIDER_GATEWAY,
        RouteSupplyRole.STORAGE_INFRA_CONTROL,
    } <= roles

    summary = bridge_policy_summary(facts)
    assert summary["total_facts"] == len(facts)
    assert summary["held_facts"] > 0

    soundcloud = _fact(
        facts,
        "sdlc_route_supply:provider_tool.publication.soundcloud_unavailable",
    )
    tauri = _fact(
        facts,
        "sdlc_route_supply:inventory:surface.tauri_logos.decommissioned_frame_server",
    )
    private_orientation = _fact(
        facts,
        "sdlc_route_supply:provider_tool.local_api.orientation",
    )

    for held in (soundcloud, tauri, private_orientation):
        assert held.visible is True
        assert held.can_satisfy_required_demands is False
        assert held.blocking_reasons


def test_source_acquisition_requires_capability_and_evidence() -> None:
    facts = project_sdlc_route_supply_facts(include_inventory_rows=False)
    tavily = _fact(facts, "sdlc_route_supply:provider_tool.search.tavily_source_acquisition")

    demand = SdlcRouteDemand(
        role=RouteSupplyRole.SOURCE_ACQUISITION,
        source_grounding_need=SourceGroundingNeed.WEB_CURRENT,
        requires_public_claim_evidence=True,
    )
    assessment = tavily.assess(demand)

    assert assessment.satisfies is True
    assert tavily.source_acquisition_capable is True
    assert tavily.source_acquisition_evidence_refs
    assert tavily.fresh_source_outcome_refs == ("tpo:search.tavily:source-acquired",)

    held_payload = tavily.model_dump(mode="python")
    held_payload["can_satisfy_required_demands"] = False
    held_payload["source_acquisition_evidence_refs"] = ()
    held_payload["fresh_current_world_evidence_allowed"] = False
    held = SdlcRouteSupplyFact.model_validate(held_payload)
    held_assessment = held.assess(demand)

    assert held_assessment.satisfies is False
    assert "source_acquisition_evidence_absent" in held_assessment.reason_codes

    forged_payload = dict(held_payload)
    forged_payload["can_satisfy_required_demands"] = True
    with pytest.raises(ValidationError, match="source-acquisition supply needs"):
        SdlcRouteSupplyFact.model_validate(forged_payload)


def test_blocking_reasons_fail_closed_even_if_positive_flag_is_set() -> None:
    facts = project_sdlc_route_supply_facts(include_inventory_rows=False)
    tavily = _fact(facts, "sdlc_route_supply:provider_tool.search.tavily_source_acquisition")

    blocked_payload = tavily.model_dump(mode="python")
    blocked_payload["can_satisfy_required_demands"] = True
    blocked_payload["blocking_reasons"] = ("test_blocking_reason",)
    blocked = SdlcRouteSupplyFact.model_validate(blocked_payload)

    assessment = blocked.assess(
        SdlcRouteDemand(
            role=RouteSupplyRole.SOURCE_ACQUISITION,
            source_grounding_need=SourceGroundingNeed.WEB_CURRENT,
            requires_public_claim_evidence=True,
        )
    )

    assert assessment.satisfies is False
    assert "supply_fact_held" in assessment.reason_codes
    assert "test_blocking_reason" in assessment.reason_codes


@pytest.mark.parametrize(
    ("field", "value", "reason_code"),
    (
        ("visible", False, "route_supply_hidden"),
        ("availability_state", None, "availability:missing"),
        ("availability_state", "private_only", "availability:private_only"),
        ("availability_state", "unavailable", "availability:unavailable"),
        ("health_status", None, "health_status:missing"),
        ("health_status", "stale", "health_status:stale"),
    ),
)
def test_model_copy_hard_blockers_fail_closed_in_assessment_and_summary(
    field: str,
    value: object,
    reason_code: str,
) -> None:
    facts = project_sdlc_route_supply_facts(include_inventory_rows=False)
    tavily = _fact(facts, "sdlc_route_supply:provider_tool.search.tavily_source_acquisition")
    malformed = tavily.model_copy(update={field: value, "can_satisfy_required_demands": True})

    assessment = malformed.assess(
        SdlcRouteDemand(
            role=RouteSupplyRole.SOURCE_ACQUISITION,
            source_grounding_need=SourceGroundingNeed.WEB_CURRENT,
            requires_public_claim_evidence=True,
        )
    )
    summary = bridge_policy_summary([malformed])

    assert assessment.satisfies is False
    assert reason_code in assessment.reason_codes
    assert summary["satisfying_facts"] == 0
    assert summary["held_facts"] == 1


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("availability_state", "next action: project a concrete availability"),
        ("health_status", "next action: project provider/tool health_status"),
    ),
)
def test_satisfying_fact_validator_requires_state_with_actionable_next_step(
    field: str,
    message: str,
) -> None:
    facts = project_sdlc_route_supply_facts(include_inventory_rows=False)
    tavily = _fact(facts, "sdlc_route_supply:provider_tool.search.tavily_source_acquisition")
    payload = tavily.model_dump(mode="python")
    payload.update({field: None, "can_satisfy_required_demands": True})

    with pytest.raises(ValidationError, match=message):
        SdlcRouteSupplyFact.model_validate(payload)


def test_supplied_evidence_only_blocks_fresh_current_world_demands_by_policy() -> None:
    facts = project_sdlc_route_supply_facts(include_inventory_rows=False)
    tavily = _fact(facts, "sdlc_route_supply:provider_tool.search.tavily_source_acquisition")
    supplied_only = tavily.model_copy(update={"supplied_evidence_only": True})

    assessment = supplied_only.assess(
        SdlcRouteDemand(
            role=RouteSupplyRole.SOURCE_ACQUISITION,
            source_grounding_need=SourceGroundingNeed.WEB_CURRENT,
        )
    )

    assert assessment.satisfies is False
    assert "supplied_evidence_not_fresh_current_world_evidence" in assessment.reason_codes


def test_supplied_evidence_recall_cannot_satisfy_current_world_or_public_claims() -> None:
    facts = project_sdlc_route_supply_facts(include_inventory_rows=False)
    supplied = _fact(facts, "sdlc_route_supply:provider_tool.model.litellm_supplied_evidence")

    assert supplied.role is RouteSupplyRole.SUPPLIED_EVIDENCE_RECALL
    assert supplied.supplied_evidence_only is True
    assert supplied.fresh_current_world_evidence_allowed is False
    assert supplied.public_claim_evidence_allowed is False

    assessment = supplied.assess(
        SdlcRouteDemand(
            role=RouteSupplyRole.SUPPLIED_EVIDENCE_RECALL,
            source_grounding_need=SourceGroundingNeed.WEB_CURRENT,
            requires_public_claim_evidence=True,
        )
    )

    assert assessment.satisfies is False
    assert "fresh_current_world_evidence_absent" in assessment.reason_codes
    assert "source_acquisition_capability_absent" in assessment.reason_codes
    assert "supplied_evidence_not_public_claim_evidence" in assessment.reason_codes

    malformed_payload = supplied.model_dump(mode="python")
    malformed_payload.update(
        {
            "supplied_evidence_only": False,
            "source_acquisition_capable": True,
            "source_acquisition_evidence_refs": ("test:malformed-source-evidence",),
            "fresh_current_world_evidence_allowed": True,
            "public_claim_evidence_allowed": True,
            "public_claim_outcome_refs": ("test:malformed-public-claim",),
            "can_satisfy_required_demands": True,
        }
    )
    with pytest.raises(
        ValidationError,
        match="supplied-evidence recall cannot satisfy fresh/public claims",
    ):
        SdlcRouteSupplyFact.model_validate(malformed_payload)

    malformed = supplied.model_copy(update=malformed_payload)
    malformed_assessment = malformed.assess(
        SdlcRouteDemand(
            role=RouteSupplyRole.SUPPLIED_EVIDENCE_RECALL,
            source_grounding_need=SourceGroundingNeed.WEB_CURRENT,
            requires_public_claim_evidence=True,
        )
    )

    assert malformed.supplied_evidence_only is False
    assert malformed.fresh_current_world_evidence_allowed is True
    assert malformed.public_claim_evidence_allowed is True
    assert malformed_assessment.satisfies is False
    assert (
        "supplied_evidence_recall_not_fresh_current_world_evidence"
        in malformed_assessment.reason_codes
    )
    assert "supplied_evidence_recall_not_public_claim_evidence" in malformed_assessment.reason_codes


def test_publication_egress_remains_held_without_authority_evidence_and_receipts() -> None:
    facts = project_sdlc_route_supply_facts(include_inventory_rows=False)
    youtube = _fact(facts, "sdlc_route_supply:provider_tool.publication.youtube_live")

    assert youtube.role is RouteSupplyRole.PUBLICATION_EGRESS
    assert youtube.publication_egress_allowed is False
    assert youtube.rights_evidence_refs
    assert youtube.privacy_redaction_evidence_refs

    assessment = youtube.assess(
        SdlcRouteDemand(
            role=RouteSupplyRole.PUBLICATION_EGRESS,
            requires_publication_egress=True,
        )
    )

    assert assessment.satisfies is False
    assert "publication_egress_held" in assessment.reason_codes
    assert "publication_authority_absent" in assessment.reason_codes
    assert "publication_rights_evidence_absent" in assessment.reason_codes
    assert "publication_privacy_redaction_evidence_absent" in assessment.reason_codes
    assert "publication_explicit_receipts_absent" in assessment.reason_codes


def test_provider_gateway_carries_spend_posture_and_is_not_routine_fallback() -> None:
    gateway = project_provider_gateway_supply_facts()[0]

    assert gateway.role is RouteSupplyRole.PROVIDER_GATEWAY
    assert gateway.provider_spend_required is True
    assert gateway.provider_spend_posture in {
        ProviderSpendPosture.SPEND_BLOCKED,
        ProviderSpendPosture.SPEND_REQUIRES_RECEIPT,
        ProviderSpendPosture.SPEND_EVIDENCED,
    }
    assert gateway.capacity_pool == "api_paid_spend"
    assert gateway.paid_provider
    assert gateway.routine_fallback_allowed is False

    routine_fallback = gateway.assess(
        SdlcRouteDemand(
            role=RouteSupplyRole.PROVIDER_GATEWAY,
            provider_spend_authorized=True,
            provider_budget_evidence_refs=("budget:explicit-test",),
            routine_fallback=True,
        )
    )
    no_spend_authority = gateway.assess(SdlcRouteDemand(role=RouteSupplyRole.PROVIDER_GATEWAY))

    assert routine_fallback.satisfies is False
    assert "provider_gateway_routine_fallback_forbidden" in routine_fallback.reason_codes
    assert no_spend_authority.satisfies is False
    assert "provider_spend_authority_absent" in no_spend_authority.reason_codes


def test_evidenced_authorized_provider_gateway_can_satisfy_route_demand() -> None:
    facts = project_provider_gateway_supply_facts(
        platform_registry=_registry_with_active_provider_gateway()
    )
    gateway = _fact(facts, "sdlc_route_supply:platform:api.headless.provider_gateway")

    assert gateway.can_satisfy_required_demands is True
    assert gateway.availability_state == "active"
    assert gateway.provider_spend_posture is ProviderSpendPosture.SPEND_EVIDENCED

    assessment = gateway.assess(
        SdlcRouteDemand(
            role=RouteSupplyRole.PROVIDER_GATEWAY,
            provider_spend_authorized=True,
            provider_budget_evidence_refs=("budget:test-approved",),
        )
    )

    assert assessment.satisfies is True
    assert assessment.reason_codes == ()
    assert "test:provider-gateway:quota:observed" in assessment.evidence_refs
    assert "budget:test-approved" in assessment.evidence_refs


def test_provider_tool_mismatch_remains_visible_but_cannot_satisfy() -> None:
    fixtures = load_provider_tool_health_fixtures()
    inventory = load_capability_classification_inventory()
    tavily_route = next(
        route
        for route in fixtures.routes
        if route.route_id == "provider_tool.search.tavily_source_acquisition"
    )
    wrong_inventory_row = inventory.require_row("capability.model.litellm_supplied_evidence")

    fact = project_provider_tool_route_supply_fact(
        tavily_route,
        inventory_row=wrong_inventory_row,
    )

    assert fact.visible is True
    assert fact.can_satisfy_required_demands is False
    assert "classification_route_family_mismatch" in fact.blocking_reasons
    assert "classification_source_acquisition_mismatch" in fact.blocking_reasons
    assert "classification_public_claim_policy_mismatch" in fact.blocking_reasons


def test_tool_provider_outcomes_attach_without_world_truth_authority() -> None:
    facts = project_sdlc_route_supply_facts(include_inventory_rows=False)
    tavily = _fact(facts, "sdlc_route_supply:provider_tool.search.tavily_source_acquisition")

    assert tavily.outcome_refs == ("tpo:search.tavily:source-acquired",)
    assert tavily.fresh_source_outcome_refs == ("tpo:search.tavily:source-acquired",)
    assert tavily.public_claim_outcome_refs == ("tpo:search.tavily:source-acquired",)
    assert tavily.world_truth_witnessed is False
    assert "tool_provider_outcomes_are_not_world_truth" in tavily.warnings
