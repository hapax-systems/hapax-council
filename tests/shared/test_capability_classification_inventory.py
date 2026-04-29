"""Tests for the capability classification inventory seed contract."""

from __future__ import annotations

import json

import pytest

from agents.hapax_daimonion.tool_affordances import TOOL_AFFORDANCES
from shared.capability_classification_inventory import (
    AvailabilityState,
    CapabilityClassificationError,
    PublicClaimPolicy,
    SurfaceFamily,
    build_seed_inventory,
    load_capability_classification_inventory,
    validate_daimonion_tool_affordance_parity,
)
from shared.semantic_recruitment import (
    AuthorityCeiling,
    ClaimType,
    ConsentLabel,
    LifecycleState,
    SemanticRecruitmentRow,
)
from shared.voice_tier import TIER_NAMES, VoiceTier


def _inventory():
    return load_capability_classification_inventory()


def _canonical_inventory_dump(payload: dict) -> dict:
    for row in payload["rows"]:
        row["kind"] = sorted(row["kind"])
    return payload


def test_inventory_rows_are_semantic_recruitment_rows() -> None:
    inventory = _inventory()

    assert inventory.rows
    for row in inventory.rows:
        assert isinstance(row, SemanticRecruitmentRow)
        assert row.semantic_description == row.primary_description
        assert row.evidence_ref in row.evidence_refs
        assert row.concrete_interface in row.concrete_interfaces
        assert row.recruitment_family in {tag.family for tag in row.family_tags}


def test_seed_inventory_covers_requested_surface_families() -> None:
    inventory = _inventory()
    families = {row.surface_family for row in inventory.rows}

    assert set(SurfaceFamily) <= families
    assert len(inventory.rows_for_family(SurfaceFamily.TOOL_SCHEMA)) >= 3
    assert inventory.rows_for_family(SurfaceFamily.MCP_TOOL)
    assert inventory.rows_for_family(SurfaceFamily.LOCAL_API)
    assert inventory.rows_for_family(SurfaceFamily.DOCKER_CONTAINER)


def test_seed_builder_and_json_fixture_stay_in_parity() -> None:
    built = _canonical_inventory_dump(build_seed_inventory().model_dump(mode="json", by_alias=True))
    loaded = _canonical_inventory_dump(_inventory().model_dump(mode="json", by_alias=True))

    assert loaded == built


def test_tool_schema_and_affordance_names_have_one_to_one_parity() -> None:
    validate_daimonion_tool_affordance_parity()


def test_missing_scene_detail_tools_have_affordances_and_inventory_rows() -> None:
    inventory = _inventory()
    affordance_names = {name for name, _description in TOOL_AFFORDANCES}

    for name in ("query_person_details", "query_object_motion", "query_scene_state"):
        assert name in affordance_names
        row = inventory.require_row(f"capability.tool.{name}")
        assert row.surface_family is SurfaceFamily.TOOL_SCHEMA
        assert row.availability_state is AvailabilityState.PRIVATE_ONLY
        assert ClaimType.PUBLIC_CLAIM not in row.claim_types_allowed


def test_public_claim_rows_fail_closed_without_witnesses() -> None:
    inventory = _inventory()

    for row in inventory.rows:
        if row.public_claim_policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED:
            assert row.authority_ceiling is AuthorityCeiling.PUBLIC_GATE_REQUIRED
            assert row.required_clearance is ConsentLabel.PUBLIC_BROADCAST
            assert row.witness_contract_id
            assert row.evidence_refs
            assert ClaimType.PUBLIC_CLAIM in row.claim_types_allowed
        else:
            assert ClaimType.PUBLIC_CLAIM not in row.claim_types_allowed


