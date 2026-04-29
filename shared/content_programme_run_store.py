"""Typed contract helpers for content programme run store events."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type PublicPrivateMode = Literal[
    "private",
    "dry_run",
    "public_live",
    "public_archive",
    "public_monetizable",
]
type RightsState = Literal[
    "operator_original", "cleared", "platform_embed_only", "blocked", "unknown"
]
type PrivacyState = Literal[
    "operator_private", "public_safe", "aggregate_only", "blocked", "unknown"
]
type RunFinalStatus = Literal[
    "selected",
    "running",
    "blocked",
    "refused",
    "corrected",
    "conversion_held",
    "completed",
    "aborted",
]
type RunStoreEventType = Literal[
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
]
type CuepointChapterDistinction = Literal[
    "none",
    "live_cuepoint_candidate",
    "vod_chapter_boundary",
    "both_distinct",
]
type BoundaryMappingState = Literal[
    "internal_only",
    "research_vehicle_required",
    "research_vehicle_linked",
    "held",
    "unavailable",
]
type WitnessState = Literal[
    "not_required",
    "not_observed",
    "observed_without_witness",
    "witness_verified",
    "witness_failed",
    "witness_stale",
    "witness_unavailable",
    "inferred_only",
]
type WcsHealthState = Literal[
    "healthy",
    "degraded",
    "blocked",
    "unsafe",
    "stale",
    "missing",
    "unknown",
    "private_only",
    "dry_run",
    "candidate",
]
type CommandState = Literal[
    "candidate_scored",
    "selected",
    "commanded",
    "accepted",
    "applied",
    "queued",
    "dry_run",
    "blocked_by_policy",
    "tool_error",
    "unknown",
]
type ConversionType = Literal[
    "archive_replay",
    "chapter",
    "live_cuepoint",
    "shorts",
    "metadata",
    "refusal_artifact",
    "correction_artifact",
    "support_prompt",
    "grant_packet",
    "monetization",
]
type ConversionState = Literal["candidate", "held", "blocked", "linked", "emitted"]
type AdapterName = Literal[
    "public_event",
    "scheduler",
    "feedback",
    "archive",
    "youtube",
    "metrics",
]
type FixtureCaseId = Literal[
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
]
type UnavailableReason = Literal[
    "private_mode",
    "dry_run_mode",
    "missing_evidence_ref",
    "missing_grounding_gate",
    "grounding_gate_failed",
    "unsupported_claim",
    "source_stale",
    "rights_blocked",
    "privacy_blocked",
    "egress_blocked",
    "audio_blocked",
    "archive_missing",
    "video_id_missing",
    "cuepoint_smoke_missing",
    "cuepoint_api_rejected",
    "rate_limited",
    "monetization_blocked",
    "monetization_readiness_missing",
    "operator_review_required",
    "live_provider_smoke_missing",
    "third_party_media_blocked",
    "owned_cleared_av_missing",
    "research_vehicle_public_event_missing",
    "world_surface_blocked",
    "witness_missing",
]

PUBLIC_PRIVATE_MODES: tuple[PublicPrivateMode, ...] = (
    "private",
    "dry_run",
    "public_live",
    "public_archive",
    "public_monetizable",
)
RUN_STORE_EVENT_TYPES: tuple[RunStoreEventType, ...] = (
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
)
FIXTURE_CASE_IDS: tuple[FixtureCaseId, ...] = (
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
)
ADAPTER_EXPOSURES: tuple[AdapterName, ...] = (
    "public_event",
    "scheduler",
    "feedback",
    "archive",
    "youtube",
    "metrics",
)


class RunStoreModel(BaseModel):
    """Strict immutable base for run-store helper records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SelectedOpportunityRef(RunStoreModel):
    decision_id: str
    decision_ref: str
    opportunity_id: str
    content_opportunity_tuple_ref: str
    posterior_sample_refs: tuple[str, ...] = Field(default_factory=tuple)
    reward_vector_ref: str
    rescore_hidden_copy_allowed: Literal[False] = False


