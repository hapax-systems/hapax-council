"""Tests for the readiness-gated conversion broker."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus_client import CollectorRegistry

from shared.content_programme_run_store import (
    ContentProgrammeRunEnvelope,
    build_fixture_envelope,
)
from shared.conversion_broker import (
    ConversionBroker,
    ConversionBrokerMetrics,
    ConversionCandidate,
    ConversionTargetRequest,
    build_conversion_broker_decision,
)
from shared.format_public_event_adapter import ProgrammeBoundaryEvent

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
    boundary_type = overrides.pop("boundary_type", "rank.assigned")
    sequence = overrides.pop("sequence", 1)
    payload = {
        "boundary_id": overrides.pop(
            "boundary_id",
            f"pbe_{run.run_id}_{boundary_type.replace('.', '_')}_{sequence:03d}",
        ),
        "emitted_at": datetime(2026, 4, 29, 13, 54, tzinfo=UTC),
        "programme_id": run.programme_id,
        "run_id": run.run_id,
        "format_id": run.format_id,
        "sequence": sequence,
        "boundary_type": boundary_type,
        "public_private_mode": run.public_private_mode,
        "grounding_question": run.grounding_question,
        "summary": "Assigned a public-safe evidence audit rank.",
        "evidence_refs": ("source:primary_doc_a", "grounding-gate:evidence_audit_a"),
        "no_expert_system_gate": gate,
        "claim_shape": claim_shape,
        "public_event_mapping": mapping,
        "cuepoint_chapter_policy": cuepoint_chapter_policy,
        "dry_run_unavailable_reasons": (),
        "duplicate_key": f"{run.programme_id}:{run.run_id}:{boundary_type}:{sequence:03d}",
    }
    payload.update(overrides)
    return ProgrammeBoundaryEvent.model_validate(payload)


def _artifact_ready_run(
    case_id: str = "public_safe_evidence_audit",
    *,
    final_status: str | None = None,
) -> ContentProgrammeRunEnvelope:
    run = build_fixture_envelope(case_id)
    run = run.model_copy(
        update={
            "selected_input_refs": (
                *run.selected_input_refs,
                "operator-attestation:artifact-release:test",
            )
        }
    )
    if final_status is not None:
        run = run.model_copy(update={"final_status": final_status})
    return run


def _candidate(
    candidates: Iterator[ConversionCandidate] | tuple[ConversionCandidate, ...],
    target_type: str,
) -> ConversionCandidate:
    return next(candidate for candidate in candidates if candidate.target_type == target_type)


def test_public_archive_boundary_generates_rich_candidates_and_public_bus_event(
    tmp_path: Path,
) -> None:
    registry = CollectorRegistry()
    run = build_fixture_envelope("public_safe_evidence_audit")
    boundary = _boundary(run)
    broker = ConversionBroker(
        public_event_path=tmp_path / "events.jsonl",
        candidate_path=tmp_path / "candidates.jsonl",
        metrics=ConversionBrokerMetrics(registry),
    )

    decision = broker.process_boundary(run, boundary, generated_at=GENERATED_AT)

    chapter = _candidate(decision.candidates, "youtube_chapter")
    assert chapter.source_run_id == run.run_id
    assert chapter.source_events[0].source_ref == f"ProgrammeBoundaryEvent:{boundary.boundary_id}"
    assert chapter.target_family_id == "youtube_vod_packaging"
    assert chapter.salience > 0
    assert chapter.rights_class == "operator_controlled"
    assert chapter.privacy_class == "public_safe"
    assert chapter.provenance is not None
    assert chapter.provenance_refs
    assert chapter.chapter_refs
    assert chapter.archive_refs == run.archive_refs
    assert "Ranks only the declared source bundle." in chapter.claim_text
    assert chapter.blocked_reason is None
    assert chapter.readiness_state == "public-archive"
    assert chapter.ready_for_publication_bus is True
    assert chapter.publication_bus_event_ref == decision.public_events[0].event_id
    payload = json.loads(chapter.to_json_line())
    for required_field in (
        "source_run_id",
        "source_events",
        "target_type",
        "salience",
        "rights_class",
        "privacy_class",
        "provenance",
        "frame_refs",
        "chapter_refs",
        "archive_refs",
        "claim_text",
        "blocked_reason",
        "readiness_state",
    ):
        assert required_field in payload

    assert len(decision.public_events) == 1
    assert json.loads((tmp_path / "events.jsonl").read_text())["event_id"] == (
        decision.public_events[0].event_id
    )
    candidate_lines = (tmp_path / "candidates.jsonl").read_text().splitlines()
    assert len(candidate_lines) == len(decision.candidates)
    assert (
        registry.get_sample_value(
            "hapax_conversion_broker_candidates_total",
            {
                "target_family": "youtube_vod_packaging",
                "target_type": "youtube_chapter",
                "readiness_state": "public-archive",
                "result": "generated",
            },
        )
        == 1.0
    )
    assert (
        registry.get_sample_value(
            "hapax_conversion_broker_candidates_total",
            {
                "target_family": "youtube_vod_packaging",
                "target_type": "youtube_chapter",
                "readiness_state": "public-archive",
                "result": "published",
            },
        )
        == 1.0
    )
    assert (
        registry.get_sample_value(
            "hapax_conversion_broker_outcomes_total",
            {"outcome_kind": "artifact", "result": "published"},
        )
        is not None
    )


def test_readiness_matrix_blocks_each_target_independently(tmp_path: Path) -> None:
    registry = CollectorRegistry()
    run = build_fixture_envelope("public_safe_evidence_audit")
    boundary = _boundary(run)
    broker = ConversionBroker(
        public_event_path=tmp_path / "events.jsonl",
        candidate_path=tmp_path / "candidates.jsonl",
        metrics=ConversionBrokerMetrics(registry),
    )

    decision = broker.process_boundary(
        run,
        boundary,
        generated_at=GENERATED_AT,
        target_requests=(
            ConversionTargetRequest(
                target_type="archive_replay",
                requested_readiness_state="public-archive",
            ),
            ConversionTargetRequest(
                target_type="support_prompt",
                requested_readiness_state="public-monetizable",
            ),
        ),
    )

    archive = _candidate(decision.candidates, "archive_replay")
    support = _candidate(decision.candidates, "support_prompt")
    assert archive.ready_for_publication_bus is True
    assert archive.readiness_state == "public-archive"
    assert support.ready_for_publication_bus is False
    assert support.readiness_state == "blocked"
    assert "monetization" in support.missing_gate_dimensions
    assert len(decision.public_events) == 1
    assert (
        registry.get_sample_value(
            "hapax_conversion_broker_public_events_total",
            {
                "target_family": "support_prompt",
                "target_type": "support_prompt",
                "result": "blocked",
            },
        )
        == 1.0
    )
    assert (
        registry.get_sample_value(
            "hapax_conversion_broker_outcomes_total",
            {"outcome_kind": "revenue", "result": "blocked"},
        )
        == 1.0
    )


def test_rights_blocker_prevents_publication_even_with_explicit_target(
    tmp_path: Path,
) -> None:
    run = build_fixture_envelope("rights_blocked_react_commentary")
    boundary = _boundary(
        run,
        public_private_mode="public_archive",
        public_event_mapping={
            "allowed_surfaces": ("youtube_chapters", "archive"),
            "unavailable_reasons": ("rights_blocked",),
        },
    )
    broker = ConversionBroker(
        public_event_path=tmp_path / "events.jsonl",
        candidate_path=tmp_path / "candidates.jsonl",
        metrics=ConversionBrokerMetrics(CollectorRegistry()),
    )

    decision = broker.process_boundary(
        run,
        boundary,
        generated_at=GENERATED_AT,
        target_requests=(
            ConversionTargetRequest(
                target_type="youtube_chapter",
                requested_readiness_state="public-archive",
            ),
        ),
    )

    candidate = decision.candidates[0]
    assert candidate.target_type == "youtube_chapter"
    assert candidate.readiness_state == "blocked"
    assert candidate.ready_for_publication_bus is False
    assert "rights" in candidate.missing_gate_dimensions
    assert "rights_blocked" in candidate.blocked_reason
    assert decision.public_events == ()
    assert not (tmp_path / "events.jsonl").exists()


def test_public_safe_refusals_corrections_and_failures_become_artifact_candidates() -> None:
    cases = (
        (
            _artifact_ready_run(),
            _boundary(
                _artifact_ready_run(),
                boundary_type="refusal.issued",
                public_event_mapping={
                    "research_vehicle_event_type": "publication.artifact",
                    "state_kind": "archive_artifact",
                    "allowed_surfaces": ("archive",),
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
                    "uncertainty": "The refused claim lacks adequate support.",
                    "scope_limit": "Refuses only the unsupported source claim.",
                },
            ),
            "refusal_artifact",
        ),
        (
            _artifact_ready_run("correction_run"),
            _boundary(
                _artifact_ready_run("correction_run"),
                boundary_type="correction.made",
                sequence=2,
                public_event_mapping={
                    "research_vehicle_event_type": "metadata.update",
                    "state_kind": "archive_artifact",
                    "allowed_surfaces": ("archive",),
                    "fallback_action": "archive_only",
                },
                no_expert_system_gate={
                    "gate_state": "correction_required",
                    "claim_allowed": False,
                    "public_claim_allowed": False,
                },
                claim_shape={
                    "claim_kind": "correction",
                    "confidence_label": "high",
                    "uncertainty": "The corrected claim is limited to cited evidence.",
                    "scope_limit": "Corrects only the prior public metadata.",
                },
            ),
            "correction_artifact",
        ),
        (
            _artifact_ready_run(final_status="aborted"),
            _boundary(
                _artifact_ready_run(final_status="aborted"),
                boundary_type="programme.ended",
                sequence=3,
                public_event_mapping={
                    "research_vehicle_event_type": "publication.artifact",
                    "state_kind": "archive_artifact",
                    "allowed_surfaces": ("archive",),
                    "fallback_action": "archive_only",
                },
                claim_shape={
                    "claim_kind": "metadata",
                    "confidence_label": "medium_high",
                    "uncertainty": "The failure note only describes the run boundary.",
                    "scope_limit": "Records the failed programme output without retry claims.",
                },
            ),
            "failure_artifact",
        ),
    )

    for run, boundary, target_type in cases:
        decision = build_conversion_broker_decision(
            run,
            boundary,
            generated_at=GENERATED_AT,
        )
        candidate = _candidate(decision.candidates, target_type)
        assert candidate.ready_for_publication_bus is True
        assert candidate.blocked_reason is None
        assert candidate.publication_bus_event_ref == decision.public_events[0].event_id