def test_voice_tiers_are_adapted_with_monetization_ceilings() -> None:
    inventory = _inventory()
    tier_rows = {
        row.row_id: row for row in inventory.rows if row.recruitment_family == "voice_tier"
    }

    expected_ids = {
        f"capability.voice_tier.{TIER_NAMES[tier].replace('-', '_')}" for tier in VoiceTier
    }
    assert set(tier_rows) == expected_ids
    assert tier_rows["capability.voice_tier.granular_wash"].monetization_risk.value == "medium"

    obliterated = tier_rows["capability.voice_tier.obliterated"]
    assert obliterated.monetization_risk.value == "high"
    assert obliterated.recruitable is False
    assert obliterated.lifecycle is LifecycleState.BLOCKED
    assert not obliterated.projects_recruitable_capability


def test_audio_routes_distinguish_raw_private_broadcast_and_remap() -> None:
    inventory = _inventory()

    raw = inventory.require_row("capability.audio.l12_raw_hardware")
    normalized = inventory.require_row("capability.audio.broadcast_master_normalized")
    remap = inventory.require_row("capability.audio.obs_broadcast_remap")

    assert raw.availability_state is AvailabilityState.PRIVATE_ONLY
    assert raw.public_claim_policy is PublicClaimPolicy.NO_PUBLIC_CLAIM
    assert normalized.public_claim_policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED
    assert remap.public_claim_policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED
    assert {
        raw.witness_contract_id,
        normalized.witness_contract_id,
        remap.witness_contract_id,
    } == {
        "witness.audio.l12_forward_invariant",
        "witness.audio.broadcast_loudness_safe",
        "witness.audio.obs_remap_not_raw",
    }


def test_remote_provider_roles_distinguish_source_supplied_publication_and_sync() -> None:
    inventory = _inventory()
    source = inventory.require_row("capability.search.tavily_source_acquisition")
    model = inventory.require_row("capability.model.litellm_supplied_evidence")
    publication = inventory.require_row("capability.publication.youtube_live")
    storage = inventory.require_row("capability.storage.backblaze_restic_sync")

    assert source.can_acquire_sources
    assert not source.supplied_evidence_only
    assert model.supplied_evidence_only
    assert not model.can_acquire_sources
    assert publication.public_claim_policy is PublicClaimPolicy.PUBLIC_GATE_REQUIRED
    assert storage.public_claim_policy is PublicClaimPolicy.NO_PUBLIC_CLAIM


def test_stale_unavailable_and_decommissioned_rows_do_not_project() -> None:
    inventory = _inventory()
    stale = inventory.require_row("state.vision.classifications_stale")
    unavailable = inventory.require_row("provider.soundcloud.publication_unavailable")
    tauri = inventory.require_row("surface.tauri_logos.decommissioned_frame_server")

    assert stale.availability_state is AvailabilityState.STALE
    assert unavailable.availability_state is AvailabilityState.UNAVAILABLE
    assert tauri.availability_state is AvailabilityState.DECOMMISSIONED
    assert tauri.replacement_row_id == "capability.visual.logos_api_frame_surface"
    for row in (stale, unavailable, tauri):
        assert not row.projects_recruitable_capability


def test_director_and_wcs_read_models_expose_available_and_blocked_postures() -> None:
    inventory = _inventory()
    snapshot = inventory.director_snapshot_rows()
    projections = inventory.wcs_projection_payloads()

    snapshot_states = {row["availability_state"] for row in snapshot}
    assert {
        "available",
        "private_only",
        "stale",
        "unavailable",
        "decommissioned",
    } <= snapshot_states
    assert "capability.visual.logos_api_frame_surface" in projections
    assert "surface.tauri_logos.decommissioned_frame_server" not in projections
    assert projections["capability.search.tavily_source_acquisition"]["public_capable"] is True


def test_inventory_loader_fails_closed_on_unknown_rows(tmp_path) -> None:
    inventory = _inventory().model_dump(mode="json", by_alias=True)
    inventory["rows"][0]["replacement_row_id"] = "missing.row"
    path = tmp_path / "bad-inventory.json"
    path.write_text(json.dumps(inventory), encoding="utf-8")

    with pytest.raises(CapabilityClassificationError):
        load_capability_classification_inventory(path)