class SelectedFormatRef(RunStoreModel):
    format_id: str
    registry_ref: str
    row_ref: str
    grounding_question: str
    grounding_attempt_types: tuple[str, ...]


class RightsPrivacyPublicMode(RunStoreModel):
    requested_mode: PublicPrivateMode
    effective_mode: PublicPrivateMode
    rights_state: RightsState
    privacy_state: PrivacyState
    public_event_policy_state: Literal["required", "linked", "held", "blocked", "not_public"]
    monetization_state: Literal["not_requested", "ready", "blocked", "unknown"]
    unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)


class DirectorPlanRef(RunStoreModel):
    director_snapshot_ref: str
    director_plan_ref: str
    director_move_refs: tuple[str, ...] = Field(default_factory=tuple)
    condition_id: str | None = None


class GateRefs(RunStoreModel):
    grounding_gate_refs: tuple[str, ...] = Field(default_factory=tuple)
    rights_gate_refs: tuple[str, ...] = Field(default_factory=tuple)
    privacy_gate_refs: tuple[str, ...] = Field(default_factory=tuple)
    monetization_gate_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_event_gate_refs: tuple[str, ...] = Field(default_factory=tuple)


class WitnessRequirement(RunStoreModel):
    requirement_id: str
    substrate_ref: str
    required_witness_refs: tuple[str, ...]
    missing_witness_refs: tuple[str, ...] = Field(default_factory=tuple)


class WcsBinding(RunStoreModel):
    semantic_substrate_refs: tuple[str, ...]
    grounding_contract_refs: tuple[str, ...]
    evidence_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    witness_requirements: tuple[WitnessRequirement, ...]
    capability_outcome_refs: tuple[str, ...] = Field(default_factory=tuple)
    health_state: WcsHealthState
    unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)
    public_private_posture: RightsPrivacyPublicMode


class RunStoreEventRef(RunStoreModel):
    event_id: str
    sequence: int = Field(ge=0)
    event_type: RunStoreEventType


class ProgrammeBoundaryEventRef(RunStoreModel):
    boundary_id: str
    sequence: int = Field(ge=0)
    boundary_type: str
    duplicate_key: str
    cuepoint_chapter_distinction: CuepointChapterDistinction
    public_event_mapping_ref: str | None = None
    mapping_state: BoundaryMappingState
    unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)


class ClaimRef(RunStoreModel):
    claim_id: str
    evidence_refs: tuple[str, ...]
    evidence_envelope_refs: tuple[str, ...]
    uncertainty_ref: str | None = None
    posterior_state_ref: str | None = None


class StateRef(RunStoreModel):
    state_id: str
    reason: str
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class ScoreRef(RunStoreModel):
    evaluation_id: str
    dimension: str
    score_ref: str
    evidence_refs: tuple[str, ...]
    verdict_authority_allowed: Literal[False] = False
    engagement_metric_source_allowed: Literal[False] = False


class CommandExecutionRecord(RunStoreModel):
    record_id: str
    state: CommandState
    occurred_at: datetime
    refs: tuple[str, ...] = Field(default_factory=tuple)
    posterior_update_allowed: Literal[False] = False


class WitnessedOutcomeRecord(RunStoreModel):
    outcome_id: str
    witness_state: WitnessState
    evidence_envelope_refs: tuple[str, ...]
    capability_outcome_ref: str
    posterior_update_allowed: bool = False


class CommandExecutionTrace(RunStoreModel):
    selected: CommandExecutionRecord
    commanded_states: tuple[CommandExecutionRecord, ...] = Field(default_factory=tuple)
    executed_states: tuple[CommandExecutionRecord, ...] = Field(default_factory=tuple)
    witnessed_outcomes: tuple[WitnessedOutcomeRecord, ...] = Field(default_factory=tuple)


