"""Tests for the YouTube content-programming packaging compiler."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from shared.content_programme_run_store import (
    ContentProgrammeRunEnvelope,
    build_fixture_envelope,
)
from shared.conversion_broker import (
    ConversionCandidate,
    ConversionTargetRequest,
    build_conversion_broker_decision,
)
from shared.format_public_event_adapter import ProgrammeBoundaryEvent
from shared.youtube_content_programming_packaging_compiler import (
    REQUIRED_SURFACES,
    YouTubePackagingReadiness,
    YouTubePackagingSurface,
    YouTubePackagingSurfaceGate,
    compile_youtube_content_programming_package,
)

GENERATED_AT = datetime(2026, 5, 10, 14, 0, tzinfo=UTC)


def _boundary(
    run: ContentProgrammeRunEnvelope,
    *,
    boundary_type: str = "comparison.resolved",
    sequence: int = 1,
    summary: str = "Pairwise evidence flipped the ranking after a witnessed grounding moment.",
    chapter_label: str = "Evidence reversal",
    vod_chapter_allowed: bool = True,
    timecode: str | None = "00:42",
    allowed_surfaces: tuple[str, ...] = (
        "youtube_description",
        "youtube_channel_sections",
        "youtube_chapters",
        "youtube_captions",
        "youtube_shorts",
        "archive",
        "replay",
    ),
    **overrides: Any,
) -> ProgrammeBoundaryEvent:
    mapping = {
        "internal_only": False,
        "research_vehicle_event_type": "programme.boundary",
        "state_kind": "programme_state",
        "source_substrate_id": "programme_packaging",
        "allowed_surfaces": allowed_surfaces,
        "denied_surfaces": ("youtube_cuepoints",),
        "fallback_action": "hold",
        "unavailable_reasons": (),
    }
    mapping.update(overrides.pop("public_event_mapping", {}))
    gate = {
        "gate_ref": run.gate_refs.grounding_gate_refs[0],
        "gate_state": "pass",
        "claim_allowed": True,
        "public_claim_allowed": True,
        "infractions": (),
    }
    gate.update(overrides.pop("no_expert_system_gate", {}))
    claim_shape = {
        "claim_kind": "comparison",
        "authority_ceiling": "evidence_bound",
        "confidence_label": "medium_high",
        "uncertainty": "Only the cited evidence window is covered.",
        "scope_limit": "Ranks only the declared source bundle.",
    }
    claim_shape.update(overrides.pop("claim_shape", {}))
    cuepoint_chapter_policy = {
        "live_ad_cuepoint_allowed": True,
        "vod_chapter_allowed": vod_chapter_allowed,
        "live_cuepoint_distinct_from_vod_chapter": True,
        "chapter_label": chapter_label,
        "timecode": timecode,
        "cuepoint_unavailable_reason": None,
    }
    cuepoint_chapter_policy.update(overrides.pop("cuepoint_chapter_policy", {}))
    payload = {
        "boundary_id": f"pbe_{run.run_id}_{boundary_type.replace('.', '_')}_{sequence:03d}",
        "emitted_at": datetime(2026, 5, 10, 13, 59, tzinfo=UTC),
        "programme_id": run.programme_id,
        "run_id": run.run_id,
        "format_id": run.format_id,
        "sequence": sequence,
        "boundary_type": boundary_type,
        "public_private_mode": run.public_private_mode,
        "grounding_question": run.grounding_question,
        "summary": summary,
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


def _candidates(
    run: ContentProgrammeRunEnvelope,
    boundary: ProgrammeBoundaryEvent,
    *target_types: str,
) -> tuple[ConversionCandidate, ...]:
    requests = tuple(
        ConversionTargetRequest(
            target_type=target_type,
            requested_readiness_state="public-archive",
        )
        for target_type in target_types
    )
    return build_conversion_broker_decision(
        run,
        boundary,
        generated_at=GENERATED_AT,
        target_requests=requests,
    ).candidates


def _ready() -> YouTubePackagingReadiness:
    return YouTubePackagingReadiness(
        captured_at=GENERATED_AT,
        source="test-youtube-readiness",
        gates=tuple(
            YouTubePackagingSurfaceGate(
                surface=surface,
                available=True,
                state_detail="evidence available",
                evidence_refs=(f"youtube-surface:{surface.value}",),
            )
            for surface in REQUIRED_SURFACES
        ),
    )


def test_compiler_builds_full_youtube_packaging_from_programme_boundaries() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    boundary = _boundary(run)
    candidates = _candidates(
        run,
        boundary,
        "youtube_vod",
        "youtube_chapter",
        "youtube_caption",
        "youtube_shorts",
    )

    result = compile_youtube_content_programming_package(
        run=run,
        boundary_events=(boundary,),
        conversion_candidates=candidates,
        readiness=_ready(),
        generated_at=GENERATED_AT,
    )

    assert result.status == "compiled"
    assert result.blocked_reasons == ()
    assert result.title_candidates
    assert "Claim Audit" in result.title_candidates[0].text
    assert result.title_candidates[0].epistemic_test in result.title_candidates[0].text
    assert result.thumbnail_briefs[0].shape in {
        "tier_grid",
        "bracket",
        "verdict_stamp",
        "comparison",
        "refusal_card",
        "confidence_meter",
    }
    assert result.description is not None
    assert result.description.public_event_refs
    assert result.chapters[0].derived_from_programme_boundary is True
    assert result.chapters[0].label == "Evidence reversal"
    assert result.chapters[0].timecode == "00:42"
    assert result.captions[0].platform_text
    assert result.captions[0].internal_claim_refs
    assert result.captions[0].internal_provenance_refs
    assert result.captions[0].internal_uncertainty == "Only the cited evidence window is covered."
    assert result.shorts_candidates[0].focus == "rank_reversal"
    assert result.shorts_candidates[0].generic_viral_cut_allowed is False
    assert {placement.kind for placement in result.placements} == {"playlist", "channel_section"}
    assert any("metadata: available" in reason for reason in result.surface_policy_reasons)


def test_compiler_fails_closed_when_required_surface_is_unavailable() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    boundary = _boundary(run)
    gates = []
    for surface in REQUIRED_SURFACES:
        gates.append(
            YouTubePackagingSurfaceGate(
                surface=surface,
                available=surface is not YouTubePackagingSurface.CAPTIONS,
                state_detail="evidence available"
                if surface is not YouTubePackagingSurface.CAPTIONS
                else "caption producer stale",
                unavailable_reasons=("caption producer stale",)
                if surface is YouTubePackagingSurface.CAPTIONS
                else (),
            )
        )
    readiness = YouTubePackagingReadiness(
        captured_at=GENERATED_AT,
        source="test-youtube-readiness",
        gates=tuple(gates),
    )

    result = compile_youtube_content_programming_package(
        run=run,
        boundary_events=(boundary,),
        conversion_candidates=_candidates(run, boundary, "youtube_vod", "youtube_chapter"),
        readiness=readiness,
        generated_at=GENERATED_AT,
    )

    assert result.status == "blocked"
    assert result.title_candidates == ()
    assert any("captions unavailable" in reason for reason in result.blocked_reasons)
    assert any("captions conversion candidate" in reason for reason in result.blocked_reasons)


def test_compiler_requires_chapters_from_programme_boundaries_not_timestamps_alone() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    boundary = _boundary(
        run,
        vod_chapter_allowed=False,
        timecode="00:09",
        chapter_label="Timestamp without chapter policy",
    )
    candidates = _candidates(
        run,
        boundary,
        "youtube_vod",
        "youtube_chapter",
        "youtube_caption",
        "youtube_shorts",
    )

    result = compile_youtube_content_programming_package(
        run=run,
        boundary_events=(boundary,),
        conversion_candidates=candidates,
        readiness=_ready(),
        generated_at=GENERATED_AT,
    )

    assert result.status == "blocked"
    assert any(
        "no programme-boundary chapter policy" in reason for reason in result.blocked_reasons
    )


def test_compiler_blocks_generic_shorts_when_no_focus_boundary_exists() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit")
    boundary = _boundary(
        run,
        boundary_type="programme.started",
        summary="Programme started with ordinary setup context.",
    )
    candidates = _candidates(
        run,
        boundary,
        "youtube_vod",
        "youtube_chapter",
        "youtube_caption",
        "youtube_shorts",
    )

    result = compile_youtube_content_programming_package(
        run=run,
        boundary_events=(boundary,),
        conversion_candidates=candidates,
        readiness=_ready(),
        generated_at=GENERATED_AT,
    )

    assert result.status == "blocked"
    assert any("no rank reversal" in reason for reason in result.blocked_reasons)


def test_compiler_blocks_packaging_policy_violations() -> None:
    run = build_fixture_envelope("public_safe_evidence_audit").model_copy(
        update={"grounding_question": "As the expert says, which source wins?"}
    )
    boundary = _boundary(run)
    candidates = _candidates(
        run,
        boundary,
        "youtube_vod",
        "youtube_chapter",
        "youtube_caption",
        "youtube_shorts",
    )

    result = compile_youtube_content_programming_package(
        run=run,
        boundary_events=(boundary,),
        conversion_candidates=candidates,
        readiness=_ready(),
        generated_at=GENERATED_AT,
    )

    assert result.status == "blocked"
    assert any("packaging policy blocked title" in reason for reason in result.blocked_reasons)
