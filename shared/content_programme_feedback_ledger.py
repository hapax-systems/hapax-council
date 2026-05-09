"""Typed contract helpers for content programme feedback ledger events."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from shared.content_programme_run_store import (
        ContentProgrammeRunEnvelope,
        ConversionCandidate,
        ScoreRef,
        StateRef,
        WitnessedOutcomeRecord,
    )

type PublicPrivateMode = Literal[
    "private",
    "dry_run",
    "public_live",
    "public_archive",
    "public_monetizable",
]
type ProgrammeOutcomeState = Literal[
    "selected",
    "blocked",
    "dry_run",
    "public_run",
    "completed",
    "aborted",
    "refused",
    "corrected",
    "private_only",
    "conversion_held",
]
type FeedbackEventKind = Literal[
    "run_selected",
    "run_blocked",
    "dry_run_completed",
    "public_run_completed",
    "run_completed",
    "run_aborted",
    "run_refused",
    "run_corrected",
    "private_only_recorded",
    "conversion_held",
    "posterior_update_proposed",
]
type GateName = Literal[
    "truth_gate",
    "rights_gate",
    "consent_gate",
    "monetization_gate",
    "substrate_freshness_gate",
    "egress_gate",
    "no_expert_system_gate",
    "world_surface_gate",
    "public_event_gate",
    "safety_gate",
]
type GateState = Literal["pass", "warn", "fail", "held", "not_applicable"]
type PosteriorUpdateFamily = Literal[
    "grounding_quality",
    "audience_response",
    "artifact_conversion",
    "revenue_support_response",
    "rights_pass_probability",
    "safety_refusal_rate",
    "format_prior",
    "source_prior",
]
type SourceSignal = Literal[
    "format_grounding_evaluation",
    "capability_outcome_witness",
    "audience_aggregate",
    "revenue_aggregate",
    "rights_gate",
    "safety_gate",
    "artifact_conversion",
    "exploration",
    "run_lifecycle",
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
type ArtifactType = Literal[
    "archive_card",
    "chapter",
    "clip",
    "shorts",
    "dataset",
    "zine",
    "caption",
    "refusal_artifact",
    "correction_artifact",
    "support_prompt",
    "grant_packet",
]
type ArtifactState = Literal["candidate", "held", "blocked", "linked", "emitted"]
type AudienceMetricName = Literal[
    "views",
    "watch_time",
    "retention",
    "click_through_rate",
    "aggregate_comment_signal",
    "rewatch",
    "follow_through",
    "support_intent",
]
type RevenueProxyName = Literal[
    "platform_revenue_readiness",
    "support_count_bucket",
    "support_intent",
    "grant_lead_signal",
    "license_interest",
    "artifact_conversion_intent",
    "product_interest",
]
type SafetyMetricName = Literal[
    "unsupported_claim_count",
    "overbroad_claim_count",
    "refusal_count",
    "correction_count",
    "rights_block_count",
    "privacy_block_count",
    "egress_block_count",
    "witness_missing_count",
    "safety_block_count",
]

PROGRAMME_OUTCOME_STATES: tuple[ProgrammeOutcomeState, ...] = (
    "selected",
    "blocked",
    "dry_run",
    "public_run",
    "completed",
    "aborted",
    "refused",
    "corrected",
    "private_only",
    "conversion_held",
)
FEEDBACK_EVENT_KINDS: tuple[FeedbackEventKind, ...] = (
    "run_selected",
    "run_blocked",
    "dry_run_completed",
    "public_run_completed",
    "run_completed",
    "run_aborted",
    "run_refused",
    "run_corrected",
    "private_only_recorded",
    "conversion_held",
    "posterior_update_proposed",
)
POSTERIOR_UPDATE_FAMILIES: tuple[PosteriorUpdateFamily, ...] = (
    "grounding_quality",
    "audience_response",
    "artifact_conversion",
    "revenue_support_response",
    "rights_pass_probability",
    "safety_refusal_rate",
    "format_prior",
    "source_prior",
)
NON_PUBLIC_TRUTH_STATES: frozenset[ProgrammeOutcomeState] = frozenset(
    {"blocked", "refused", "corrected", "private_only", "aborted", "conversion_held"}
)
CLAIM_BEARING_PROGRAMME_STATES: frozenset[ProgrammeOutcomeState] = frozenset(
    {"public_run", "completed"}
)
NON_CLAIM_BEARING_PROGRAMME_STATES: frozenset[ProgrammeOutcomeState] = frozenset(
    state for state in PROGRAMME_OUTCOME_STATES if state not in CLAIM_BEARING_PROGRAMME_STATES
)
GROUNDING_UPDATE_ELIGIBLE_STATES: frozenset[ProgrammeOutcomeState] = frozenset(
    {"dry_run", "public_run", "completed"}
)
PUBLIC_CLAIM_MODES: frozenset[PublicPrivateMode] = frozenset(
    {"public_live", "public_archive", "public_monetizable"}
)
EVENT_KIND_BY_PROGRAMME_STATE: dict[ProgrammeOutcomeState, FeedbackEventKind] = {
    "selected": "run_selected",
    "blocked": "run_blocked",
    "dry_run": "dry_run_completed",
    "public_run": "public_run_completed",
    "completed": "run_completed",
    "aborted": "run_aborted",
    "refused": "run_refused",
    "corrected": "run_corrected",
    "private_only": "private_only_recorded",
    "conversion_held": "conversion_held",
}
RUN_FINAL_STATUS_TO_PROGRAMME_STATE: dict[str, ProgrammeOutcomeState] = {
    "selected": "selected",
    "running": "selected",
    "blocked": "blocked",
    "refused": "refused",
    "corrected": "corrected",
    "conversion_held": "conversion_held",
    "aborted": "aborted",
}
CONVERSION_ARTIFACT_TYPES: dict[str, ArtifactType] = {
    "archive_replay": "archive_card",
    "chapter": "chapter",
    "live_cuepoint": "chapter",
    "shorts": "shorts",
    "metadata": "caption",
    "refusal_artifact": "refusal_artifact",
    "correction_artifact": "correction_artifact",
    "support_prompt": "support_prompt",
    "grant_packet": "grant_packet",
    "monetization": "support_prompt",
}


class FeedbackLedgerModel(BaseModel):
    """Strict immutable base for feedback-ledger helper records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class GateOutcome(FeedbackLedgerModel):
    gate_name: GateName
    state: GateState
    gate_ref: str | None = None
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    unavailable_reasons: tuple[str, ...] = Field(default_factory=tuple)
    blocks_public_claim: bool
    posterior_update_allowed: bool = False