class ConversionCandidate(RunStoreModel):
    candidate_id: str
    conversion_type: ConversionType
    state: ConversionState
    requires_research_vehicle_public_event: bool = True
    research_vehicle_public_event_ref: str | None = None
    owned_cleared_av_ref: str | None = None
    monetization_readiness_ref: str | None = None
    unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)


class AdapterExposure(RunStoreModel):
    adapters: tuple[AdapterName, ...] = ADAPTER_EXPOSURES
    ref: str
    stale_or_missing_state_blocks_public: Literal[True] = True


class SeparationPolicy(RunStoreModel):
    selected_commanded_executed_are_not_witnessed: Literal[True] = True
    witnessed_outcomes_only_update_posteriors: Literal[True] = True
    evaluator_outputs_are_evidence_outcomes: Literal[True] = True
    engagement_can_override_grounding: Literal[False] = False
    revenue_can_override_grounding: Literal[False] = False
    engagement_metrics_stored_separately: Literal[True] = True
    support_data_public_state_aggregate_only: Literal[True] = True
    public_payer_identity_allowed: Literal[False] = False


class OperatorLaborPolicy(RunStoreModel):
    single_operator_only: Literal[True] = True
    request_queue_allowed: Literal[False] = False
    manual_content_calendar_allowed: Literal[False] = False
    supporter_controlled_programming_allowed: Literal[False] = False
    personalized_supporter_treatment_allowed: Literal[False] = False


class ContentProgrammeRunStoreEvent(RunStoreModel):
    schema_version: Literal[1] = 1
    event_id: str
    run_id: str
    sequence: int = Field(ge=0)
    event_type: RunStoreEventType
    occurred_at: datetime
    idempotency_key: str
    producer: str
    payload_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    boundary_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    public_event_refs: tuple[str, ...] = Field(default_factory=tuple)
    capability_outcome_refs: tuple[str, ...] = Field(default_factory=tuple)
    append_only: Literal[True] = True
    mutation_policy: Literal["append_new_event_never_update_existing"] = (
        "append_new_event_never_update_existing"
    )


class ContentProgrammeRunEnvelope(RunStoreModel):
    schema_version: Literal[1] = 1
    run_id: str
    programme_id: str
    opportunity_decision_id: str
    format_id: str
    condition_id: str | None = None
    selected_at: datetime
    selected_by: str
    grounding_question: str
    requested_public_private_mode: PublicPrivateMode
    public_private_mode: PublicPrivateMode
    rights_privacy_public_mode: RightsPrivacyPublicMode
    selected_opportunity: SelectedOpportunityRef
    selected_format: SelectedFormatRef
    broadcast_refs: tuple[str, ...] = Field(default_factory=tuple)
    archive_refs: tuple[str, ...] = Field(default_factory=tuple)
    selected_input_refs: tuple[str, ...] = Field(default_factory=tuple)
    substrate_refs: tuple[str, ...] = Field(default_factory=tuple)
    semantic_capability_refs: tuple[str, ...] = Field(default_factory=tuple)
    director_plan: DirectorPlanRef
    gate_refs: GateRefs
    wcs: WcsBinding
    events: tuple[RunStoreEventRef, ...] = Field(default_factory=tuple)
    boundary_event_refs: tuple[ProgrammeBoundaryEventRef, ...] = Field(default_factory=tuple)
    claims: tuple[ClaimRef, ...] = Field(default_factory=tuple)
    uncertainties: tuple[StateRef, ...] = Field(default_factory=tuple)
    refusals: tuple[StateRef, ...] = Field(default_factory=tuple)
    corrections: tuple[StateRef, ...] = Field(default_factory=tuple)
    scores: tuple[ScoreRef, ...] = Field(default_factory=tuple)
    conversion_candidates: tuple[ConversionCandidate, ...] = Field(default_factory=tuple)
    command_execution: CommandExecutionTrace
    witnessed_outcomes: tuple[WitnessedOutcomeRecord, ...] = Field(default_factory=tuple)
    adapter_exposure: AdapterExposure
    separation_policy: SeparationPolicy = Field(default_factory=SeparationPolicy)
    operator_labor_policy: OperatorLaborPolicy = Field(default_factory=OperatorLaborPolicy)
    final_status: RunFinalStatus


