"""Tests for programme boundary WCS/evidence adapter projections."""

from __future__ import annotations

from datetime import UTC, datetime

from shared.content_programme_feedback_ledger import build_feedback_event_from_run_envelope
from shared.content_programme_run_store import build_fixture_envelope
from shared.format_public_event_adapter import adapt_format_boundary_to_public_event
from shared.programme_boundary_wcs_evidence_adapter import (
    CONTENT_PROGRAMME_FEEDBACK_LEDGER,
    FORMAT_PUBLIC_EVENT_ADAPTER,
    load_programme_boundary_wcs_evidence_fixtures,
    project_boundary_wcs_evidence,
    project_fixture,
)

GENERATED_AT = datetime(2026, 4, 29, 14, 0, tzinfo=UTC)


def test_fixture_projections_match_expected_contract() -> None:
    fixture_set = load_programme_boundary_wcs_evidence_fixtures()

    for fixture in fixture_set.fixtures:
        projection = project_fixture(fixture)

        assert projection.projection_state == fixture.expected.projection_state
        assert (
            projection.public_conversion.format_public_event_adapter_ready
            is fixture.expected.format_public_event_adapter_ready
        )
        for reason in fixture.expected.blocker_reasons:
            assert reason in projection.blocker_reasons
        assert bool(projection.refs.refusal_or_correction_refs) is (
            fixture.expected.refusal_or_correction_refs_present
        )
        assert projection.public_conversion.boundary_alone_grants_public_conversion is False
        assert projection.public_conversion.adapter_grants_public_authority is False
        assert projection.public_conversion.adapter_grants_monetization_authority is False


def test_public_safe_boundary_carries_all_required_refs_but_not_authority() -> None:
    fixture = _fixture("public_safe_evidence_boundary")
    projection = project_fixture(fixture)

    assert projection.public_conversion.handoff_state == "rvpe_linked"
    assert projection.public_conversion.format_public_event_adapter_ready is True
    assert projection.public_conversion.research_vehicle_public_event_ref == (
        "rvpe:public_safe_evidence_audit"
    )
    assert projection.refs.wcs_snapshot_refs
    assert projection.refs.wcs_surface_refs
    assert projection.refs.evidence_refs
    assert projection.refs.evidence_envelope_refs == ("ee:public_safe_evidence_audit",)
    assert projection.refs.grounding_gate_refs
    assert projection.refs.outcome_refs == ("coe:public_safe_evidence_audit",)
    assert projection.grounding_gate_result.public_claim_allowed is True
    assert projection.grounding_gate_result.adapter_grants_public_claim is False
    assert set(projection.downstream_consumers) == {
        FORMAT_PUBLIC_EVENT_ADAPTER,
        CONTENT_PROGRAMME_FEEDBACK_LEDGER,
    }


def test_boundary_without_rvpe_link_fails_closed_for_public_handoff() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit", generated_at=GENERATED_AT)
    run_without_rvpe = run.model_copy(
        update={
            "boundary_event_refs": tuple(
                ref.model_copy(update={"public_event_mapping_ref": None})
                for ref in run.boundary_event_refs
            ),
            "conversion_candidates": tuple(
                candidate.model_copy(update={"research_vehicle_public_event_ref": None})
                for candidate in run.conversion_candidates
            ),
        }
    )
    fixture = _fixture("public_safe_evidence_boundary")

    projection = project_boundary_wcs_evidence(
        run_without_rvpe,
        fixture.boundary,
        generated_at=GENERATED_AT,
    )

    assert projection.public_conversion.handoff_state == "held_for_rvpe"
    assert projection.public_conversion.format_public_event_adapter_ready is False
    assert "research_vehicle_public_event_missing" in projection.blocker_reasons
    assert projection.public_conversion.boundary_alone_grants_public_conversion is False