class GroundingOutput(FeedbackLedgerModel):
    evaluation_id: str
    event_kind: Literal["format_grounding_evaluation"] = "format_grounding_evaluation"
    grounding_quality_score: float | None = Field(default=None, ge=0, le=1)
    update_allowed: bool = False
    infraction_refs: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    posterior_refs: tuple[str, ...] = Field(default_factory=tuple)


class ArtifactOutput(FeedbackLedgerModel):
    artifact_id: str
    artifact_type: ArtifactType
    state: ArtifactState
    public_event_ref: str | None = None
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class AudienceMetric(FeedbackLedgerModel):
    metric_name: AudienceMetricName
    value: float = Field(ge=0)
    sample_size: int = Field(ge=0)
    identity_scope: Literal["aggregate"] = "aggregate"
    aggregate_ref: str
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class AudienceOutcome(FeedbackLedgerModel):
    aggregate_only: Literal[True] = True
    per_person_identity_allowed: Literal[False] = False
    raw_comment_text_allowed: Literal[False] = False
    public_payer_identity_allowed: Literal[False] = False
    metrics: tuple[AudienceMetric, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class RevenueProxy(FeedbackLedgerModel):
    proxy_name: RevenueProxyName
    value: float
    aggregate_only: Literal[True] = True
    public_payer_identity_allowed: Literal[False] = False
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class SafetyMetric(FeedbackLedgerModel):
    metric_name: SafetyMetricName
    count: int = Field(ge=0)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class CapabilityOutcomeWitness(FeedbackLedgerModel):
    capability_outcome_ref: str
    capability_outcome_envelope_ref: str
    witness_state: WitnessState
    evidence_envelope_refs: tuple[str, ...] = Field(default_factory=tuple)
    posterior_update_allowed: bool = False


class PosteriorUpdate(FeedbackLedgerModel):
    update_id: str
    posterior_family: PosteriorUpdateFamily
    target_ref: str
    source_signal: SourceSignal
    value: float
    confidence: float = Field(ge=0, le=1)
    prior_ref: str
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    update_allowed: bool = False
    blocked_reason: str | None = None


class HermeneuticDeltaRecord(FeedbackLedgerModel):
    """What a prep cycle revealed about commitments or blind spots."""

    delta_id: str
    source_ref: str
    delta_kind: Literal[
        "new_consequence",
        "reinforced_consequence",
        "revised_consequence",
        "novel_dimension",
    ]
    consequence_kind: str
    changed_dimensions: tuple[str, ...] = Field(default_factory=tuple)
    prior_encounter_count: int = Field(ge=0, default=0)
    summary: str


class ExplorationSignal(FeedbackLedgerModel):
    exploration_budget_ref: str
    exploration_regret: float = Field(ge=0, le=1)
    novelty_distance: float = Field(ge=0, le=1)
    cooldown_effect_ref: str | None = None
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)


class SeparationPolicy(FeedbackLedgerModel):
    selected_commanded_states_update_posteriors: Literal[False] = False
    witnessed_capability_outcomes_update_grounding: Literal[True] = True
    format_grounding_evaluations_update_grounding: Literal[True] = True
    engagement_can_override_grounding: Literal[False] = False
    revenue_can_override_grounding: Literal[False] = False
    audience_data_aggregate_only: Literal[True] = True
    per_person_audience_state_allowed: Literal[False] = False
    public_payer_identity_allowed: Literal[False] = False
    blocked_claims_become_public_truth: Literal[False] = False


class LearningPolicy(FeedbackLedgerModel):
    blocked_refused_corrected_private_only_are_learning_events: Literal[True] = True
    public_truth_claim_allowed: bool = False
    posterior_store_mutation_allowed: Literal[False] = False


class ContentProgrammeFeedbackEvent(FeedbackLedgerModel):
    schema_version: Literal[1] = 1
    ledger_event_id: str
    run_id: str
    programme_id: str
    opportunity_decision_id: str
    format_id: str
    input_source_id: str
    subject_cluster: str
    occurred_at: datetime
    event_kind: FeedbackEventKind
    programme_state: ProgrammeOutcomeState
    public_private_mode: PublicPrivateMode
    run_store_ref: str
    selected_state_refs: tuple[str, ...] = Field(default_factory=tuple)
    commanded_state_refs: tuple[str, ...] = Field(default_factory=tuple)
    gate_outcomes: tuple[GateOutcome, ...] = Field(default_factory=tuple)
    grounding_outputs: tuple[GroundingOutput, ...] = Field(default_factory=tuple)
    artifact_outputs: tuple[ArtifactOutput, ...] = Field(default_factory=tuple)
    audience_outcome: AudienceOutcome = Field(default_factory=AudienceOutcome)
    revenue_proxies: tuple[RevenueProxy, ...] = Field(default_factory=tuple)
    safety_metrics: tuple[SafetyMetric, ...] = Field(default_factory=tuple)
    witnessed_capability_outcomes: tuple[CapabilityOutcomeWitness, ...] = Field(
        default_factory=tuple
    )
    nested_programme_outcome_refs: tuple[str, ...] = Field(default_factory=tuple)
    posterior_updates: tuple[PosteriorUpdate, ...] = Field(default_factory=tuple)
    hermeneutic_deltas: tuple[HermeneuticDeltaRecord, ...] = Field(default_factory=tuple)
    exploration: ExplorationSignal
    separation_policy: SeparationPolicy = Field(default_factory=SeparationPolicy)
    learning_policy: LearningPolicy = Field(default_factory=LearningPolicy)
    append_only: Literal[True] = True
    idempotency_key: str