class FailClosedDecision(RunStoreModel):
    requested_mode: PublicPrivateMode
    effective_mode: PublicPrivateMode
    final_status: RunFinalStatus
    public_claim_allowed: bool
    unavailable_reasons: tuple[UnavailableReason, ...]


class FixtureCase(RunStoreModel):
    case_id: FixtureCaseId
    requested_mode: PublicPrivateMode
    effective_mode: PublicPrivateMode
    final_status: RunFinalStatus
    format_id: str
    unavailable_reasons: tuple[UnavailableReason, ...] = Field(default_factory=tuple)


FIXTURE_CASES: tuple[FixtureCase, ...] = (
    FixtureCase(
        case_id="private_run",
        requested_mode="private",
        effective_mode="private",
        final_status="completed",
        format_id="explainer",
        unavailable_reasons=("private_mode",),
    ),
    FixtureCase(
        case_id="dry_run",
        requested_mode="dry_run",
        effective_mode="dry_run",
        final_status="completed",
        format_id="comparison",
        unavailable_reasons=("dry_run_mode",),
    ),
    FixtureCase(
        case_id="public_archive_run",
        requested_mode="public_archive",
        effective_mode="public_archive",
        final_status="completed",
        format_id="ranking",
    ),
    FixtureCase(
        case_id="public_live_blocked_run",
        requested_mode="public_live",
        effective_mode="dry_run",
        final_status="blocked",
        format_id="rundown",
        unavailable_reasons=("egress_blocked", "research_vehicle_public_event_missing"),
    ),
    FixtureCase(
        case_id="monetization_blocked_run",
        requested_mode="public_monetizable",
        effective_mode="public_archive",
        final_status="blocked",
        format_id="review",
        unavailable_reasons=("monetization_blocked", "monetization_readiness_missing"),
    ),
    FixtureCase(
        case_id="refusal_run",
        requested_mode="public_archive",
        effective_mode="dry_run",
        final_status="refused",
        format_id="refusal_breakdown",
        unavailable_reasons=("unsupported_claim", "missing_evidence_ref"),
    ),
    FixtureCase(
        case_id="correction_run",
        requested_mode="public_archive",
        effective_mode="public_archive",
        final_status="corrected",
        format_id="evidence_audit",
    ),
    FixtureCase(
        case_id="conversion_held_run",
        requested_mode="public_archive",
        effective_mode="dry_run",
        final_status="conversion_held",
        format_id="bracket",
        unavailable_reasons=("research_vehicle_public_event_missing",),
    ),
    FixtureCase(
        case_id="dry_run_tier_list",
        requested_mode="dry_run",
        effective_mode="dry_run",
        final_status="completed",
        format_id="tier_list",
        unavailable_reasons=("dry_run_mode",),
    ),
    FixtureCase(
        case_id="public_safe_evidence_audit",
        requested_mode="public_archive",
        effective_mode="public_archive",
        final_status="completed",
        format_id="evidence_audit",
    ),
    FixtureCase(
        case_id="rights_blocked_react_commentary",
        requested_mode="public_monetizable",
        effective_mode="dry_run",
        final_status="blocked",
        format_id="react_commentary",
        unavailable_reasons=("rights_blocked", "third_party_media_blocked"),
    ),
    FixtureCase(
        case_id="world_surface_blocked_run",
        requested_mode="public_live",
        effective_mode="private",
        final_status="blocked",
        format_id="watch_along",
        unavailable_reasons=("world_surface_blocked", "witness_missing"),
    ),
)
FIXTURE_CASES_BY_ID: dict[FixtureCaseId, FixtureCase] = {
    fixture.case_id: fixture for fixture in FIXTURE_CASES
}


