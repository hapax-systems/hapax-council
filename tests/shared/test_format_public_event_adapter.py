"""Tests for the content-programme format to public-event adapter."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from shared.content_programme_run_store import (
    ContentProgrammeRunEnvelope,
    build_fixture_envelope,
)
from shared.format_public_event_adapter import (
    ProgrammeBoundaryEvent,
    adapt_format_boundary_to_public_event,
    format_public_event_id,
)

GENERATED_AT = datetime(2026, 4, 29, 13, 55, tzinfo=UTC)


def _boundary(
    run: ContentProgrammeRunEnvelope,
    **overrides: Any,
) -> ProgrammeBoundaryEvent:
    mapping = {
        "internal_only": False,
        "research_vehicle_event_type": "programme.boundary",
        "state_kind": "programme_state",
        "source_substrate_id": "programme_cuepoints",
        "allowed_surfaces": ("youtube_chapters", "archive"),
        "denied_surfaces": ("youtube_cuepoints", "youtube_shorts", "monetization"),
        "fallback_action": "chapter_only",
        "unavailable_reasons": (),
    }
    mapping.update(overrides.pop("public_event_mapping", {}))
    gate = {
        "gate_ref": run.gate_refs.grounding_gate_refs[0]
        if run.gate_refs.grounding_gate_refs
        else None,
        "gate_state": "pass",
        "claim_allowed": True,
        "public_claim_allowed": True,
        "infractions": (),
    }
    gate.update(overrides.pop("no_expert_system_gate", {}))
    claim_shape = {
        "claim_kind": "ranking",
        "authority_ceiling": "evidence_bound",
        "confidence_label": "medium_high",
        "uncertainty": "Scope is limited to the cited evidence window.",
        "scope_limit": "Ranks only the declared source bundle.",
    }
    claim_shape.update(overrides.pop("claim_shape", {}))
    cuepoint_chapter_policy = {
        "live_ad_cuepoint_allowed": False,
        "vod_chapter_allowed": True,
        "live_cuepoint_distinct_from_vod_chapter": True,
        "chapter_label": "Evidence audit claim",
        "timecode": "00:00",
        "cuepoint_unavailable_reason": None,
    }
    cuepoint_chapter_policy.update(overrides.pop("cuepoint_chapter_policy", {}))
    payload = {
        "boundary_id": "pbe_evidence_audit_a_001",
        "emitted_at": datetime(2026, 4, 29, 13, 54, tzinfo=UTC),
        "programme_id": run.programme_id,
        "run_id": run.run_id,
        "format_id": run.format_id,
        "sequence": 1,
        "boundary_type": "rank.assigned",
        "public_private_mode": run.public_private_mode,
        "grounding_question": run.grounding_question,
        "summary": "Assigned a public-safe evidence audit rank.",
        "evidence_refs": ("source:primary_doc_a", "grounding-gate:evidence_audit_a"),
        "no_expert_system_gate": gate,
        "claim_shape": claim_shape,
        "public_event_mapping": mapping,
        "cuepoint_chapter_policy": cuepoint_chapter_policy,
        "dry_run_unavailable_reasons": (),
        "duplicate_key": f"{run.programme_id}:{run.run_id}:rank.assigned:001",
    }
    payload.update(overrides)
    return ProgrammeBoundaryEvent.model_validate(payload)


def test_public_archive_boundary_maps_to_schema_safe_public_event() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    boundary = _boundary(run)

    decision = adapt_format_boundary_to_public_event(
        run,
        boundary.model_dump(mode="json"),
        generated_at=GENERATED_AT,
    )

    assert decision.status == "emitted"
    assert decision.hard_unavailable_reasons == ()
    assert decision.grounding_question == run.grounding_question
    assert decision.claim_scope == "Ranks only the declared source bundle."
    assert decision.confidence_label == "medium_high"
    assert decision.uncertainty == "Scope is limited to the cited evidence window."
    assert decision.evidence_envelope_refs == ("ee:public_safe_evidence_audit",)
    assert "semantic-substrate:public_safe_evidence_audit" in decision.substrate_refs
    assert decision.witness_statuses == ("witness_verified",)

    event = decision.public_event
    assert event is not None
    assert event.event_id == format_public_event_id(
        run_id=run.run_id,
        boundary_id=boundary.boundary_id,
        duplicate_key=boundary.duplicate_key,
    )
    assert event.event_type == "programme.boundary"
    assert event.programme_id == run.programme_id
    assert event.source.evidence_ref == (
        f"ContentProgrammeRun:{run.run_id}#ProgrammeBoundaryEvent:{boundary.boundary_id}"
    )
    assert event.provenance.token == f"format_public_event:{event.event_id}"
    assert "ContentProgrammeRun.opportunity_decision_id:cod_public_safe_evidence_audit" in (
        event.provenance.evidence_refs
    )
    assert "ClaimShape.confidence:medium_high" in event.provenance.evidence_refs
    assert "source:primary_doc_a" in event.attribution_refs
    assert event.surface_policy.claim_live is False
    assert event.surface_policy.claim_archive is True
    assert event.surface_policy.claim_monetizable is False
    assert event.surface_policy.allowed_surfaces == ["youtube_chapters", "archive"]
    assert event.surface_policy.denied_surfaces == [
        "youtube_cuepoints",
        "youtube_shorts",
        "monetization",
    ]
    assert event.chapter_ref is not None
    assert event.chapter_ref.kind == "programme_boundary"
    assert json.loads(decision.to_json_line())["status"] == "emitted"


def test_private_and_dry_run_boundaries_refuse_without_public_event() -> None:
    private_run = build_fixture_envelope("private_run")
    dry_run = build_fixture_envelope("dry_run_tier_list")

    private_decision = adapt_format_boundary_to_public_event(
        private_run,
        _boundary(private_run),
        generated_at=GENERATED_AT,
    )
    dry_run_decision = adapt_format_boundary_to_public_event(
        dry_run,
        _boundary(dry_run),
        generated_at=GENERATED_AT,
    )

    assert private_decision.status == "refused"
    assert private_decision.public_event is None
    assert "private_mode" in private_decision.hard_unavailable_reasons
    assert dry_run_decision.status == "refused"
    assert dry_run_decision.public_event is None
    assert "dry_run_mode" in dry_run_decision.hard_unavailable_reasons


def test_missing_gate_and_evidence_fail_closed() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    run = run.model_copy(
        update={
            "claims": (),
            "wcs": run.wcs.model_copy(update={"evidence_envelope_refs": ()}),
            "gate_refs": run.gate_refs.model_copy(update={"grounding_gate_refs": ()}),
        }
    )
    boundary = _boundary(
        run,
        evidence_refs=(),
        no_expert_system_gate={"gate_ref": None},
    )

    decision = adapt_format_boundary_to_public_event(run, boundary, generated_at=GENERATED_AT)

    assert decision.status == "refused"
    assert decision.public_event is None
    assert "missing_evidence_ref" in decision.hard_unavailable_reasons
    assert "missing_grounding_gate" in decision.hard_unavailable_reasons


def test_wcs_blockers_and_witness_status_are_preserved_on_refusal() -> None:
    run = build_fixture_envelope("world_surface_blocked_run")
    boundary = _boundary(
        run,
        public_private_mode="public_live",
        public_event_mapping={
            "allowed_surfaces": ("youtube_cuepoints", "youtube_chapters", "archive"),
            "denied_surfaces": ("youtube_shorts", "monetization"),
            "unavailable_reasons": ("cuepoint_smoke_missing",),
        },
        cuepoint_chapter_policy={"cuepoint_unavailable_reason": "cuepoint_smoke_missing"},
    )

    decision = adapt_format_boundary_to_public_event(run, boundary, generated_at=GENERATED_AT)

    assert decision.status == "refused"
    assert decision.public_event is None
    assert "world_surface_blocked" in decision.hard_unavailable_reasons
    assert "witness_missing" in decision.hard_unavailable_reasons
    assert "cuepoint_smoke_missing" in decision.unavailable_reasons
    assert decision.wcs_unavailable_reasons == ("world_surface_blocked", "witness_missing")
    assert decision.witness_statuses == ("witness_verified",)


def test_refusal_artifact_emits_only_when_source_run_is_public_safe() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    boundary = _boundary(
        run,
        boundary_type="refusal.issued",
        public_event_mapping={
            "research_vehicle_event_type": "publication.artifact",
            "state_kind": "archive_artifact",
            "allowed_surfaces": ("archive",),
            "denied_surfaces": ("youtube_cuepoints", "youtube_shorts", "monetization"),
            "fallback_action": "archive_only",
        },
        no_expert_system_gate={
            "gate_state": "refusal",
            "claim_allowed": False,
            "public_claim_allowed": False,
            "infractions": ("original_claim_blocked",),
        },
        claim_shape={
            "claim_kind": "refusal",
            "confidence_label": "high",
            "uncertainty": "The refused claim lacks adequate supporting evidence.",
            "scope_limit": "Refuses only the unsupported source claim.",
        },
    )

    decision = adapt_format_boundary_to_public_event(run, boundary, generated_at=GENERATED_AT)

    assert decision.status == "emitted"
    assert decision.source_status == "refusal"
    assert decision.public_event is not None
    assert decision.public_event.event_type == "publication.artifact"
    assert decision.public_event.state_kind == "archive_artifact"
    assert decision.public_event.surface_policy.claim_archive is True

    private_run = build_fixture_envelope("private_run")
    private_boundary = _boundary(
        private_run,
        boundary_type="refusal.issued",
        public_event_mapping={
            "research_vehicle_event_type": "publication.artifact",
            "state_kind": "archive_artifact",
            "allowed_surfaces": ("archive",),
            "denied_surfaces": ("youtube_cuepoints", "youtube_shorts", "monetization"),
            "fallback_action": "archive_only",
        },
        no_expert_system_gate={
            "gate_state": "refusal",
            "claim_allowed": False,
            "public_claim_allowed": False,
        },
        claim_shape={"claim_kind": "refusal"},
    )

    private_decision = adapt_format_boundary_to_public_event(
        private_run,
        private_boundary,
        generated_at=GENERATED_AT,
    )

    assert private_decision.status == "refused"
    assert private_decision.public_event is None
    assert "private_mode" in private_decision.hard_unavailable_reasons


def test_boundary_must_match_run_ids_directly() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    boundary = _boundary(run, run_id="run_from_partial_legacy_state")

    decision = adapt_format_boundary_to_public_event(run, boundary, generated_at=GENERATED_AT)

    assert decision.status == "refused"
    assert decision.public_event is None
    assert "unsupported_claim" in decision.hard_unavailable_reasons
