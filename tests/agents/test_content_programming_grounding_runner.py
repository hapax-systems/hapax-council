"""Tests for the content-programming grounding runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agents.content_programming_grounding_runner import (
    ContentProgrammeRun,
    ContentProgrammingGroundingRunner,
    ScheduledProgrammeOpportunity,
)
from shared.content_programme_scheduler_policy import (
    PromotionStage,
    SchedulerOpportunity,
    ScheduleRoute,
    SchedulerWorldSurfaceSnapshot,
    decide_schedule,
)

NOW = datetime(2026, 5, 10, 18, 15, tzinfo=UTC)


def _runner(tmp_path: Path) -> ContentProgrammingGroundingRunner:
    return ContentProgrammingGroundingRunner(
        scheduled_opportunity_path=tmp_path / "scheduled.jsonl",
        run_envelope_path=tmp_path / "envelopes.jsonl",
        boundary_event_path=tmp_path / "boundaries.jsonl",
        public_event_decision_path=tmp_path / "public-event-decisions.jsonl",
        public_event_path=tmp_path / "public-events.jsonl",
        cursor_path=tmp_path / "cursor.json",
    )


def _opportunity(**overrides: object) -> SchedulerOpportunity:
    payload = {
        "decision_id": "cod_grounding_runner",
        "opportunity_id": "opp_grounding_runner",
        "format_id": "tier_list",
        "input_source_id": "source:grounding-runner",
        "subject_cluster": "grounding_runner",
        "public_mode": "public_live",
        "rights_state": "operator_original",
        "grounding_question": "What can this scheduled programme ground?",
        "evidence_refs": ("evidence:grounding-runner",),
        "source_priors": {"grounding_yield_prior": 0.72},
        "public_selectable": True,
        "monetizable": False,
        "completed_stages": (PromotionStage.DISCOVERED, PromotionStage.SCORED),
    }
    payload.update(overrides)
    return SchedulerOpportunity(**payload)


def _green_world(**overrides: object) -> SchedulerWorldSurfaceSnapshot:
    payload = {
        "available_surface_ids": ("surface:all",),
        "fresh_surface_ids": ("surface:all",),
        "evidence_refs": ("wcs:evidence:grounding-runner",),
        "health_state": "healthy",
        "no_expert_system_passed": True,
        "rights_clear": True,
        "privacy_clear": True,
        "provenance_complete": True,
        "public_event_ready": True,
        "audio_safe": True,
        "egress_ready": True,
        "archive_ready": True,
        "monetization_ready": True,
        "claim_shape_declared": True,
    }
    payload.update(overrides)
    return SchedulerWorldSurfaceSnapshot(**payload)


def _completed_through(stage: PromotionStage) -> tuple[PromotionStage, ...]:
    order = (
        PromotionStage.DISCOVERED,
        PromotionStage.SCORED,
        PromotionStage.DRY_RUN,
        PromotionStage.PRIVATE_ARCHIVE,
        PromotionStage.PUBLIC_LIVE,
        PromotionStage.CLIPPED_REPLAYED,
        PromotionStage.MONETIZED,
    )
    return order[: order.index(stage) + 1]


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_public_live_candidate_promotes_through_dry_run_without_public_events(
    tmp_path: Path,
) -> None:
    opportunity = _opportunity(public_mode="public_live")
    world = _green_world()
    decision = decide_schedule(opportunity, world, now=NOW)

    batch = _runner(tmp_path).run_once(
        [
            ScheduledProgrammeOpportunity(
                opportunity=opportunity,
                world=world,
                decision=decision,
                selected_input_refs=("input:selected-source",),
                substrate_refs=("substrate:tier-list-board",),
            )
        ],
        now=NOW,
    )

    assert decision.route is ScheduleRoute.DRY_RUN
    assert batch.processed == 1
    assert batch.public_events == ()
    assert isinstance(batch.runs[0], ContentProgrammeRun)
    assert batch.runs[0].format_id == "tier_list"
    assert batch.runs[0].selected_inputs == ("input:selected-source",)
    assert batch.runs[0].selected_substrates == ("substrate:tier-list-board",)
    assert batch.runs[0].rights_consent.public_event_policy_state == "not_public"
    assert batch.envelopes[0].public_private_mode == "dry_run"
    assert batch.envelopes[0].final_status == "completed"
    assert {boundary.boundary_type for boundary in batch.boundary_events} >= {
        "programme.started",
        "rank.assigned",
        "programme.ended",
    }
    assert all(decision.status == "refused" for decision in batch.public_event_decisions)
    assert "dry_run_mode" in batch.public_event_decisions[0].hard_unavailable_reasons
    assert batch.metrics.format_frequency == {"tier_list": 1}
    assert batch.metrics.public_events_refused == len(batch.public_event_decisions)


def test_public_archive_route_emits_programme_events_and_is_idempotent(
    tmp_path: Path,
) -> None:
    opportunity = _opportunity(
        public_mode="public_archive",
        completed_stages=_completed_through(PromotionStage.PUBLIC_LIVE),
    )
    world = _green_world()
    decision = decide_schedule(opportunity, world, now=NOW)
    scheduled = ScheduledProgrammeOpportunity(
        opportunity=opportunity,
        world=world,
        decision=decision,
        archive_refs=("https://example.invalid/archive/grounding-runner",),
    )
    runner = _runner(tmp_path)

    batch = runner.run_once([scheduled], now=NOW)
    second = runner.run_once([scheduled], now=NOW)

    assert decision.route is ScheduleRoute.PUBLIC_ARCHIVE
    assert batch.envelopes[0].public_private_mode == "public_archive"
    assert batch.envelopes[0].rights_privacy_public_mode.public_event_policy_state == "linked"
    assert batch.envelopes[0].final_status == "completed"
    assert batch.public_events
    assert any(event.event_type == "chapter.marker" for event in batch.public_events)
    assert any(
        "youtube_chapters" in event.surface_policy.allowed_surfaces for event in batch.public_events
    )
    assert any("archive" in event.surface_policy.allowed_surfaces for event in batch.public_events)
    assert any(output == "public_event:chapter.marker" for output in batch.runs[0].actual_outputs)
    assert second.processed == 0
    assert second.skipped_existing == 1
    assert len(_jsonl(tmp_path / "envelopes.jsonl")) == 1
    assert len(_jsonl(tmp_path / "public-events.jsonl")) == len(batch.public_events)


def test_public_monetizable_missing_gates_fails_closed_to_private_block(
    tmp_path: Path,
) -> None:
    opportunity = _opportunity(
        decision_id="cod_monetization_blocked",
        opportunity_id="opp_monetization_blocked",
        format_id="review",
        public_mode="public_monetizable",
        rights_state="unknown",
        monetizable=True,
        completed_stages=_completed_through(PromotionStage.CLIPPED_REPLAYED),
    )
    world = _green_world(rights_clear=False, audio_safe=False, monetization_ready=False)
    decision = decide_schedule(opportunity, world, now=NOW)

    batch = _runner(tmp_path).run_once(
        [ScheduledProgrammeOpportunity(opportunity=opportunity, world=world, decision=decision)],
        now=NOW,
    )

    run = batch.envelopes[0]
    assert decision.route is ScheduleRoute.PRIVATE
    assert run.public_private_mode == "private"
    assert run.final_status == "blocked"
    assert run.rights_privacy_public_mode.rights_state == "blocked"
    assert set(run.rights_privacy_public_mode.unavailable_reasons) >= {
        "private_mode",
        "rights_blocked",
        "audio_blocked",
        "monetization_blocked",
        "monetization_readiness_missing",
    }
    assert batch.public_events == ()
    assert batch.metrics.rights_refusals == 1
    assert batch.metrics.public_events_refused == len(batch.public_event_decisions)


def test_correction_route_records_correction_and_emits_public_safe_artifact(
    tmp_path: Path,
) -> None:
    opportunity = _opportunity(
        decision_id="cod_correction",
        opportunity_id="opp_correction",
        format_id="evidence_audit",
        public_mode="public_archive",
        correction_required=True,
        completed_stages=_completed_through(PromotionStage.PRIVATE_ARCHIVE),
    )
    world = _green_world()
    decision = decide_schedule(opportunity, world, now=NOW)

    batch = _runner(tmp_path).run_once(
        [ScheduledProgrammeOpportunity(opportunity=opportunity, world=world, decision=decision)],
        now=NOW,
    )

    assert decision.route is ScheduleRoute.CORRECTION
    assert batch.envelopes[0].final_status == "corrected"
    assert batch.runs[0].correction_refs
    assert any(boundary.boundary_type == "correction.made" for boundary in batch.boundary_events)
    assert any(
        decision.boundary_type == "correction.made" and decision.status == "emitted"
        for decision in batch.public_event_decisions
    )
    assert any(event.event_type == "publication.artifact" for event in batch.public_events)
    assert batch.metrics.grounding_corrections == 1