def append_run_store_event(
    events: Sequence[ContentProgrammeRunStoreEvent],
    event: ContentProgrammeRunStoreEvent,
) -> tuple[ContentProgrammeRunStoreEvent, ...]:
    """Return a new event tuple only when the event can be appended without mutation."""

    if any(existing.event_id == event.event_id for existing in events):
        raise ValueError(f"duplicate event_id: {event.event_id}")
    if any(existing.idempotency_key == event.idempotency_key for existing in events):
        raise ValueError(f"duplicate idempotency_key: {event.idempotency_key}")
    if events and event.sequence <= events[-1].sequence:
        raise ValueError("run-store events must append with increasing sequence numbers")
    return (*events, event)


def decide_fail_closed_mode(
    requested_mode: PublicPrivateMode,
    evidence_refs: Iterable[str],
    unavailable_reasons: Iterable[UnavailableReason] = (),
) -> FailClosedDecision:
    """Downgrade/refuse public intent when required evidence is missing."""

    reasons = tuple(dict.fromkeys(unavailable_reasons))
    if tuple(evidence_refs):
        return FailClosedDecision(
            requested_mode=requested_mode,
            effective_mode=requested_mode,
            final_status="selected",
            public_claim_allowed=requested_mode in {"public_live", "public_archive"},
            unavailable_reasons=reasons,
        )

    fail_reasons = tuple(dict.fromkeys((*reasons, "missing_evidence_ref")))
    return FailClosedDecision(
        requested_mode=requested_mode,
        effective_mode="dry_run",
        final_status="refused",
        public_claim_allowed=False,
        unavailable_reasons=fail_reasons,
    )


def command_execution_allows_posterior_update(record: CommandExecutionRecord) -> bool:
    """Selection, command acceptance, and execution are never witness updates."""

    return bool(record.posterior_update_allowed)


def witnessed_outcome_allows_posterior_update(outcome: WitnessedOutcomeRecord) -> bool:
    """Only witnessed outcomes with evidence envelopes can update posteriors."""

    return (
        outcome.posterior_update_allowed
        and outcome.witness_state == "witness_verified"
        and bool(outcome.evidence_envelope_refs)
    )


def public_conversion_is_allowed(candidate: ConversionCandidate) -> bool:
    """Check public conversion blockers without re-evaluating programme semantics."""

    if candidate.state not in {"candidate", "linked", "emitted"}:
        return False
    if candidate.unavailable_reasons:
        return False
    if (
        candidate.requires_research_vehicle_public_event
        and candidate.research_vehicle_public_event_ref is None
    ):
        return False
    if candidate.conversion_type == "shorts" and candidate.owned_cleared_av_ref is None:
        return False
    return not (
        candidate.conversion_type == "monetization" and candidate.monetization_readiness_ref is None
    )


def _fixture_health_state(case: FixtureCase) -> WcsHealthState:
    if case.final_status == "blocked":
        return "blocked"
    if case.effective_mode == "private":
        return "private_only"
    if case.effective_mode == "dry_run":
        return "dry_run"
    return "healthy"


