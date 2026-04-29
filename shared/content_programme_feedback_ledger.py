"""Typed contract helpers for content programme feedback ledger events."""

from __future__ import annotations

from collections.abc import Sequence
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
    posterior_updates: tuple[PosteriorUpdate, ...] = Field(default_factory=tuple)
    exploration: ExplorationSignal
    separation_policy: SeparationPolicy = Field(default_factory=SeparationPolicy)
    learning_policy: LearningPolicy = Field(default_factory=LearningPolicy)
    append_only: Literal[True] = True
    idempotency_key: str


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
