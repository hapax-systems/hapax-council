from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.route_metadata_schema import (
    AuthorityLevel,
    FreshnessState,
    MutationSurface,
    QualityFloor,
    RouteMetadata,
    RouteMetadataStatus,
    assess_route_metadata,
    build_demand_vector,
    check_demand_vector_freshness,
    validate_route_metadata,
)


def _explicit_metadata() -> dict[str, object]:
    return {
        "route_metadata_schema": 1,
        "quality_floor": "frontier_required",
        "authority_level": "authoritative",
        "mutation_surface": "source",
        "mutation_scope_refs": ["isap:CASE-CAPACITY-ROUTING-001/ROUTE-METADATA-SCHEMA"],
        "risk_flags": {
            "governance_sensitive": True,
            "privacy_or_secret_sensitive": False,
            "public_claim_sensitive": False,
            "aesthetic_theory_sensitive": False,
            "audio_or_live_egress_sensitive": False,
            "provider_billing_sensitive": False,
        },
        "context_shape": {
            "codebase_locality": "module",
            "vault_context_required": True,
            "external_docs_required": False,
            "currentness_required": False,
        },
        "verification_surface": {
            "deterministic_tests": ["uv run pytest tests/shared/test_route_metadata_schema.py"],
            "static_checks": ["uv run ruff check shared/route_metadata_schema.py"],
            "runtime_observation": [],
            "operator_only": False,
        },
        "route_constraints": {
            "preferred_platforms": ["codex"],
            "allowed_platforms": [],
            "prohibited_platforms": ["jr"],
            "required_mode": "headless",
            "required_profile": "full",
        },
        "review_requirement": {
            "support_artifact_allowed": False,
            "independent_review_required": False,
            "authoritative_acceptor_profile": None,
        },
    }


def test_full_explicit_route_metadata_validates() -> None:
    metadata = validate_route_metadata(_explicit_metadata())

    assert metadata.quality_floor == QualityFloor.FRONTIER_REQUIRED
    assert metadata.authority_level == AuthorityLevel.AUTHORITATIVE
    assert metadata.mutation_surface == MutationSurface.SOURCE
    assert metadata.risk_flags.governance_sensitive is True


def test_conservative_derivation_from_existing_task_fields() -> None:
    assessment = assess_route_metadata(
        {
            "type": "cc-task",
            "task_id": "source-task",
            "title": "Source Task",
            "kind": "implementation",
            "risk_tier": "T1",
            "authority_case": "CASE-TEST-001",
            "parent_spec": "/tmp/spec.md",
            "tags": ["governance"],
        }
    )

    assert assessment.status == RouteMetadataStatus.DERIVED
    assert assessment.metadata is not None
    assert assessment.metadata.quality_floor == QualityFloor.FRONTIER_REQUIRED
    assert assessment.metadata.mutation_surface == MutationSurface.SOURCE
    assert assessment.metadata.risk_flags.governance_sensitive is True


def test_missing_quality_floor_is_hold_not_permissive() -> None:
    assessment = assess_route_metadata(
        {
            "type": "cc-task",
            "task_id": "underspecified",
            "title": "Underspecified Task",
            "authority_case": "CASE-TEST-001",
        }
    )

    assert assessment.status == RouteMetadataStatus.HOLD
    assert "quality_floor" in assessment.missing_fields
    assert "missing_quality_floor" in assessment.hold_reasons
    assert assessment.dispatchable is False


def test_mutation_surface_unknown_is_hold_condition() -> None:
    assessment = assess_route_metadata(
        {
            "type": "cc-task",
            "task_id": "risk-known-surface-unknown",
            "title": "Risk Known Surface Unknown",
            "risk_tier": "T1",
            "authority_case": "CASE-TEST-001",
        }
    )

    assert assessment.status == RouteMetadataStatus.HOLD
    assert "mutation_surface" in assessment.missing_fields
    assert "missing_mutation_surface" in assessment.hold_reasons


def test_malformed_explicit_route_metadata_reports_validation_errors() -> None:
    assessment = assess_route_metadata(
        {
            "route_metadata_schema": 1,
            "quality_floor": "spark_is_fine",
            "authority_level": "authoritative",
            "mutation_surface": "source",
        }
    )

    assert assessment.status == RouteMetadataStatus.MALFORMED
    assert assessment.validation_errors


def test_support_artifact_requires_independent_frontier_review() -> None:
    payload = {
        "route_metadata_schema": 1,
        "quality_floor": "frontier_review_required",
        "authority_level": "support_non_authoritative",
        "mutation_surface": "vault_docs",
        "review_requirement": {
            "support_artifact_allowed": True,
            "independent_review_required": True,
            "authoritative_acceptor_profile": "frontier_full",
        },
    }

    metadata = RouteMetadata.model_validate(payload)
    assert metadata.quality_floor == QualityFloor.FRONTIER_REVIEW_REQUIRED

    payload["authority_level"] = "authoritative"
    with pytest.raises(ValidationError, match="cannot be authoritative directly"):
        RouteMetadata.model_validate(payload)


def test_demand_vector_hashes_frontmatter_and_source_refs(tmp_path) -> None:
    task_note = tmp_path / "task.md"
    parent_spec = tmp_path / "spec.md"
    parent_spec.write_text("---\ncase_id: CASE-TEST-001\n---\n", encoding="utf-8")
    task_note.write_text("---\ntask_id: source-task\n---\n", encoding="utf-8")
    frontmatter = {
        **_explicit_metadata(),
        "task_id": "source-task",
        "authority_case": "CASE-TEST-001",
        "parent_spec": str(parent_spec),
        "priority": "p0",
        "wsjf": 14.0,
    }

    demand = build_demand_vector(frontmatter, note_path=task_note)

    assert demand.demand_vector_schema == 1
    assert demand.routing_model_version == "capacity-dimensional-v1"
    assert demand.work_item.frontmatter_hash.startswith("sha256:")
    assert demand.work_item.authority_case == "CASE-TEST-001"
    assert demand.task_demand.authority_class == "source_mutation"
    assert {ref.source_id for ref in demand.source_refs} >= {"task_note", "parent_spec"}


def test_demand_vector_freshness_stales_when_frontmatter_changes(tmp_path) -> None:
    task_note = tmp_path / "task.md"
    task_note.write_text("---\ntask_id: source-task\n---\n", encoding="utf-8")
    frontmatter = {
        **_explicit_metadata(),
        "task_id": "source-task",
        "authority_case": "CASE-TEST-001",
        "title": "Original",
    }
    demand = build_demand_vector(frontmatter, note_path=task_note)

    freshness = check_demand_vector_freshness(
        demand,
        {**frontmatter, "title": "Changed"},
        note_path=task_note,
    )

    assert freshness.freshness_state is FreshnessState.STALE
    assert "frontmatter_hash_changed" in freshness.stale_reasons
