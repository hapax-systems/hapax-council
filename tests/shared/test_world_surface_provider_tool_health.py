"""Tests for provider/tool route health WCS projection."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from shared.capability_classification_inventory import load_capability_classification_inventory
from shared.grounding_provider_router import provider_by_id
from shared.world_surface_health import (
    AuthorityCeiling,
    HealthDimensionId,
    HealthDimensionState,
    HealthStatus,
    PublicPrivatePosture,
    SurfaceFamily,
)
from shared.world_surface_provider_tool_health import (
    PROVIDER_TOOL_HEALTH_FIXTURES,
    REQUIRED_PROVIDER_TOOL_FAMILIES,
    ProviderToolHealthFixtureSet,
    SuppliedEvidenceMode,
    load_provider_tool_health_fixtures,
    project_provider_tool_health_records,
)


def _json(path: Path = PROVIDER_TOOL_HEALTH_FIXTURES) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


def _dimension_state(record, dimension_id: HealthDimensionId) -> HealthDimensionState:
    dimensions = {dimension.dimension: dimension for dimension in record.health_dimensions}
    return dimensions[dimension_id].state


def test_fixture_rows_are_seeded_from_capability_classification_inventory() -> None:
    fixture_set = load_provider_tool_health_fixtures()
    inventory = load_capability_classification_inventory()

    assert {
        route.route_family.value for route in fixture_set.routes
    } >= REQUIRED_PROVIDER_TOOL_FAMILIES
    for route in fixture_set.routes:
        row = inventory.require_row(route.classification_row_id)

        assert route.route_family.value == row.surface_family.value
        assert route.availability_state is row.availability_state
        assert route.source_acquisition_capability is row.can_acquire_sources
        assert route.public_claim_policy is row.public_claim_policy
        assert route.authority_ceiling.value == row.claim_authority_ceiling.value
        assert row.evidence_ref in route.source_refs
        assert row.producer in route.producer_refs
        assert set(row.consumer_refs).issubset(route.consumer_refs)


def test_grounding_provider_registry_refs_are_checked_for_model_routes() -> None:
    fixture_set = load_provider_tool_health_fixtures()
    providers = provider_by_id()
    routes = {route.route_id: route for route in fixture_set.routes}
    local = routes["provider_tool.model.litellm_supplied_evidence"]

    assert local.provider_registry_id == "local_supplied_evidence_command_r"
    provider = providers[local.provider_registry_id]
    assert provider.requires_supplied_evidence is True
    assert provider.can_satisfy_open_world_claims is False
    assert local.supplied_evidence_mode is SuppliedEvidenceMode.SUPPLIED_EVIDENCE_ONLY


def test_projected_rows_are_bounded_provider_tool_wcs_records() -> None:
    records = project_provider_tool_health_records()

    assert records
    for record in records:
        assert record.surface_family is SurfaceFamily.PROVIDER_TOOL
        assert record.public_claim_allowed is False
        assert record.monetization_allowed is False
        assert record.claimable_health is False
        assert record.claimability.public_live is False
        assert record.claimability.grounded is False
        assert record.satisfies_claimable_health() is False
        assert "provider_tool_route_health_does_not_grant_public_authority" in record.warnings


def test_source_acquisition_claims_require_actual_acquisition_evidence() -> None:
    payload = _json()
    bad = deepcopy(payload)
    route = next(
        item
        for item in bad["routes"]
        if item["route_id"] == "provider_tool.search.tavily_source_acquisition"
    )
    route["source_acquisition_evidence_refs"] = []

    with pytest.raises(ValidationError):
        ProviderToolHealthFixtureSet.model_validate(bad)


def test_supplied_evidence_model_does_not_project_source_acquisition() -> None:
    records = {
        record.surface_id.removesuffix(".health"): record
        for record in project_provider_tool_health_records()
    }
    local = records["provider_tool.model.litellm_supplied_evidence"]

    assert local.status is HealthStatus.PRIVATE_ONLY
    assert local.authority_ceiling is AuthorityCeiling.INTERNAL_ONLY
    assert local.public_private_posture is PublicPrivatePosture.PRIVATE_ONLY
    assert _dimension_state(local, HealthDimensionId.WORLD_WITNESS) is (
        HealthDimensionState.NOT_APPLICABLE
    )
    assert _dimension_state(local, HealthDimensionId.CLAIM_AUTHORITY) is (
        HealthDimensionState.BLOCKED
    )


def test_public_gate_routes_are_inspectable_but_not_public_authority() -> None:
    records = {
        record.surface_id.removesuffix(".health"): record
        for record in project_provider_tool_health_records()
    }
    tavily = records["provider_tool.search.tavily_source_acquisition"]
    youtube = records["provider_tool.publication.youtube_live"]

    assert tavily.status is HealthStatus.HEALTHY
    assert tavily.authority_ceiling is AuthorityCeiling.PUBLIC_GATE_REQUIRED
    assert tavily.public_claim_allowed is False
    assert _dimension_state(tavily, HealthDimensionId.WORLD_WITNESS) is HealthDimensionState.PASS
    assert _dimension_state(tavily, HealthDimensionId.EGRESS_PUBLIC) is (
        HealthDimensionState.MISSING
    )
    assert _dimension_state(tavily, HealthDimensionId.PUBLIC_EVENT_POLICY) is (
        HealthDimensionState.MISSING
    )

    assert youtube.status is HealthStatus.DEGRADED
    assert youtube.public_claim_allowed is False
    assert "publication_route_health_not_egress_clearance" in youtube.blocking_reasons


def test_unavailable_publication_route_remains_visible_and_blocked() -> None:
    records = {
        record.surface_id.removesuffix(".health"): record
        for record in project_provider_tool_health_records()
    }
    soundcloud = records["provider_tool.publication.soundcloud_unavailable"]

    assert soundcloud.status is HealthStatus.BLOCKED
    assert soundcloud.public_claim_allowed is False
    assert soundcloud.claimable_health is False
    assert "route_unavailable" in soundcloud.blocking_reasons
    assert _dimension_state(soundcloud, HealthDimensionId.PRODUCER_EXISTS) is (
        HealthDimensionState.FAIL
    )
    assert _dimension_state(soundcloud, HealthDimensionId.PRIVACY_CONSENT) is (
        HealthDimensionState.FAIL
    )


def test_source_acquisition_flag_must_match_inventory_row() -> None:
    payload = _json()
    bad = deepcopy(payload)
    route = next(
        item
        for item in bad["routes"]
        if item["route_id"] == "provider_tool.model.litellm_supplied_evidence"
    )
    route["source_acquisition_capability"] = True
    route["source_acquisition_evidence_refs"] = ["forged:source-acquisition"]

    with pytest.raises(ValidationError):
        ProviderToolHealthFixtureSet.model_validate(bad)