class SchedulerPolicyFeedback(FeedbackLedgerModel):
    """Minimal machine-readable view consumed by scheduler policy."""

    feedback_event_id: str
    run_id: str
    programme_state: ProgrammeOutcomeState
    public_private_mode: PublicPrivateMode
    public_truth_claim_allowed: bool
    allowed_posterior_update_refs: tuple[str, ...] = Field(default_factory=tuple)
    blocked_posterior_update_refs: tuple[str, ...] = Field(default_factory=tuple)
    allowed_posterior_families: tuple[PosteriorUpdateFamily, ...] = Field(default_factory=tuple)
    grounding_update_refs: tuple[str, ...] = Field(default_factory=tuple)
    metric_response_update_refs: tuple[str, ...] = Field(default_factory=tuple)
    operator_scoring_required: Literal[False] = False
    audience_revenue_can_upgrade_grounding: Literal[False] = False


def append_feedback_event(
    events: Sequence[ContentProgrammeFeedbackEvent],
    event: ContentProgrammeFeedbackEvent,
) -> tuple[ContentProgrammeFeedbackEvent, ...]:
    """Return a new event tuple only when the append would not rewrite history."""

    if any(existing.ledger_event_id == event.ledger_event_id for existing in events):
        raise ValueError(f"duplicate ledger_event_id: {event.ledger_event_id}")
    if any(existing.idempotency_key == event.idempotency_key for existing in events):
        raise ValueError(f"duplicate idempotency_key: {event.idempotency_key}")
    return (*events, event)


def hermeneutic_delta_records_from_deltas(
    deltas: Iterable[Any],
) -> tuple[HermeneuticDeltaRecord, ...]:
    """Convert hermeneutic_spiral.HermeneuticDelta objects into ledger records."""
    records: list[HermeneuticDeltaRecord] = []
    for delta in deltas:
        records.append(
            HermeneuticDeltaRecord(
                delta_id=delta.delta_id,
                source_ref=delta.source_ref,
                delta_kind=delta.delta_kind,
                consequence_kind=delta.consequence_kind,
                changed_dimensions=delta.changed_dimensions,
                prior_encounter_count=len(delta.prior_encounter_ids),
                summary=delta.summary,
            )
        )
    return tuple(records)


def audience_outcome_is_aggregate_only(outcome: AudienceOutcome) -> bool:
    """Check that audience and support-facing state contains aggregate observations only."""

    return (
        outcome.aggregate_only
        and not outcome.per_person_identity_allowed
        and not outcome.raw_comment_text_allowed
        and not outcome.public_payer_identity_allowed
        and all(metric.identity_scope == "aggregate" for metric in outcome.metrics)
    )


def witnessed_outcome_allows_posterior_update(witness: CapabilityOutcomeWitness) -> bool:
    """Only verified witnessed capability outcomes with envelopes can update posteriors."""

    return (
        witness.posterior_update_allowed
        and witness.witness_state == "witness_verified"
        and witness.capability_outcome_envelope_ref.startswith("CapabilityOutcomeEnvelope:")
        and bool(witness.evidence_envelope_refs)
    )


def posterior_update_is_evidence_bound(update: PosteriorUpdate) -> bool:
    """A posterior update proposal must have evidence and no blocked reason."""

    return update.update_allowed and bool(update.evidence_refs) and update.blocked_reason is None


def event_allows_public_truth_claim(event: ContentProgrammeFeedbackEvent) -> bool:
    """Blocked/refused/corrected/private-only learning events never become public truth."""

    if event.programme_state in NON_PUBLIC_TRUTH_STATES:
        return False
    if event.learning_policy.public_truth_claim_allowed is False:
        return False
    return all(not gate.blocks_public_claim for gate in event.gate_outcomes)


def programme_state_from_run_envelope(run: ContentProgrammeRunEnvelope) -> ProgrammeOutcomeState:
    """Map run-store final status plus effective mode into feedback lifecycle state."""

    if run.final_status == "completed":
        if run.public_private_mode == "private":
            return "private_only"
        if run.public_private_mode == "dry_run":
            return "dry_run"
        return "public_run"
    return RUN_FINAL_STATUS_TO_PROGRAMME_STATE[run.final_status]


def build_feedback_event_from_run_envelope(
    run: ContentProgrammeRunEnvelope,
    *,
    occurred_at: datetime | None = None,
    audience_outcome: AudienceOutcome | None = None,
    revenue_proxies: Sequence[RevenueProxy] = (),
    exploration: ExplorationSignal | None = None,
    hermeneutic_deltas: Iterable[Any] = (),
) -> ContentProgrammeFeedbackEvent:
    """Build the append-only feedback event for an actual programme run envelope."""

    from shared.content_programme_run_store import nested_outcome_refs_for_feedback

    state = programme_state_from_run_envelope(run)
    gate_outcomes = _gate_outcomes_from_run(run, state)
    grounding_outputs = _grounding_outputs_from_run(run, state)
    artifact_outputs = _artifact_outputs_from_run(run)
    safety_metrics = _safety_metrics_from_run(run)
    witnesses = _capability_witnesses_from_run(run)
    effective_audience = audience_outcome or AudienceOutcome()
    effective_revenue = tuple(revenue_proxies)
    public_truth_allowed = _public_truth_claim_allowed(state, gate_outcomes, run)

    return ContentProgrammeFeedbackEvent(
        ledger_event_id=f"feedback:{run.run_id}:{state}",
        run_id=run.run_id,
        programme_id=run.programme_id,
        opportunity_decision_id=run.opportunity_decision_id,
        format_id=run.format_id,
        input_source_id=_input_source_id(run),
        subject_cluster=run.selected_opportunity.opportunity_id,
        occurred_at=occurred_at or run.selected_at,
        event_kind=EVENT_KIND_BY_PROGRAMME_STATE[state],
        programme_state=state,
        public_private_mode=run.public_private_mode,
        run_store_ref=f"ContentProgrammeRunEnvelope:{run.run_id}",
        selected_state_refs=(run.command_execution.selected.record_id,),
        commanded_state_refs=tuple(
            record.record_id
            for record in (
                *run.command_execution.commanded_states,
                *run.command_execution.executed_states,
            )
        ),
        gate_outcomes=gate_outcomes,
        grounding_outputs=grounding_outputs,
        artifact_outputs=artifact_outputs,
        audience_outcome=effective_audience,
        revenue_proxies=effective_revenue,
        safety_metrics=safety_metrics,
        witnessed_capability_outcomes=witnesses,
        nested_programme_outcome_refs=nested_outcome_refs_for_feedback(run),
        posterior_updates=_posterior_updates_from_run(
            run,
            state,
            grounding_outputs,
            artifact_outputs,
            effective_audience,
            effective_revenue,
            safety_metrics,
        ),
        hermeneutic_deltas=hermeneutic_delta_records_from_deltas(hermeneutic_deltas),
        exploration=exploration or _default_exploration_signal(run, state),
        learning_policy=LearningPolicy(public_truth_claim_allowed=public_truth_allowed),
        idempotency_key=f"{run.run_id}:{run.final_status}:{run.public_private_mode}:feedback",
    )