def build_fixture_envelope(
    case_id: FixtureCaseId,
    *,
    generated_at: datetime | None = None,
) -> ContentProgrammeRunEnvelope:
    """Build a representative aggregate-only run envelope fixture."""

    case = FIXTURE_CASES_BY_ID[case_id]
    now = generated_at or datetime(2026, 4, 29, tzinfo=UTC)
    run_id = f"run_{case.case_id}"
    opportunity_id = f"opp_{case.case_id}"
    decision_id = f"cod_{case.case_id}"
    has_evidence = "missing_evidence_ref" not in case.unavailable_reasons
    evidence_refs = (f"evidence:{case.case_id}",) if has_evidence else ()
    evidence_envelope_refs = (f"ee:{case.case_id}",) if has_evidence else ()
    public_event_ref = None
    if case.effective_mode in {"public_archive", "public_live", "public_monetizable"}:
        public_event_ref = f"rvpe:{case.case_id}"

    rights_public_mode = RightsPrivacyPublicMode(
        requested_mode=case.requested_mode,
        effective_mode=case.effective_mode,
        rights_state="blocked" if "rights_blocked" in case.unavailable_reasons else "cleared",
        privacy_state="public_safe" if case.effective_mode != "private" else "operator_private",
        public_event_policy_state="linked" if public_event_ref else "held",
        monetization_state=(
            "blocked" if "monetization_blocked" in case.unavailable_reasons else "not_requested"
        ),
        unavailable_reasons=case.unavailable_reasons,
    )
    selected = CommandExecutionRecord(
        record_id=f"selected:{case.case_id}",
        state="selected",
        occurred_at=now,
        refs=(decision_id,),
    )
    commanded = CommandExecutionRecord(
        record_id=f"commanded:{case.case_id}",
        state="dry_run" if case.effective_mode == "dry_run" else "accepted",
        occurred_at=now,
        refs=(run_id,),
    )
    witnessed = WitnessedOutcomeRecord(
        outcome_id=f"outcome:{case.case_id}",
        witness_state="witness_verified" if has_evidence else "witness_unavailable",
        evidence_envelope_refs=evidence_envelope_refs,
        capability_outcome_ref=f"coe:{case.case_id}",
        posterior_update_allowed=has_evidence and case.final_status == "completed",
    )

    boundary = ProgrammeBoundaryEventRef(
        boundary_id=f"pbe_{case.case_id}_001",
        sequence=1,
        boundary_type="programme.started",
        duplicate_key=f"programme:{run_id}:programme.started:001",
        cuepoint_chapter_distinction="none",
        public_event_mapping_ref=public_event_ref,
        mapping_state="research_vehicle_linked" if public_event_ref else "held",
        unavailable_reasons=case.unavailable_reasons,
    )
    conversion = ConversionCandidate(
        candidate_id=f"conversion:{case.case_id}",
        conversion_type="shorts" if case.format_id == "what_is_this" else "archive_replay",
        state="linked" if public_event_ref else "held",
        research_vehicle_public_event_ref=public_event_ref,
        unavailable_reasons=case.unavailable_reasons,
    )

    return ContentProgrammeRunEnvelope(
        run_id=run_id,
        programme_id=f"programme_{case.format_id}",
        opportunity_decision_id=decision_id,
        format_id=case.format_id,
        condition_id="condition_content_programming_20260429",
        selected_at=now,
        selected_by="content_opportunity_model",
        grounding_question=f"What can this {case.format_id} run ground from declared evidence?",
        requested_public_private_mode=case.requested_mode,
        public_private_mode=case.effective_mode,
        rights_privacy_public_mode=rights_public_mode,
        selected_opportunity=SelectedOpportunityRef(
            decision_id=decision_id,
            decision_ref=f"content-opportunity-model:{decision_id}",
            opportunity_id=opportunity_id,
            content_opportunity_tuple_ref=f"tuple:{opportunity_id}",
            posterior_sample_refs=(f"posterior:{case.case_id}",),
            reward_vector_ref=f"reward:{case.case_id}",
        ),
        selected_format=SelectedFormatRef(
            format_id=case.format_id,
            registry_ref="schemas/content-programme-format.schema.json",
            row_ref=f"schemas/content-programme-format.schema.json#{case.format_id}",
            grounding_question=f"What can this {case.format_id} run ground?",
            grounding_attempt_types=("classification", "uncertainty"),
        ),
        broadcast_refs=(f"broadcast:{case.case_id}",)
        if case.requested_mode == "public_live"
        else (),
        archive_refs=(f"archive:{case.case_id}",)
        if case.effective_mode == "public_archive"
        else (),
        selected_input_refs=(f"input:{case.case_id}",) if has_evidence else (),
        substrate_refs=(f"substrate:{case.case_id}",),
        semantic_capability_refs=(f"capability:{case.format_id}",),
        director_plan=DirectorPlanRef(
            director_snapshot_ref=f"director-snapshot:{case.case_id}",
            director_plan_ref=f"director-plan:{case.case_id}",
            director_move_refs=(f"director-move:{case.case_id}",),
            condition_id="condition_content_programming_20260429",
        ),
        gate_refs=GateRefs(
            grounding_gate_refs=(f"grounding-gate:{case.case_id}",) if has_evidence else (),
            rights_gate_refs=(f"rights-gate:{case.case_id}",),
            privacy_gate_refs=(f"privacy-gate:{case.case_id}",),
            public_event_gate_refs=(f"public-event-gate:{case.case_id}",),
        ),
        wcs=WcsBinding(
            semantic_substrate_refs=(f"semantic-substrate:{case.case_id}",),
            grounding_contract_refs=(f"grounding-contract:{case.case_id}",),
            evidence_envelope_refs=evidence_envelope_refs,
            witness_requirements=(
                WitnessRequirement(
                    requirement_id=f"witness-required:{case.case_id}",
                    substrate_ref=f"semantic-substrate:{case.case_id}",
                    required_witness_refs=(f"witness:{case.case_id}",),
                    missing_witness_refs=(
                        (f"witness:{case.case_id}",)
                        if "witness_missing" in case.unavailable_reasons
                        else ()
                    ),
                ),
            ),
            capability_outcome_refs=(f"coe:{case.case_id}",),
            health_state=_fixture_health_state(case),
            unavailable_reasons=case.unavailable_reasons,
            public_private_posture=rights_public_mode,
        ),
        events=(
            RunStoreEventRef(
                event_id=f"event:{case.case_id}:selected", sequence=0, event_type="selected"
            ),
            RunStoreEventRef(
                event_id=f"event:{case.case_id}:started", sequence=1, event_type="started"
            ),
        ),
        boundary_event_refs=(boundary,),
        claims=(
            ClaimRef(
                claim_id=f"claim:{case.case_id}",
                evidence_refs=evidence_refs,
                evidence_envelope_refs=evidence_envelope_refs,
                uncertainty_ref=f"uncertainty:{case.case_id}",
                posterior_state_ref=f"posterior-state:{case.case_id}" if has_evidence else None,
            ),
        )
        if has_evidence
        else (),
        uncertainties=(
            StateRef(
                state_id=f"uncertainty:{case.case_id}",
                reason="Evidence, rights, public-event, and witness limits are explicit.",
                evidence_refs=evidence_refs,
            ),
        ),
        refusals=(
            (
                StateRef(
                    state_id=f"refusal:{case.case_id}",
                    reason="Run failed closed instead of emitting unsupported public content.",
                    evidence_refs=evidence_refs,
                ),
            )
            if case.final_status == "refused"
            else ()
        ),
        corrections=(
            (
                StateRef(
                    state_id=f"correction:{case.case_id}",
                    reason="Correction is a first-class programme output.",
                    evidence_refs=evidence_refs,
                ),
            )
            if case.final_status == "corrected"
            else ()
        ),
        scores=(
            ScoreRef(
                evaluation_id=f"fge:{case.case_id}",
                dimension="uncertainty",
                score_ref=f"score:{case.case_id}",
                evidence_refs=evidence_refs,
            ),
        )
        if has_evidence
        else (),
        conversion_candidates=(conversion,),
        command_execution=CommandExecutionTrace(
            selected=selected,
            commanded_states=(commanded,),
            executed_states=(commanded,),
            witnessed_outcomes=(witnessed,),
        ),
        witnessed_outcomes=(witnessed,),
        adapter_exposure=AdapterExposure(ref=f"adapter-exposure:{case.case_id}"),
        final_status=case.final_status,
    )