def test_missing_wcs_evidence_gate_and_outcome_refs_fail_closed() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit", generated_at=GENERATED_AT)
    run_missing_refs = run.model_copy(
        update={
            "substrate_refs": (),
            "wcs": run.wcs.model_copy(
                update={
                    "semantic_substrate_refs": (),
                    "grounding_contract_refs": (),
                    "evidence_envelope_refs": (),
                    "capability_outcome_refs": (),
                }
            ),
            "gate_refs": run.gate_refs.model_copy(update={"grounding_gate_refs": ()}),
            "claims": (),
            "witnessed_outcomes": (),
        }
    )
    fixture = _fixture("public_safe_evidence_boundary")
    boundary = fixture.boundary.model_copy(
        update={
            "evidence_refs": (),
            "no_expert_system_gate": fixture.boundary.no_expert_system_gate.model_copy(
                update={"gate_ref": None}
            ),
        }
    )

    projection = project_boundary_wcs_evidence(
        run_missing_refs,
        boundary,
        generated_at=GENERATED_AT,
    )

    assert projection.public_conversion.format_public_event_adapter_ready is False
    assert "wcs_surface_ref_missing" in projection.blocker_reasons
    assert "missing_evidence_ref" in projection.blocker_reasons
    assert "evidence_envelope_ref_missing" in projection.blocker_reasons
    assert "missing_grounding_gate" in projection.blocker_reasons
    assert "capability_outcome_ref_missing" in projection.blocker_reasons


def test_world_surface_blocked_boundary_preserves_blockers_without_hiding_event() -> None:
    fixture = _fixture("world_surface_blocked_boundary")
    projection = project_fixture(fixture)

    assert projection.projection_state == "blocked"
    assert projection.boundary_type == "live_cuepoint.candidate"
    assert projection.public_conversion.format_public_event_adapter_ready is False
    assert "world_surface_blocked" in projection.blocker_reasons
    assert "witness_missing" in projection.blocker_reasons
    assert "privacy_blocked" in projection.blocker_reasons
    assert projection.public_conversion.format_public_event_input_ref


def test_refusal_and_correction_boundaries_keep_artifact_refs() -> None:
    refusal = project_fixture(_fixture("refusal_boundary_supported"))
    correction = project_fixture(_fixture("correction_boundary_supported"))

    assert refusal.projection_state == "refusal_supported"
    assert refusal.refs.refusal_or_correction_refs == ("refusal:refusal_run",)
    assert refusal.public_conversion.format_public_event_adapter_ready is False
    assert "public_event_mapping_internal_only" in refusal.blocker_reasons

    assert correction.projection_state == "correction_supported"
    assert correction.refs.refusal_or_correction_refs == ("correction:correction_run",)
    assert correction.public_conversion.format_public_event_adapter_ready is True
    assert correction.blocker_reasons == ()


def test_projection_is_consumable_by_public_event_and_feedback_adapters() -> None:
    fixture = _fixture("public_safe_evidence_boundary")
    run = build_fixture_envelope(fixture.run_fixture_case, generated_at=fixture.generated_at)
    projection = project_boundary_wcs_evidence(
        run,
        fixture.boundary,
        generated_at=fixture.generated_at,
    )

    public_decision = adapt_format_boundary_to_public_event(
        run,
        fixture.boundary,
        generated_at=fixture.generated_at,
    )
    feedback_event = build_feedback_event_from_run_envelope(
        run,
        occurred_at=fixture.generated_at,
    )

    assert projection.public_conversion.format_public_event_adapter_ready is True
    assert public_decision.status == "emitted"
    assert public_decision.public_event is not None
    assert projection.public_conversion.format_public_event_input_ref.endswith(
        f"{run.run_id}:{fixture.boundary.boundary_id}"
    )
    assert projection.feedback_ledger_input_ref == (
        f"ContentProgrammeFeedbackEvent:{feedback_event.ledger_event_id}"
    )
    assert feedback_event.learning_policy.public_truth_claim_allowed is True


def _fixture(fixture_id: str):
    fixture_set = load_programme_boundary_wcs_evidence_fixtures()
    return next(fixture for fixture in fixture_set.fixtures if fixture.fixture_id == fixture_id)
