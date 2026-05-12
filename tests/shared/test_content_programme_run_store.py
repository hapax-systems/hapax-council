"""Tests for content programme run-store helper models."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError

from shared.content_programme_run_store import (
    FIXTURE_CASE_IDS,
    RUN_STORE_EVENT_TYPES,
    CommandExecutionRecord,
    ContentProgrammeRunStoreEvent,
    ConversionCandidate,
    ProgrammeBoundaryEventRef,
    WitnessedOutcomeRecord,
    append_run_store_event,
    build_fixture_envelope,
    command_execution_allows_posterior_update,
    decide_fail_closed_mode,
    public_conversion_is_allowed,
    witnessed_outcome_allows_posterior_update,
)


def _event(sequence: int, event_type: str = "selected") -> ContentProgrammeRunStoreEvent:
    return ContentProgrammeRunStoreEvent(
        event_id=f"event:{sequence}",
        run_id="run_a",
        sequence=sequence,
        event_type=event_type,
        occurred_at=datetime(2026, 4, 29, tzinfo=UTC),
        idempotency_key=f"run_a:{sequence}",
        producer="test",
    )


def test_event_type_catalog_matches_acceptance_contract() -> None:
    assert set(RUN_STORE_EVENT_TYPES) == {
        "selected",
        "started",
        "transitioned",
        "blocked",
        "evidence_attached",
        "gate_evaluated",
        "boundary_emitted",
        "claim_recorded",
        "outcome_recorded",
        "refusal_issued",
        "correction_made",
        "artifact_candidate",
        "conversion_held",
        "public_event_linked",
        "completed",
        "aborted",
    }


def test_append_run_store_event_rejects_rewrites_and_duplicate_keys() -> None:
    first = _event(0)
    second = _event(1, "started")

    events = append_run_store_event((), first)
    events = append_run_store_event(events, second)

    assert [event.sequence for event in events] == [0, 1]
    assert all(event.append_only for event in events)

    for bad_event in (
        _event(1, "blocked"),
        ContentProgrammeRunStoreEvent(
            event_id="event:new",
            run_id="run_a",
            sequence=2,
            event_type="blocked",
            occurred_at=datetime(2026, 4, 29, tzinfo=UTC),
            idempotency_key="run_a:1",
            producer="test",
        ),
    ):
        try:
            append_run_store_event(events, bad_event)
        except ValueError:
            pass
        else:  # pragma: no cover - assertion guard
            raise AssertionError("append-only event validation should reject rewrite")


def test_missing_evidence_fails_closed_to_dry_run_refusal() -> None:
    decision = decide_fail_closed_mode("public_live", ())

    assert decision.requested_mode == "public_live"
    assert decision.effective_mode == "dry_run"
    assert decision.final_status == "refused"
    assert decision.public_claim_allowed is False
    assert "missing_evidence_ref" in decision.unavailable_reasons

    allowed = decide_fail_closed_mode("public_archive", ("evidence:a",))
    assert allowed.effective_mode == "public_archive"
    assert allowed.public_claim_allowed is True


def test_selected_commanded_and_executed_records_never_update_posteriors() -> None:
    selected = CommandExecutionRecord(
        record_id="selected:a",
        state="selected",
        occurred_at=datetime(2026, 4, 29, tzinfo=UTC),
    )

    assert command_execution_allows_posterior_update(selected) is False

    witnessed = WitnessedOutcomeRecord(
        outcome_id="outcome:a",
        witness_state="witness_verified",
        evidence_envelope_refs=("ee:a",),
        capability_outcome_ref="coe:a",
        posterior_update_allowed=True,
    )
    missing = WitnessedOutcomeRecord(
        outcome_id="outcome:b",
        witness_state="witness_unavailable",
        evidence_envelope_refs=(),
        capability_outcome_ref="coe:b",
        posterior_update_allowed=True,
    )

    assert witnessed_outcome_allows_posterior_update(witnessed) is True
    assert witnessed_outcome_allows_posterior_update(missing) is False


def test_boundary_refs_preserve_adapter_keys_without_duplicate_payload() -> None:
    boundary = ProgrammeBoundaryEventRef(
        boundary_id="pbe_a",
        sequence=7,
        boundary_type="rank.assigned",
        duplicate_key="programme:run:rank.assigned:007",
        cuepoint_chapter_distinction="vod_chapter_boundary",
        public_event_mapping_ref="rvpe:a",
        mapping_state="research_vehicle_linked",
        unavailable_reasons=(),
    )

    assert boundary.sequence == 7
    assert boundary.duplicate_key.endswith(":007")
    assert boundary.cuepoint_chapter_distinction == "vod_chapter_boundary"

    try:
        ProgrammeBoundaryEventRef.model_validate(
            {
                "boundary_id": "pbe_b",
                "sequence": 1,
                "boundary_type": "claim.made",
                "duplicate_key": "programme:run:claim.made:001",
                "cuepoint_chapter_distinction": "none",
                "public_event_mapping_ref": None,
                "mapping_state": "held",
                "unavailable_reasons": [],
                "summary": "duplicated boundary payload",
            }
        )
    except ValidationError as exc:
        assert "summary" in str(exc)
    else:  # pragma: no cover - assertion guard
        raise AssertionError("boundary refs must not accept duplicated boundary semantics")


def test_public_conversion_requires_rvpe_shorts_av_and_monetization_readiness() -> None:
    archive = ConversionCandidate(
        candidate_id="archive:a",
        conversion_type="archive_replay",
        state="linked",
        research_vehicle_public_event_ref="rvpe:a",
    )
    no_rvpe = archive.model_copy(update={"research_vehicle_public_event_ref": None})
    shorts = ConversionCandidate(
        candidate_id="shorts:a",
        conversion_type="shorts",
        state="linked",
        research_vehicle_public_event_ref="rvpe:shorts",
    )
    monetization = ConversionCandidate(
        candidate_id="monetization:a",
        conversion_type="monetization",
        state="linked",
        research_vehicle_public_event_ref="rvpe:monetization",
    )

    assert public_conversion_is_allowed(archive) is True
    assert public_conversion_is_allowed(no_rvpe) is False
    assert public_conversion_is_allowed(shorts) is False
    assert public_conversion_is_allowed(shorts.model_copy(update={"owned_cleared_av_ref": "av:a"}))
    assert public_conversion_is_allowed(monetization) is False
    assert public_conversion_is_allowed(
        monetization.model_copy(update={"monetization_readiness_ref": "monetization:ready"})
    )


def test_fixture_envelopes_cover_required_cases_and_keep_separation_policy() -> None:
    assert set(FIXTURE_CASE_IDS) == {
        "private_run",
        "dry_run",
        "public_archive_run",
        "public_live_blocked_run",
        "monetization_blocked_run",
        "refusal_run",
        "correction_run",
        "conversion_held_run",
        "dry_run_tier_list",
        "public_safe_evidence_audit",
        "rights_blocked_react_commentary",
        "world_surface_blocked_run",
    }

    for case_id in FIXTURE_CASE_IDS:
        envelope = build_fixture_envelope(case_id)
        assert envelope.selected_opportunity.decision_id == envelope.opportunity_decision_id
        assert envelope.selected_opportunity.rescore_hidden_copy_allowed is False
        assert envelope.selected_format.row_ref.endswith(f"#{envelope.format_id}")
        assert envelope.separation_policy.engagement_can_override_grounding is False
        assert envelope.separation_policy.revenue_can_override_grounding is False
        assert envelope.separation_policy.support_data_public_state_aggregate_only is True
        assert envelope.operator_labor_policy.single_operator_only is True
        assert envelope.operator_labor_policy.request_queue_allowed is False
        assert envelope.boundary_event_refs[0].duplicate_key
        assert envelope.role_state.active_programme_run_ref == envelope.run_id
        assert envelope.role_state.grounding_question == envelope.grounding_question

    public_live_blocked = build_fixture_envelope("public_live_blocked_run")
    assert public_live_blocked.requested_public_private_mode == "public_live"
    assert public_live_blocked.public_private_mode == "dry_run"
    assert "research_vehicle_public_event_missing" in public_live_blocked.wcs.unavailable_reasons

    rights_blocked = build_fixture_envelope("rights_blocked_react_commentary")
    assert rights_blocked.format_id == "react_commentary"
    assert "third_party_media_blocked" in rights_blocked.wcs.unavailable_reasons

    monetization_blocked = build_fixture_envelope("monetization_blocked_run")
    assert monetization_blocked.requested_public_private_mode == "public_monetizable"
    assert monetization_blocked.public_private_mode == "public_archive"
    assert "monetization_readiness_missing" in monetization_blocked.wcs.unavailable_reasons