def build_scheduler_policy_feedback(
    event: ContentProgrammeFeedbackEvent,
) -> SchedulerPolicyFeedback:
    """Expose feedback entries to scheduler policy without operator scoring."""

    allowed = tuple(update for update in event.posterior_updates if update.update_allowed)
    blocked = tuple(update for update in event.posterior_updates if not update.update_allowed)
    metric_updates = tuple(
        update.update_id
        for update in allowed
        if update.posterior_family in {"audience_response", "revenue_support_response"}
    )

    return SchedulerPolicyFeedback(
        feedback_event_id=event.ledger_event_id,
        run_id=event.run_id,
        programme_state=event.programme_state,
        public_private_mode=event.public_private_mode,
        public_truth_claim_allowed=event_allows_public_truth_claim(event),
        allowed_posterior_update_refs=tuple(update.update_id for update in allowed),
        blocked_posterior_update_refs=tuple(update.update_id for update in blocked),
        allowed_posterior_families=tuple(
            dict.fromkeys(update.posterior_family for update in allowed)
        ),
        grounding_update_refs=tuple(
            update.update_id for update in allowed if update.posterior_family == "grounding_quality"
        ),
        metric_response_update_refs=metric_updates,
    )


def _dedupe_strs(items: Iterable[str | None]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _input_source_id(run: ContentProgrammeRunEnvelope) -> str:
    if run.selected_input_refs:
        return run.selected_input_refs[0]
    return "input:unavailable"


def _is_public_claim_mode(mode: PublicPrivateMode) -> bool:
    return mode in PUBLIC_CLAIM_MODES


def _combined_unavailable_reasons(run: ContentProgrammeRunEnvelope) -> tuple[str, ...]:
    reasons: list[str] = []
    reasons.extend(run.rights_privacy_public_mode.unavailable_reasons)
    reasons.extend(run.wcs.unavailable_reasons)
    for boundary in run.boundary_event_refs:
        reasons.extend(boundary.unavailable_reasons)
    for candidate in run.conversion_candidates:
        reasons.extend(candidate.unavailable_reasons)
    return _dedupe_strs(reasons)


def _state_refs(states: Iterable[StateRef]) -> tuple[str, ...]:
    return _dedupe_strs(state.state_id for state in states)


def _state_evidence_refs(states: Iterable[StateRef]) -> tuple[str, ...]:
    refs: list[str] = []
    for state in states:
        refs.append(state.state_id)
        refs.extend(state.evidence_refs)
    return _dedupe_strs(refs)


def _score_evidence_refs(scores: Iterable[ScoreRef]) -> tuple[str, ...]:
    refs: list[str] = []
    for score in scores:
        refs.append(score.evaluation_id)
        refs.extend(score.evidence_refs)
    return _dedupe_strs(refs)


def _combined_run_evidence_refs(run: ContentProgrammeRunEnvelope) -> tuple[str, ...]:
    refs: list[str] = []
    refs.extend(run.selected_input_refs)
    refs.extend(run.wcs.evidence_envelope_refs)
    for claim in run.claims:
        refs.extend(claim.evidence_refs)
        refs.extend(claim.evidence_envelope_refs)
    for score in run.scores:
        refs.append(score.evaluation_id)
        refs.extend(score.evidence_refs)
    refs.extend(_state_evidence_refs(run.refusals))
    refs.extend(_state_evidence_refs(run.corrections))
    return _dedupe_strs(refs)


def _public_event_refs(run: ContentProgrammeRunEnvelope) -> tuple[str, ...]:
    refs: list[str] = []
    for boundary in run.boundary_event_refs:
        refs.append(boundary.public_event_mapping_ref)
    for candidate in run.conversion_candidates:
        refs.append(candidate.research_vehicle_public_event_ref)
    return _dedupe_strs(refs)


def _has_verified_witness(run: ContentProgrammeRunEnvelope) -> bool:
    outcomes = (*run.witnessed_outcomes, *run.command_execution.witnessed_outcomes)
    return any(_run_witness_allows_update(outcome) for outcome in outcomes)


def _run_witness_allows_update(outcome: WitnessedOutcomeRecord) -> bool:
    return (
        outcome.posterior_update_allowed
        and outcome.witness_state == "witness_verified"
        and bool(outcome.evidence_envelope_refs)
    )


def _grounding_update_allowed(
    run: ContentProgrammeRunEnvelope, state: ProgrammeOutcomeState
) -> bool:
    return (
        state in GROUNDING_UPDATE_ELIGIBLE_STATES
        and bool(run.scores)
        and bool(_score_evidence_refs(run.scores))
        and _has_verified_witness(run)
    )


def _gate_outcomes_from_run(
    run: ContentProgrammeRunEnvelope,
    state: ProgrammeOutcomeState,
) -> tuple[GateOutcome, ...]:
    reasons = _combined_unavailable_reasons(run)
    evidence_refs = _combined_run_evidence_refs(run)
    public_event_refs = _public_event_refs(run)
    truth_blocked = (
        not evidence_refs
        or "missing_evidence_ref" in reasons
        or "missing_grounding_gate" in reasons
        or "grounding_gate_failed" in reasons
    )
    rights_blocked = run.rights_privacy_public_mode.rights_state in {"blocked", "unknown"} or any(
        reason in {"rights_blocked", "third_party_media_blocked"} for reason in reasons
    )
    privacy_blocked = run.rights_privacy_public_mode.privacy_state in {"blocked", "unknown"} or (
        "privacy_blocked" in reasons
    )
    public_event_blocked = _is_public_claim_mode(run.public_private_mode) and not public_event_refs
    monetization_blocked = (
        run.requested_public_private_mode == "public_monetizable"
        and run.rights_privacy_public_mode.monetization_state != "ready"
    )
    safety_blocked = state in {"blocked", "refused", "corrected", "aborted"} or any(
        reason
        in {
            "unsupported_claim",
            "egress_blocked",
            "world_surface_blocked",
            "witness_missing",
        }
        for reason in reasons
    )

    return (
        GateOutcome(
            gate_name="truth_gate",
            state="fail" if truth_blocked else "pass",
            gate_ref=run.gate_refs.grounding_gate_refs[0]
            if run.gate_refs.grounding_gate_refs
            else None,
            evidence_refs=evidence_refs,
            unavailable_reasons=reasons if truth_blocked else (),
            blocks_public_claim=truth_blocked,
            posterior_update_allowed=not truth_blocked,
        ),
        GateOutcome(
            gate_name="rights_gate",
            state="fail" if rights_blocked else "pass",
            gate_ref=run.gate_refs.rights_gate_refs[0] if run.gate_refs.rights_gate_refs else None,
            evidence_refs=run.gate_refs.rights_gate_refs,
            unavailable_reasons=tuple(
                reason
                for reason in reasons
                if reason in {"rights_blocked", "third_party_media_blocked"}
            ),
            blocks_public_claim=rights_blocked,
            posterior_update_allowed=bool(run.gate_refs.rights_gate_refs),
        ),
        GateOutcome(
            gate_name="consent_gate",
            state="fail" if privacy_blocked else "pass",
            gate_ref=run.gate_refs.privacy_gate_refs[0]
            if run.gate_refs.privacy_gate_refs
            else None,
            evidence_refs=run.gate_refs.privacy_gate_refs,
            unavailable_reasons=tuple(
                reason for reason in reasons if reason in {"privacy_blocked", "private_mode"}
            ),
            blocks_public_claim=privacy_blocked,
            posterior_update_allowed=bool(run.gate_refs.privacy_gate_refs),
        ),
        GateOutcome(
            gate_name="public_event_gate",
            state="fail" if public_event_blocked else "pass",
            gate_ref=run.gate_refs.public_event_gate_refs[0]
            if run.gate_refs.public_event_gate_refs
            else None,
            evidence_refs=public_event_refs,
            unavailable_reasons=tuple(
                reason
                for reason in reasons
                if reason in {"research_vehicle_public_event_missing", "egress_blocked"}
            ),
            blocks_public_claim=public_event_blocked,
            posterior_update_allowed=bool(public_event_refs),
        ),
        GateOutcome(
            gate_name="monetization_gate",
            state="fail" if monetization_blocked else "not_applicable",
            gate_ref=run.gate_refs.monetization_gate_refs[0]
            if run.gate_refs.monetization_gate_refs
            else None,
            evidence_refs=run.gate_refs.monetization_gate_refs,
            unavailable_reasons=tuple(
                reason
                for reason in reasons
                if reason in {"monetization_blocked", "monetization_readiness_missing"}
            ),
            blocks_public_claim=monetization_blocked,
            posterior_update_allowed=bool(run.gate_refs.monetization_gate_refs),
        ),
        GateOutcome(
            gate_name="safety_gate",
            state="fail" if safety_blocked else "pass",
            gate_ref=None,
            evidence_refs=_state_evidence_refs((*run.refusals, *run.corrections)),
            unavailable_reasons=tuple(
                reason
                for reason in reasons
                if reason
                in {
                    "unsupported_claim",
                    "egress_blocked",
                    "world_surface_blocked",
                    "witness_missing",
                }
            ),
            blocks_public_claim=safety_blocked,
            posterior_update_allowed=safety_blocked,
        ),
    )


def _grounding_outputs_from_run(
    run: ContentProgrammeRunEnvelope,
    state: ProgrammeOutcomeState,
) -> tuple[GroundingOutput, ...]:
    update_allowed = _grounding_update_allowed(run, state)
    posterior_refs = _dedupe_strs(claim.posterior_state_ref for claim in run.claims)
    reasons = _combined_unavailable_reasons(run)
    infraction_refs = tuple(
        f"unavailable:{reason}"
        for reason in reasons
        if reason
        in {
            "missing_evidence_ref",
            "grounding_gate_failed",
            "unsupported_claim",
            "witness_missing",
        }
    )

    return tuple(
        GroundingOutput(
            evaluation_id=score.evaluation_id,
            grounding_quality_score=None,
            update_allowed=update_allowed and bool(score.evidence_refs),
            infraction_refs=infraction_refs,
            evidence_refs=_dedupe_strs((*score.evidence_refs, *run.wcs.evidence_envelope_refs)),
            posterior_refs=posterior_refs,
        )
        for score in run.scores
    )


def _artifact_type_from_conversion(candidate: ConversionCandidate) -> ArtifactType:
    return CONVERSION_ARTIFACT_TYPES[candidate.conversion_type]


def _artifact_outputs_from_run(run: ContentProgrammeRunEnvelope) -> tuple[ArtifactOutput, ...]:
    outputs: list[ArtifactOutput] = []
    for candidate in run.conversion_candidates:
        outputs.append(
            ArtifactOutput(
                artifact_id=candidate.candidate_id,
                artifact_type=_artifact_type_from_conversion(candidate),
                state=candidate.state,
                public_event_ref=candidate.research_vehicle_public_event_ref,
                evidence_refs=_dedupe_strs(
                    (
                        candidate.candidate_id,
                        candidate.research_vehicle_public_event_ref,
                        candidate.owned_cleared_av_ref,
                        candidate.monetization_readiness_ref,
                        *run.wcs.evidence_envelope_refs,
                    )
                ),
            )
        )
    for refusal in run.refusals:
        outputs.append(
            ArtifactOutput(
                artifact_id=f"artifact:{refusal.state_id}",
                artifact_type="refusal_artifact",
                state="emitted",
                public_event_ref=None,
                evidence_refs=_state_evidence_refs((refusal,)),
            )
        )
    for correction in run.corrections:
        outputs.append(
            ArtifactOutput(
                artifact_id=f"artifact:{correction.state_id}",
                artifact_type="correction_artifact",
                state="emitted",
                public_event_ref=_public_event_refs(run)[0] if _public_event_refs(run) else None,
                evidence_refs=_state_evidence_refs((correction,)),
            )
        )
    return tuple(outputs)


def _safety_metrics_from_run(run: ContentProgrammeRunEnvelope) -> tuple[SafetyMetric, ...]:
    reasons = _combined_unavailable_reasons(run)
    metrics: list[SafetyMetric] = []

    def add_metric(metric_name: SafetyMetricName, count: int, refs: Iterable[str | None]) -> None:
        if count > 0:
            metrics.append(
                SafetyMetric(
                    metric_name=metric_name,
                    count=count,
                    evidence_refs=_dedupe_strs(refs),
                )
            )

    add_metric(
        "refusal_count",
        max(1, len(run.refusals)) if run.final_status == "refused" else 0,
        _state_refs(run.refusals),
    )
    add_metric(
        "correction_count",
        max(1, len(run.corrections)) if run.final_status == "corrected" else 0,
        _state_refs(run.corrections),
    )
    add_metric(
        "unsupported_claim_count",
        1 if "unsupported_claim" in reasons else 0,
        (*_state_refs(run.refusals), *_score_evidence_refs(run.scores)),
    )
    add_metric(
        "rights_block_count",
        1
        if run.rights_privacy_public_mode.rights_state == "blocked"
        or any(reason in {"rights_blocked", "third_party_media_blocked"} for reason in reasons)
        else 0,
        (*run.gate_refs.rights_gate_refs, *_combined_run_evidence_refs(run)),
    )
    add_metric(
        "privacy_block_count",
        1 if run.rights_privacy_public_mode.privacy_state == "blocked" else 0,
        run.gate_refs.privacy_gate_refs,
    )
    add_metric(
        "egress_block_count",
        1 if "egress_blocked" in reasons or "world_surface_blocked" in reasons else 0,
        run.gate_refs.public_event_gate_refs,
    )
    add_metric(
        "witness_missing_count",
        1 if "witness_missing" in reasons else 0,
        run.wcs.capability_outcome_refs,
    )
    return tuple(metrics)


def _capability_witnesses_from_run(
    run: ContentProgrammeRunEnvelope,
) -> tuple[CapabilityOutcomeWitness, ...]:
    outcomes = (*run.witnessed_outcomes, *run.command_execution.witnessed_outcomes)
    return tuple(
        CapabilityOutcomeWitness(
            capability_outcome_ref=outcome.capability_outcome_ref,
            capability_outcome_envelope_ref=_capability_outcome_envelope_ref(outcome),
            witness_state=outcome.witness_state,
            evidence_envelope_refs=outcome.evidence_envelope_refs,
            posterior_update_allowed=_run_witness_allows_update(outcome),
        )
        for outcome in outcomes
    )


def _capability_outcome_envelope_ref(outcome: WitnessedOutcomeRecord) -> str:
    if outcome.capability_outcome_ref.startswith("CapabilityOutcomeEnvelope:"):
        return outcome.capability_outcome_ref
    return f"CapabilityOutcomeEnvelope:{outcome.capability_outcome_ref}"


def _posterior_updates_from_run(
    run: ContentProgrammeRunEnvelope,
    state: ProgrammeOutcomeState,
    grounding_outputs: Sequence[GroundingOutput],
    artifact_outputs: Sequence[ArtifactOutput],
    audience_outcome: AudienceOutcome,
    revenue_proxies: Sequence[RevenueProxy],
    safety_metrics: Sequence[SafetyMetric],
) -> tuple[PosteriorUpdate, ...]:
    updates: list[PosteriorUpdate] = []
    grounding_evidence_refs = _dedupe_strs(
        ref for output in grounding_outputs for ref in (output.evaluation_id, *output.evidence_refs)
    )
    grounding_allowed = any(output.update_allowed for output in grounding_outputs)
    if grounding_outputs:
        updates.append(
            PosteriorUpdate(
                update_id=f"posterior:grounding:{run.run_id}",
                posterior_family="grounding_quality",
                target_ref="content-opportunity-model.posterior_state.grounding_yield_probability",
                source_signal="format_grounding_evaluation",
                value=1.0 if grounding_evidence_refs else 0.0,
                confidence=0.7 if grounding_allowed else 1.0,
                prior_ref=f"posterior:grounding:{run.format_id}:prior",
                evidence_refs=grounding_evidence_refs,
                update_allowed=grounding_allowed,
                blocked_reason=None
                if grounding_allowed
                else _grounding_update_blocked_reason(run, state),
            )
        )

    for artifact in artifact_outputs:
        success = artifact.state in {"linked", "emitted"}
        updates.append(
            PosteriorUpdate(
                update_id=f"posterior:artifact:{run.run_id}:{artifact.artifact_id}",
                posterior_family="artifact_conversion",
                target_ref="content-opportunity-model.posterior_state.artifact_conversion",
                source_signal="artifact_conversion",
                value=1.0 if success else 0.0,
                confidence=0.7,
                prior_ref=f"posterior:artifact:{run.format_id}:prior",
                evidence_refs=_dedupe_strs((artifact.artifact_id, *artifact.evidence_refs)),
                update_allowed=bool(artifact.evidence_refs),
                blocked_reason=None if success else "artifact_not_linked_or_emitted",
            )
        )

    rights_evidence_refs = _dedupe_strs(
        (*run.gate_refs.rights_gate_refs, *_combined_run_evidence_refs(run))
    )
    if rights_evidence_refs:
        rights_blocked = any(
            metric.metric_name == "rights_block_count" for metric in safety_metrics
        )
        updates.append(
            PosteriorUpdate(
                update_id=f"posterior:rights:{run.run_id}",
                posterior_family="rights_pass_probability",
                target_ref="content-opportunity-model.posterior_state.rights_pass_probability",
                source_signal="rights_gate",
                value=0.0 if rights_blocked else 1.0,
                confidence=0.85,
                prior_ref=f"posterior:rights:{run.format_id}:prior",
                evidence_refs=rights_evidence_refs,
                update_allowed=True,
            )
        )

    safety_evidence_refs = _dedupe_strs(
        ref for metric in safety_metrics for ref in metric.evidence_refs
    )
    if safety_metrics:
        updates.append(
            PosteriorUpdate(
                update_id=f"posterior:safety:{run.run_id}",
                posterior_family="safety_refusal_rate",
                target_ref="content-opportunity-model.posterior_state.safety_refusal_rate",
                source_signal="safety_gate",
                value=1.0,
                confidence=0.9,
                prior_ref=f"posterior:safety:{run.format_id}:prior",
                evidence_refs=safety_evidence_refs
                or _state_refs((*run.refusals, *run.corrections)),
                update_allowed=True,
            )
        )

    if audience_outcome.metrics:
        updates.append(
            PosteriorUpdate(
                update_id=f"posterior:audience:{run.run_id}",
                posterior_family="audience_response",
                target_ref="content-opportunity-model.posterior_state.audience_response",
                source_signal="audience_aggregate",
                value=_audience_response_value(audience_outcome),
                confidence=_audience_confidence(audience_outcome),
                prior_ref=f"posterior:audience:{run.format_id}:prior",
                evidence_refs=audience_outcome.evidence_refs,
                update_allowed=bool(audience_outcome.evidence_refs),
            )
        )

    if revenue_proxies:
        updates.append(
            PosteriorUpdate(
                update_id=f"posterior:revenue:{run.run_id}",
                posterior_family="revenue_support_response",
                target_ref="content-opportunity-model.posterior_state.revenue_support_response",
                source_signal="revenue_aggregate",
                value=_revenue_response_value(revenue_proxies),
                confidence=0.5,
                prior_ref=f"posterior:revenue:{run.format_id}:prior",
                evidence_refs=_dedupe_strs(
                    ref for proxy in revenue_proxies for ref in proxy.evidence_refs
                ),
                update_allowed=any(proxy.evidence_refs for proxy in revenue_proxies),
            )
        )

    return tuple(updates)


def _grounding_update_blocked_reason(
    run: ContentProgrammeRunEnvelope,
    state: ProgrammeOutcomeState,
) -> str:
    if not _score_evidence_refs(run.scores):
        return "missing_grounding_evidence_ref"
    if not _has_verified_witness(run):
        return "missing_verified_witness"
    if state not in GROUNDING_UPDATE_ELIGIBLE_STATES:
        return f"programme_state_{state}_blocks_grounding_update"
    return "grounding_update_blocked"


def _audience_response_value(outcome: AudienceOutcome) -> float:
    if not outcome.metrics:
        return 0.0
    weighted_total = sum(metric.value * max(metric.sample_size, 1) for metric in outcome.metrics)
    sample_total = sum(max(metric.sample_size, 1) for metric in outcome.metrics)
    return _clamp01(weighted_total / sample_total)


def _audience_confidence(outcome: AudienceOutcome) -> float:
    sample_total = sum(metric.sample_size for metric in outcome.metrics)
    return _clamp01(sample_total / 100)


def _revenue_response_value(proxies: Sequence[RevenueProxy]) -> float:
    if not proxies:
        return 0.0
    return _clamp01(sum(proxy.value for proxy in proxies) / len(proxies))


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _public_truth_claim_allowed(
    state: ProgrammeOutcomeState,
    gate_outcomes: Sequence[GateOutcome],
    run: ContentProgrammeRunEnvelope,
) -> bool:
    return (
        state in CLAIM_BEARING_PROGRAMME_STATES
        and _is_public_claim_mode(run.public_private_mode)
        and _has_verified_witness(run)
        and bool(run.claims)
        and all(not gate.blocks_public_claim for gate in gate_outcomes)
    )


def _default_exploration_signal(
    run: ContentProgrammeRunEnvelope,
    state: ProgrammeOutcomeState,
) -> ExplorationSignal:
    return ExplorationSignal(
        exploration_budget_ref=f"exploration:daily:{run.selected_at:%Y%m%d}",
        exploration_regret=0.16 if state in NON_CLAIM_BEARING_PROGRAMME_STATES else 0.05,
        novelty_distance=0.0,
        cooldown_effect_ref=f"cooldown:format:{run.format_id}",
        evidence_refs=(run.selected_opportunity.reward_vector_ref,),
    )


def build_feedback_fixture(
    state: ProgrammeOutcomeState,
    *,
    generated_at: datetime | None = None,
) -> ContentProgrammeFeedbackEvent:
    """Build a representative feedback event fixture for tests and contract docs."""

    now = generated_at or datetime(2026, 4, 29, tzinfo=UTC)
    run_id = f"run_feedback_{state}"
    has_evidence = state not in {"blocked", "aborted"}
    public_truth_allowed = state in {"public_run", "completed"}
    gate_state: GateState = "pass" if has_evidence else "fail"
    witness_state: WitnessState = "witness_verified" if has_evidence else "witness_unavailable"
    event_kind_by_state: dict[ProgrammeOutcomeState, FeedbackEventKind] = {
        "selected": "run_selected",
        "blocked": "run_blocked",
        "dry_run": "dry_run_completed",
        "public_run": "public_run_completed",
        "completed": "run_completed",
        "aborted": "run_aborted",
        "refused": "run_refused",
        "corrected": "run_corrected",
        "private_only": "private_only_recorded",
        "conversion_held": "conversion_held",
    }
    public_private_mode: PublicPrivateMode
    if state in {"public_run", "completed", "corrected"}:
        public_private_mode = "public_archive"
    elif state in {"dry_run", "blocked", "refused", "conversion_held"}:
        public_private_mode = "dry_run"
    else:
        public_private_mode = "private"

    posterior_updates: tuple[PosteriorUpdate, ...] = (
        PosteriorUpdate(
            update_id=f"posterior:grounding:{state}",
            posterior_family="grounding_quality",
            target_ref="content-opportunity-model.posterior_state.grounding_yield_probability",
            source_signal="format_grounding_evaluation",
            value=0.75 if has_evidence else 0.0,
            confidence=0.7 if has_evidence else 1.0,
            prior_ref=f"posterior:grounding:{state}:prior",
            evidence_refs=(f"fge:{state}",) if has_evidence else (),
            update_allowed=has_evidence,
            blocked_reason=None if has_evidence else "missing_evidence_ref",
        ),
    )
    if state in {"blocked", "refused", "corrected", "private_only", "aborted"}:
        posterior_updates = (
            *posterior_updates,
            PosteriorUpdate(
                update_id=f"posterior:safety:{state}",
                posterior_family="safety_refusal_rate",
                target_ref="content-opportunity-model.posterior_state.safety_refusal_rate",
                source_signal="safety_gate",
                value=1.0,
                confidence=1.0,
                prior_ref=f"posterior:safety:{state}:prior",
                evidence_refs=(f"safety:{state}",),
                update_allowed=True,
            ),
        )

    return ContentProgrammeFeedbackEvent(
        ledger_event_id=f"feedback:{state}",
        run_id=run_id,
        programme_id="programme_feedback_fixture",
        opportunity_decision_id=f"cod_feedback_{state}",
        format_id="evidence_audit",
        input_source_id="operator_owned_archive_segments",
        subject_cluster="feedback_fixture",
        occurred_at=now,
        event_kind=event_kind_by_state[state],
        programme_state=state,
        public_private_mode=public_private_mode,
        run_store_ref=f"run-store:{run_id}",
        selected_state_refs=(f"command:selected:{state}",),
        commanded_state_refs=(f"command:accepted:{state}",),
        gate_outcomes=(
            GateOutcome(
                gate_name="truth_gate",
                state=gate_state,
                gate_ref=f"grounding-gate:{state}",
                evidence_refs=(f"evidence:{state}",) if has_evidence else (),
                unavailable_reasons=() if has_evidence else ("missing_evidence_ref",),
                blocks_public_claim=not public_truth_allowed,
                posterior_update_allowed=has_evidence,
            ),
        ),
        grounding_outputs=(
            GroundingOutput(
                evaluation_id=f"fge:{state}",
                grounding_quality_score=0.75 if has_evidence else None,
                update_allowed=has_evidence,
                evidence_refs=(f"evidence:{state}",) if has_evidence else (),
                posterior_refs=("grounding_yield_probability",) if has_evidence else (),
            ),
        ),
        artifact_outputs=(
            ArtifactOutput(
                artifact_id=f"artifact:{state}",
                artifact_type="correction_artifact"
                if state == "corrected"
                else "refusal_artifact"
                if state == "refused"
                else "archive_card",
                state="emitted" if has_evidence else "held",
                public_event_ref=f"rvpe:{state}" if public_truth_allowed else None,
                evidence_refs=(f"artifact:{state}",) if has_evidence else (),
            ),
        ),
        audience_outcome=AudienceOutcome(
            metrics=(
                AudienceMetric(
                    metric_name="watch_time",
                    value=0.5,
                    sample_size=5,
                    aggregate_ref=f"audience:aggregate:{state}",
                    evidence_refs=(f"audience:aggregate:{state}",),
                ),
            )
            if state in {"public_run", "completed"}
            else (),
            evidence_refs=(f"audience:aggregate:{state}",)
            if state in {"public_run", "completed"}
            else (),
        ),
        revenue_proxies=(
            RevenueProxy(
                proxy_name="support_intent",
                value=0.1,
                evidence_refs=(f"support:aggregate:{state}",),
            ),
        )
        if state == "completed"
        else (),
        safety_metrics=(
            SafetyMetric(
                metric_name="refusal_count" if state == "refused" else "unsupported_claim_count",
                count=1 if state == "refused" else 0,
                evidence_refs=(f"safety:{state}",),
            ),
        ),
        witnessed_capability_outcomes=(
            CapabilityOutcomeWitness(
                capability_outcome_ref=f"coe:{state}",
                capability_outcome_envelope_ref=f"CapabilityOutcomeEnvelope:coe:{state}",
                witness_state=witness_state,
                evidence_envelope_refs=(f"ee:{state}",) if has_evidence else (),
                posterior_update_allowed=has_evidence,
            ),
        ),
        posterior_updates=posterior_updates,
        exploration=ExplorationSignal(
            exploration_budget_ref="exploration:daily:20260429",
            exploration_regret=0.1 if state in {"blocked", "aborted"} else 0.04,
            novelty_distance=0.35,
            cooldown_effect_ref=f"cooldown:format:{state}",
            evidence_refs=(f"sampler:{state}",),
        ),
        learning_policy=LearningPolicy(public_truth_claim_allowed=public_truth_allowed),
        idempotency_key=f"{run_id}:{state}",
    )
