"""Tests for the formal semantic recruitment row contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.semantic_recruitment import (
    AUTHORITY_ORDER,
    CONSENT_ORDER,
    CONTENT_RISK_ORDER,
    MONETIZATION_RISK_ORDER,
    ClaimType,
    ConsentLabel,
    ContentRisk,
    LifecycleState,
    MonetizationRisk,
    SemanticKind,
    SemanticLevel,
    SemanticRecruitmentError,
    SemanticRecruitmentFixtureSet,
    SemanticRecruitmentRow,
    SplitMergeDecisionKind,
    lattice_allows,
    load_semantic_recruitment_fixture_set,
    semantic_recruitment_rows_by_id,
)


def _fixtures() -> SemanticRecruitmentFixtureSet:
    return load_semantic_recruitment_fixture_set()


def _row(row_id: str) -> SemanticRecruitmentRow:
    return _fixtures().require_row(row_id)


def test_core_substrate_instances_not_recruitable() -> None:
    core = _row("substrate.reverie.core_vocabulary_graph")

    assert core.core_substrate_instance
    assert SemanticKind.SUBSTRATE in core.kind
    assert SemanticKind.CAPABILITY not in core.kind
    assert core.recruitable is False
    assert core.projects_recruitable_capability is False


def test_satellite_templates_distinct_from_core_instances() -> None:
    core = _row("substrate.reverie.core_vocabulary_graph")
    satellite = _row("capability.visual.sierpinski_satellite_template")

    assert core.core_substrate_instance
    assert satellite.core_substrate_instance is False
    assert satellite.recruitable
    assert {SemanticKind.CAPABILITY, SemanticKind.AFFORDANCE} <= satellite.kind
    assert satellite.dispatch_contract.intent_family == "content.visual"


def test_every_recruitable_row_has_kind_level_description_and_governance() -> None:
    for row in _fixtures().recruitable_rows():
        assert {SemanticKind.CAPABILITY, SemanticKind.AFFORDANCE} <= row.kind
        assert row.abstraction_level in {SemanticLevel.L1, SemanticLevel.L2}
        assert row.primary_description
        assert row.domain_tags
        assert row.evidence_refs
        assert row.witness_contract_id
        assert row.content_risk is not ContentRisk.UNKNOWN
        assert row.monetization_risk is not MonetizationRisk.UNKNOWN
        assert row.projection is not None


def test_description_rejects_implementation_terms() -> None:
    payload = _row("capability.knowledge.public_source_retrieval").model_dump(mode="json")
    payload["semantic_descriptions"][0]["text"] = (
        "Retrieve Tavily tool results for current claims while preserving citation freshness "
        "and evidence."
    )

    with pytest.raises(ValidationError, match="implementation terms"):
        SemanticRecruitmentRow.model_validate(payload)


def test_multi_domain_membership_without_duplicate_rows() -> None:
    fixtures = _fixtures()
    satellite = fixtures.require_row("capability.visual.sierpinski_satellite_template")

    assert {tag.domain for tag in satellite.domain_tags} == {"studio", "visual"}
    assert len(fixtures.by_id()) == len(fixtures.rows)
    assert list(fixtures.by_id()).count("capability.visual.sierpinski_satellite_template") == 1


def test_family_tags_are_structured_not_prefix_only() -> None:
    satellite = _row("capability.visual.sierpinski_satellite_template")
    family = satellite.family_tags[0]

    assert family.family == "visual_content"
    assert family.intent_binding == "content.visual"
    assert family.dispatch_required is True
    assert satellite.dispatch_contract.route_by_family_only is True


def test_provider_swap_preserves_affordance_identity() -> None:
    fixtures = _fixtures()
    row = fixtures.require_row("capability.knowledge.public_source_retrieval")
    decision = next(
        item
        for item in fixtures.split_merge_decisions
        if item.decision_id == "decision.provider_swap.source_retrieval_merge"
    )

    assert len(row.provider_refs) == 2
    assert {alias.alias for alias in row.aliases} >= {
        "knowledge.web_search",
        "knowledge.wikipedia",
    }
    assert decision.decision is SplitMergeDecisionKind.MERGE
    assert decision.canonical_row_id == row.row_id
    assert "provider_swap" in decision.dimensions


def test_split_when_privacy_freshness_authority_or_failure_differs() -> None:
    fixtures = _fixtures()
    camera_decision = next(
        item
        for item in fixtures.split_merge_decisions
        if item.decision_id == "decision.camera.perspective_split"
    )
    audio_decision = next(
        item
        for item in fixtures.split_merge_decisions
        if item.decision_id == "decision.audio.route_role_split"
    )

    assert camera_decision.decision is SplitMergeDecisionKind.SPLIT
    assert {"privacy", "freshness", "public_aperture"} <= set(camera_decision.dimensions)
    assert len(camera_decision.row_ids) == 3
    assert audio_decision.decision is SplitMergeDecisionKind.SPLIT
    assert {"privacy", "public_egress", "failure_mode"} <= set(audio_decision.dimensions)


def test_consent_content_monetization_claim_lattices_fail_closed() -> None:
    assert lattice_allows(ConsentLabel.OPERATOR_SELF, ConsentLabel.PUBLIC_BROADCAST, CONSENT_ORDER)
    assert not lattice_allows(
        ConsentLabel.PUBLIC_BROADCAST, ConsentLabel.OPERATOR_SELF, CONSENT_ORDER
    )
    assert (
        CONTENT_RISK_ORDER[ContentRisk.TIER_4_RISKY] > CONTENT_RISK_ORDER[ContentRisk.TIER_0_OWNED]
    )
    assert (
        MONETIZATION_RISK_ORDER[MonetizationRisk.HIGH]
        > MONETIZATION_RISK_ORDER[MonetizationRisk.LOW]
    )
    assert (
        AUTHORITY_ORDER[_row("capability.audio.normalized_broadcast_route").authority_ceiling] > 0
    )

    payload = _row("capability.audio.normalized_broadcast_route").model_dump(mode="json")
    payload["monetization_risk"] = "high"
    with pytest.raises(ValidationError, match="high monetization risk"):
        SemanticRecruitmentRow.model_validate(payload)

    payload = _row("capability.audio.normalized_broadcast_route").model_dump(mode="json")
    payload["authority_ceiling"] = "internal_only"
    with pytest.raises(ValidationError, match="public_gate_required"):
        SemanticRecruitmentRow.model_validate(payload)


def test_batch_and_single_projection_payload_equivalence() -> None:
    fixtures = _fixtures()
    single = fixtures.qdrant_payloads_for_single_indexing()
    batch = fixtures.qdrant_payloads_for_batch_indexing()

    assert single == batch
    payload = single["capability.audio.normalized_broadcast_route"]
    assert payload["wcs_row_id"] == "capability.audio.normalized_broadcast_route"
    assert payload["domain_tags"]
    assert payload["family_tags"]
    assert payload["lifecycle"] == "active"
    assert payload["content_risk"] == "tier_0_owned"
    assert payload["monetization_risk"] == "low"
    assert payload["witness_contract_id"] == "witness.audio.broadcast_route_safe"


def test_decommissioned_surface_cannot_project_recruitable_capability() -> None:
    row = _row("surface.tauri_logos.decommissioned_frame_server")

    assert row.lifecycle is LifecycleState.DECOMMISSIONED
    assert row.replacement_row_id == "capability.visual.logos_api_frame_surface"
    assert row.projects_recruitable_capability is False
    with pytest.raises(SemanticRecruitmentError, match="cannot project"):
        row.to_capability_record()


def test_outcome_learning_requires_witness_identity_for_public_success() -> None:
    public_rows = [
        row
        for row in _fixtures().recruitable_rows()
        if ClaimType.PUBLIC_CLAIM in row.claim_types_allowed
    ]
    assert public_rows
    for row in public_rows:
        assert row.witness_contract_id
        assert row.outcome_learning_policy.value == "public_witness_required"

    payload = public_rows[0].model_dump(mode="json")
    payload["witness_contract_id"] = None
    with pytest.raises(ValidationError, match="witness"):
        SemanticRecruitmentRow.model_validate(payload)


def test_existing_capability_names_have_alias_migration_maps() -> None:
    source = _row("capability.knowledge.public_source_retrieval")
    decommissioned = _row("surface.tauri_logos.decommissioned_frame_server")

    assert {alias.alias for alias in source.aliases} >= {
        "knowledge.web_search",
        "knowledge.wikipedia",
    }
    assert decommissioned.aliases[0].state.value == "decommissioned"


def test_director_snapshots_can_reference_row_ids_and_witness_ids() -> None:
    payloads = _fixtures().qdrant_payloads_for_single_indexing()

    for row_id, payload in payloads.items():
        assert payload["wcs_row_id"] == row_id
        assert payload["semantic_version"] == 1
        assert payload["witness_contract_id"]
        assert payload["relation_predicates"]


def test_single_projection_to_capability_record_carries_risk_metadata() -> None:
    row = _row("capability.knowledge.public_source_retrieval")
    record = row.to_capability_record()

    assert record.name == "knowledge.public_claim_sources"
    assert record.description == row.primary_description
    assert record.operational.public_capable is True
    assert record.operational.requires_network is True
    assert record.operational.consent_required is False
    assert record.operational.consent_person_id is None
    assert record.operational.consent_data_category is None
    assert record.operational.content_risk == "tier_1_platform_cleared"
    assert record.operational.monetization_risk == "low"
    assert record.operational.rights_ref == "rights:provider-public-source-terms"


def test_interpersonal_consent_projection_requires_explicit_scope() -> None:
    payload = _row("capability.camera.raw_workspace_observation").model_dump(mode="json")
    payload["privacy_label"] = "person_adjacent"
    payload["consent_label"] = "identifiable_person"
    payload["required_clearance"] = "identifiable_person"

    with pytest.raises(ValidationError, match="interpersonal consent projections"):
        SemanticRecruitmentRow.model_validate(payload)

    payload["projection"]["consent_person_id"] = "guest"
    payload["projection"]["consent_data_category"] = "video"
    row = SemanticRecruitmentRow.model_validate(payload)
    record = row.to_capability_record()

    assert record.operational.consent_required is True
    assert record.operational.consent_person_id == "guest"
    assert record.operational.consent_data_category == "video"


def test_semantic_rows_by_id_helper_is_fail_closed() -> None:
    rows = semantic_recruitment_rows_by_id()

    assert rows["capability.visual.logos_api_frame_surface"].recruitable is True
    with pytest.raises(KeyError):
        _fixtures().require_row("missing.row")
