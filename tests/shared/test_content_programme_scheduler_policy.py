"""Tests for content programme scheduler policy."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jsonschema

from shared.content_candidate_discovery import ContentSourceObservation, discover_candidates
from shared.content_programme_scheduler_policy import (
    PROMOTION_LADDER,
    CooldownLedger,
    ExplorationBudgetState,
    MediaReferenceGateView,
    PromotionStage,
    RiskTier,
    ScheduleRoute,
    SchedulerRuntimeState,
    SchedulerWorldSurfaceSnapshot,
    decide_schedule,
    load_policy,
    scheduler_opportunity_from_discovery,
)
from shared.format_wcs_requirement_matrix import load_format_wcs_requirement_matrix
from shared.programme_scrim_profile_policy import ProfileSelectionContext, select_profile_prior

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "config" / "content-programme-scheduler-policy.json"
SCHEMA_PATH = REPO_ROOT / "schemas" / "content-programme-scheduler-policy.schema.json"
NOW = datetime(2026, 5, 10, 17, 45, tzinfo=UTC)


def _observation(**overrides: object) -> ContentSourceObservation:
    payload = {
        "observation_id": "obs_scheduler_tier_list",
        "source_class": "local_state",
        "source_id": "local_scheduler_source",
        "format_id": "tier_list",
        "subject": "scheduler policy fixture",
        "subject_cluster": "scheduler_policy",
        "retrieved_at": NOW - timedelta(minutes=5),
        "published_at": NOW - timedelta(hours=1),
        "freshness_ttl_s": 3600,
        "public_mode": "public_live",
        "rights_state": "operator_original",
        "rights_hints": ("operator_original",),
        "substrate_refs": ("scheduler_fixture",),
        "evidence_refs": ("evidence:scheduler-fixture",),
        "provenance_refs": ("obsidian:scheduler-fixture",),
        "source_priors": {"grounding_yield_prior": 0.7},
        "grounding_question": "What can this scheduler policy fixture prove?",
    }
    payload.update(overrides)
    return ContentSourceObservation(**payload)


def _candidate(**overrides: object):
    decision = discover_candidates([_observation()], now=NOW)[0]
    candidate = scheduler_opportunity_from_discovery(decision)
    if overrides:
        candidate = candidate.model_copy(update=overrides)
    return candidate


def _green_world(**overrides: object) -> SchedulerWorldSurfaceSnapshot:
    payload = {
        "available_surface_ids": ("surface:all",),
        "fresh_surface_ids": ("surface:all",),
        "evidence_refs": ("ee:scheduler-fixture",),
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
    index = PROMOTION_LADDER.index(stage)
    return PROMOTION_LADDER[: index + 1]


def test_policy_config_validates_schema_and_pins_boundary_contract() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(payload)

    policy = load_policy()
    assert policy.promotion_ladder == PROMOTION_LADDER
    assert policy.routes == (
        ScheduleRoute.PRIVATE,
        ScheduleRoute.DRY_RUN,
        ScheduleRoute.PUBLIC_LIVE,
        ScheduleRoute.PUBLIC_ARCHIVE,
        ScheduleRoute.MONETIZED,
        ScheduleRoute.REFUSAL,
        ScheduleRoute.CORRECTION,
    )
    assert policy.operator_boundary_policy.manual_calendar_allowed is False
    assert policy.operator_boundary_policy.request_queue_allowed is False
    assert policy.operator_boundary_policy.supporter_controlled_show_allowed is False
    assert policy.operator_boundary_policy.community_moderation_allowed is False


def test_discovery_decision_is_default_input_and_operator_nomination_is_refused() -> None:
    candidate = _candidate()
    assert candidate.discovered_from == "content_discovery_decision"

    nominated = candidate.model_copy(
        update={
            "discovered_from": "operator_nominated",
            "manual_calendar_requested": True,
            "supporter_controlled": True,
            "per_person_request": True,
            "community_moderation_required": True,
        }
    )
    decision = decide_schedule(nominated, _green_world(), now=NOW)

    assert decision.route is ScheduleRoute.REFUSAL
    assert decision.selected is False
    assert "operator_nominated_topic_default_path_forbidden" in decision.blocked_reasons
    assert "manual_content_calendar_forbidden" in decision.blocked_reasons
    assert "supporter_show_control_forbidden" in decision.blocked_reasons
    assert "operator_request_queue_forbidden" in decision.blocked_reasons
    assert "community_moderation_obligation_forbidden" in decision.blocked_reasons


def test_public_candidate_must_promote_through_dry_run_first() -> None:
    candidate = _candidate(
        public_mode="public_live",
        public_selectable=True,
        completed_stages=(PromotionStage.DISCOVERED, PromotionStage.SCORED),
    )
    decision = decide_schedule(candidate, _green_world(), now=NOW)

    assert decision.requested_route is ScheduleRoute.PUBLIC_LIVE
    assert decision.route is ScheduleRoute.DRY_RUN
    assert decision.promotion_stage is PromotionStage.DRY_RUN
    assert decision.public_claim_allowed is False
    assert "promotion_ladder_requires_prior_stage:dry_run" in decision.scheduling_reasons


def test_public_live_gate_failures_downgrade_to_private_or_dry_run_with_audit_reasons() -> None:
    candidate = _candidate(
        public_mode="public_live",
        public_selectable=True,
        completed_stages=_completed_through(PromotionStage.PRIVATE_ARCHIVE),
    )
    world = _green_world(
        no_expert_system_passed=False,
        rights_clear=False,
        privacy_clear=False,
        provenance_complete=False,
        evidence_refs=(),
        missing_witness_refs=("witness:scheduler",),
        audio_safe=False,
        egress_ready=False,
        public_event_ready=False,
        claim_shape_declared=False,
    )
    decision = decide_schedule(candidate, world, now=NOW)

    assert decision.route is ScheduleRoute.PRIVATE
    assert decision.public_route_blocked is True
    assert decision.public_claim_allowed is False
    assert "no_expert_system_gate_failed" in decision.blocked_reasons
    assert "missing_claim_shape" in decision.blocked_reasons
    assert "rights_gate_blocked" in decision.blocked_reasons
    assert "provenance_gate_blocked" in decision.blocked_reasons
    assert "privacy_gate_blocked" in decision.blocked_reasons
    assert "missing_evidence" in decision.blocked_reasons
    assert "missing_witness" in decision.blocked_reasons
    assert "public_event_missing" in decision.blocked_reasons
    assert "audio_safety_gate_blocked" in decision.blocked_reasons
    assert "egress_gate_blocked" in decision.blocked_reasons


def test_public_archive_and_monetized_routes_remain_distinct() -> None:
    archive_candidate = _candidate(
        public_mode="public_archive",
        public_selectable=True,
        completed_stages=_completed_through(PromotionStage.PUBLIC_LIVE),
    )
    archive_decision = decide_schedule(archive_candidate, _green_world(), now=NOW)

    assert archive_decision.route is ScheduleRoute.PUBLIC_ARCHIVE
    assert archive_decision.promotion_stage is PromotionStage.CLIPPED_REPLAYED
    assert archive_decision.public_claim_allowed is True
    assert archive_decision.monetization_allowed is False

    monetized_candidate = _candidate(
        public_mode="public_monetizable",
        public_selectable=True,
        monetizable=True,
        completed_stages=_completed_through(PromotionStage.CLIPPED_REPLAYED),
    )
    monetized_decision = decide_schedule(monetized_candidate, _green_world(), now=NOW)

    assert monetized_decision.route is ScheduleRoute.MONETIZED
    assert monetized_decision.promotion_stage is PromotionStage.MONETIZED
    assert monetized_decision.public_claim_allowed is True
    assert monetized_decision.monetization_allowed is True

    blocked_monetized = decide_schedule(
        monetized_candidate,
        _green_world(monetization_ready=False),
        now=NOW,
    )
    assert blocked_monetized.route is ScheduleRoute.PRIVATE
    assert "monetization_gate_blocked" in blocked_monetized.blocked_reasons


def test_exploration_budget_and_cooldowns_are_enforced() -> None:
    exhausted_state = SchedulerRuntimeState(
        exploration_budget=ExplorationBudgetState(
            budget_window="daily",
            max_exploration_fraction=0.2,
            used_fraction=0.2,
            remaining_fraction=0.0,
            private_first=True,
            max_public_risk_tier=RiskTier.LOW,
        )
    )
    exploration_candidate = _candidate(exploration=True)
    exhausted_decision = decide_schedule(
        exploration_candidate,
        _green_world(),
        runtime_state=exhausted_state,
        now=NOW,
    )

    assert exhausted_decision.route is ScheduleRoute.REFUSAL
    assert "exploration_budget_exhausted" in exhausted_decision.blocked_reasons

    cooldown_state = SchedulerRuntimeState(
        exploration_budget=load_policy().default_exploration_budget,
        cooldowns=CooldownLedger(format_last_selected_at={"tier_list": NOW - timedelta(minutes=5)}),
    )
    cooldown_decision = decide_schedule(
        _candidate(),
        _green_world(),
        runtime_state=cooldown_state,
        now=NOW,
    )

    assert cooldown_decision.route is ScheduleRoute.REFUSAL
    assert "format_cooldown_active" in cooldown_decision.blocked_reasons


def test_risky_public_candidate_remains_dry_run_or_private() -> None:
    candidate = _candidate(
        public_mode="public_live",
        public_selectable=True,
        risk_tier=RiskTier.HIGH,
        completed_stages=(PromotionStage.DISCOVERED, PromotionStage.SCORED),
    )
    decision = decide_schedule(candidate, _green_world(), now=NOW)

    assert decision.route is ScheduleRoute.DRY_RUN
    assert decision.public_claim_allowed is False

    promoted = candidate.model_copy(
        update={"completed_stages": _completed_through(PromotionStage.PRIVATE_ARCHIVE)}
    )
    promoted_decision = decide_schedule(promoted, _green_world(), now=NOW)

    assert promoted_decision.route is ScheduleRoute.PRIVATE
    assert "public_risk_ceiling_exceeded" in promoted_decision.blocked_reasons


def test_matrix_scrim_and_media_reference_blockers_are_auditable() -> None:
    row = load_format_wcs_requirement_matrix().require_row("tier_list")
    required = row.required_surfaces_for_mode("public_archive")
    available = tuple(
        block.surface_id for block in required if block.surface_id != "tier_list.evidence_trace"
    )
    scrim_result = select_profile_prior(
        "tier_list",
        ProfileSelectionContext(evidence_status="missing"),
    )
    world = _green_world(
        available_surface_ids=available,
        media_reference_gate=MediaReferenceGateView(
            decision="refuse",
            safe_reference_mode="none",
            refused_factors=("rights_unknown",),
        ),
    )
    candidate = _candidate(
        public_mode="public_archive",
        public_selectable=True,
        completed_stages=_completed_through(PromotionStage.PUBLIC_LIVE),
    )
    decision = decide_schedule(
        candidate,
        world,
        format_row=row,
        scrim_profile_result=scrim_result,
        now=NOW,
    )

    assert decision.route is ScheduleRoute.PRIVATE
    assert "missing_evidence_trace" in decision.blocked_reasons
    assert "tier_list.evidence_trace" in decision.blocked_reasons
    assert "scrim_profile_unavailable" in decision.blocked_reasons
    assert "media_reference_rights_refused" in decision.blocked_reasons
    assert "rights_unknown" in decision.blocked_reasons
