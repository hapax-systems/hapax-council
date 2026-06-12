"""Topic interestingness as systemic impingement pressure.

The engine stops at pure decisions. It can mint an existing ``Impingement`` and,
when the gates are strong enough, adapt the same observation into a
``ContentSourceObservation`` for the publication/content candidate path.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.content_candidate_discovery import (
    ContentSourceObservation,
    PublicMode,
    RightsState,
    SourceClass,
)
from shared.impingement import Impingement, ImpingementType

type TopicInterestSourceKind = Literal[
    "chronicle_event",
    "research_registry_entry",
    "cc_task",
    "pull_request",
    "review_outcome",
    "publication_log",
    "programme_boundary",
    "content_observation",
    "platform_aggregate",
    "operator_signal",
    "external_reference",
]
type TopicInterestAction = Literal[
    "ignore",
    "watch",
    "research_more",
    "frame_candidate",
    "emit_content_observation",
    "operator_question",
    "refusal_candidate",
]
type TopicInterestStatus = Literal["ignored", "watched", "emitted", "held", "blocked"]

PUBLIC_MODES: frozenset[str] = frozenset({"public_live", "public_archive", "public_monetizable"})
UNSAFE_RIGHTS_STATES: frozenset[str] = frozenset({"third_party_uncleared"})

POSITIVE_WEIGHTS: dict[str, float] = {
    "novelty": 0.15,
    "surprise": 0.12,
    "relevance": 0.16,
    "evidence_density": 0.17,
    "trajectory": 0.10,
    "public_value": 0.10,
    "research_value": 0.12,
    "actionability": 0.08,
}
PENALTY_WEIGHTS: dict[str, float] = {
    "staleness": 0.22,
    "rights_privacy_risk": 0.28,
    "claim_risk": 0.24,
    "duplicate_pressure": 0.16,
    "operator_cost": 0.10,
}


class TopicInterestModel(BaseModel):
    """Strict immutable base for topic-interest records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class TopicInterestScoreVector(TopicInterestModel):
    """Multidimensional interest signal.

    Positive dimensions express why the observation may matter. Penalty
    dimensions express why the signal should be downgraded, held, or blocked.
    """

    novelty: float = Field(ge=0.0, le=1.0)
    surprise: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    evidence_density: float = Field(ge=0.0, le=1.0)
    trajectory: float = Field(ge=0.0, le=1.0)
    public_value: float = Field(ge=0.0, le=1.0)
    research_value: float = Field(ge=0.0, le=1.0)
    actionability: float = Field(ge=0.0, le=1.0)
    staleness: float = Field(default=0.0, ge=0.0, le=1.0)
    rights_privacy_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    claim_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_pressure: float = Field(default=0.0, ge=0.0, le=1.0)
    operator_cost: float = Field(default=0.0, ge=0.0, le=1.0)

    def positive_score(self) -> float:
        return sum(getattr(self, key) * weight for key, weight in POSITIVE_WEIGHTS.items())

    def penalty_score(self) -> float:
        return sum(getattr(self, key) * weight for key, weight in PENALTY_WEIGHTS.items())

    def total_score(self) -> float:
        return _clamp(self.positive_score() - (0.55 * self.penalty_score()))


class TopicInterestPolicy(TopicInterestModel):
    """Thresholds for v0 routing.

    Thresholds are deliberately conservative: under-evidenced novelty may
    recruit research, but content-candidate emission needs evidence, freshness,
    low risk, and actionability.
    """

    schema_version: Literal[1] = 1
    watch_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    research_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    frame_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    content_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    operator_question_threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    min_relevance_for_content: float = Field(default=0.45, ge=0.0, le=1.0)
    min_evidence_density_for_content: float = Field(default=0.65, ge=0.0, le=1.0)
    min_actionability_for_content: float = Field(default=0.55, ge=0.0, le=1.0)
    max_claim_risk_for_content: float = Field(default=0.45, ge=0.0, le=1.0)
    max_rights_privacy_risk_for_content: float = Field(default=0.40, ge=0.0, le=1.0)
    max_duplicate_pressure_for_content: float = Field(default=0.55, ge=0.0, le=1.0)
    max_staleness_for_content: float = Field(default=0.30, ge=0.0, le=1.0)
    suppress_duplicate_pressure: float = Field(default=0.85, ge=0.0, le=1.0)
    suppress_staleness: float = Field(default=0.90, ge=0.0, le=1.0)
    duplicate_count_saturation: int = Field(default=6, gt=0)


class TopicInterestObservation(TopicInterestModel):
    """One structured observation from any local or external aperture."""

    observation_id: str
    source_kind: TopicInterestSourceKind
    source_id: str
    subject: str
    subject_cluster: str
    observed_at: datetime
    retrieved_at: datetime | None = None
    freshness_ttl_s: int | None = Field(default=None, ge=0)
    format_id: str = "research_note"
    source_class: SourceClass = "local_state"
    public_mode: PublicMode = "dry_run"
    rights_state: RightsState = "unknown"
    rights_hints: tuple[str, ...] = ()
    substrate_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = ()
    source_priors: dict[str, float] = Field(default_factory=dict)
    grounding_question: str
    signals: TopicInterestScoreVector
    programme_relevant: bool = True
    publication_relevant: bool = True
    requires_operator_authority: bool = False
    recent_duplicate_count: int = Field(default=0, ge=0)
    quota_available: bool = True
    current_event_claim: bool = False
    sensitive_event: bool = False
    trend_current_event: bool = False
    trend_used_as_truth: bool = False
    trend_decay_score: float | None = Field(default=None, ge=0.0, le=1.0)
    source_bias_score: float | None = Field(default=None, ge=0.0, le=1.0)
    primary_source_count: int = Field(default=0, ge=0)
    official_source_count: int = Field(default=0, ge=0)
    corroborating_source_count: int = Field(default=0, ge=0)
    recency_label_present: bool = False
    title_uncertainty_present: bool = False
    description_uncertainty_present: bool = False
    edsa_context_present: bool = False
    trace_id: str | None = None
    parent_impingement_id: str | None = None

    def source_age_s(self, now: datetime) -> float:
        return max(0.0, (now - self.retrieved_at_utc()).total_seconds())

    def retrieved_at_utc(self) -> datetime:
        return _utc(self.retrieved_at or self.observed_at)

    def observed_at_utc(self) -> datetime:
        return _utc(self.observed_at)


class TopicInterestDecision(TopicInterestModel):
    """Auditable routing decision for one topic-interest observation."""

    decision_id: str
    decided_at: datetime
    producer: Literal["topic_interest_engine"] = "topic_interest_engine"
    observation_id: str
    source_kind: TopicInterestSourceKind
    action: TopicInterestAction
    status: TopicInterestStatus
    score: float = Field(ge=0.0, le=1.0)
    score_vector: TopicInterestScoreVector
    blocked_reasons: tuple[str, ...] = ()
    downgrade_reasons: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()
    impingement: Impingement | None = None
    content_observation: ContentSourceObservation | None = None


def decide_topic_interest(
    observation: TopicInterestObservation,
    *,
    now: datetime | None = None,
    policy: TopicInterestPolicy | None = None,
) -> TopicInterestDecision:
    """Convert one structured observation into gated systemic pressure."""

    resolved_now = _utc(now)
    resolved_policy = policy or TopicInterestPolicy()
    effective_signals = _effective_score_vector(
        observation, now=resolved_now, policy=resolved_policy
    )
    score = effective_signals.total_score()
    blocked, downgraded = _gating_reasons(observation, effective_signals, resolved_now)

    action = _select_action(
        observation,
        effective_signals,
        score=score,
        policy=resolved_policy,
        blocked_reasons=blocked,
    )
    content_observation = None
    if action == "emit_content_observation":
        content_observation, content_downgrades = _content_observation(
            observation,
            score_vector=effective_signals,
            score=score,
            now=resolved_now,
        )
        downgraded.extend(content_downgrades)

    impingement = _impingement(
        observation,
        action=action,
        score=score,
        score_vector=effective_signals,
        blocked_reasons=blocked,
        downgrade_reasons=downgraded,
        content_observation=content_observation,
        now=resolved_now,
    )
    return TopicInterestDecision(
        decision_id=f"tie_{observation.observation_id}",
        decided_at=resolved_now,
        observation_id=observation.observation_id,
        source_kind=observation.source_kind,
        action=action,
        status=_status(action, blocked_reasons=blocked, impingement=impingement),
        score=score,
        score_vector=effective_signals,
        blocked_reasons=_unique(tuple(blocked)),
        downgrade_reasons=_unique(tuple(downgraded)),
        audit_refs=(
            "docs/legibility/topic-interest-impingement-engine-v0.md",
            "schemas/content-opportunity-model.schema.json",
            "shared/impingement.py",
            "shared/content_candidate_discovery.py",
        ),
        impingement=impingement,
        content_observation=content_observation,
    )


def decide_topic_interests(
    observations: list[TopicInterestObservation],
    *,
    now: datetime | None = None,
    policy: TopicInterestPolicy | None = None,
) -> list[TopicInterestDecision]:
    """Batch helper for deterministic callers."""

    resolved_now = _utc(now)
    resolved_policy = policy or TopicInterestPolicy()
    return [
        decide_topic_interest(observation, now=resolved_now, policy=resolved_policy)
        for observation in observations
    ]


def _select_action(
    observation: TopicInterestObservation,
    score_vector: TopicInterestScoreVector,
    *,
    score: float,
    policy: TopicInterestPolicy,
    blocked_reasons: list[str],
) -> TopicInterestAction:
    if (
        score_vector.duplicate_pressure >= policy.suppress_duplicate_pressure
        or score_vector.staleness >= policy.suppress_staleness
    ):
        return "watch" if score >= policy.watch_threshold else "ignore"
    if score < policy.watch_threshold:
        return "ignore"
    if observation.requires_operator_authority and score >= policy.operator_question_threshold:
        return "operator_question"
    if score_vector.claim_risk >= 0.80 and score_vector.evidence_density >= 0.40:
        return "refusal_candidate"
    if _content_eligible(observation, score_vector, score=score, policy=policy):
        return "emit_content_observation"
    if score >= policy.frame_threshold and not blocked_reasons:
        return "frame_candidate"
    if score >= policy.research_threshold:
        return "research_more"
    return "watch"


def _content_eligible(
    observation: TopicInterestObservation,
    score_vector: TopicInterestScoreVector,
    *,
    score: float,
    policy: TopicInterestPolicy,
) -> bool:
    if not observation.publication_relevant:
        return False
    if score < policy.content_threshold:
        return False
    if not observation.evidence_refs or not observation.provenance_refs:
        return False
    if observation.freshness_ttl_s is None:
        return False
    if observation.requires_operator_authority:
        return False
    if observation.rights_state in UNSAFE_RIGHTS_STATES:
        return False
    if observation.trend_used_as_truth:
        return False
    checks = (
        score_vector.relevance >= policy.min_relevance_for_content,
        score_vector.evidence_density >= policy.min_evidence_density_for_content,
        score_vector.actionability >= policy.min_actionability_for_content,
        score_vector.claim_risk <= policy.max_claim_risk_for_content,
        score_vector.rights_privacy_risk <= policy.max_rights_privacy_risk_for_content,
        score_vector.duplicate_pressure <= policy.max_duplicate_pressure_for_content,
        score_vector.staleness <= policy.max_staleness_for_content,
    )
    return all(checks)


def _content_observation(
    observation: TopicInterestObservation,
    *,
    score_vector: TopicInterestScoreVector,
    score: float,
    now: datetime,
) -> tuple[ContentSourceObservation, list[str]]:
    public_mode = observation.public_mode
    downgrades: list[str] = []
    public_risky = (
        score_vector.rights_privacy_risk > 0.20
        or score_vector.claim_risk > 0.20
        or observation.current_event_claim
        or observation.trend_current_event
        or observation.rights_state == "unknown"
    )
    if public_mode in PUBLIC_MODES and public_risky:
        public_mode = "dry_run"
        downgrades.append("public_mode_downgraded_to_dry_run")

    source_priors = {
        **_finite_source_priors(observation.source_priors),
        "topic_interest_score": round(score, 6),
        "topic_interest_novelty": round(score_vector.novelty, 6),
        "topic_interest_surprise": round(score_vector.surprise, 6),
        "topic_interest_relevance": round(score_vector.relevance, 6),
        "topic_interest_evidence_density": round(score_vector.evidence_density, 6),
        "topic_interest_actionability": round(score_vector.actionability, 6),
    }
    return (
        ContentSourceObservation(
            observation_id=f"tie_{observation.observation_id}",
            source_class=observation.source_class,
            source_id=observation.source_id,
            format_id=observation.format_id,
            subject=observation.subject,
            subject_cluster=observation.subject_cluster,
            retrieved_at=observation.retrieved_at_utc(),
            published_at=observation.observed_at_utc(),
            freshness_ttl_s=observation.freshness_ttl_s,
            public_mode=public_mode,  # type: ignore[arg-type]
            rights_state=observation.rights_state,
            rights_hints=_unique(observation.rights_hints),
            substrate_refs=_unique(observation.substrate_refs),
            evidence_refs=_unique(observation.evidence_refs),
            provenance_refs=_unique(observation.provenance_refs),
            source_priors=source_priors,
            grounding_question=observation.grounding_question,
            quota_available=observation.quota_available,
            provenance_complete=True,
            current_event_claim=observation.current_event_claim or observation.trend_current_event,
            sensitive_event=observation.sensitive_event,
            trend_used_as_truth=observation.trend_used_as_truth,
            trend_decay_score=observation.trend_decay_score,
            source_bias_score=observation.source_bias_score,
            primary_source_count=observation.primary_source_count,
            official_source_count=observation.official_source_count,
            corroborating_source_count=observation.corroborating_source_count,
            recency_label_present=observation.recency_label_present,
            title_uncertainty_present=observation.title_uncertainty_present,
            description_uncertainty_present=observation.description_uncertainty_present,
            edsa_context_present=observation.edsa_context_present,
        ),
        downgrades,
    )


def _impingement(
    observation: TopicInterestObservation,
    *,
    action: TopicInterestAction,
    score: float,
    score_vector: TopicInterestScoreVector,
    blocked_reasons: list[str],
    downgrade_reasons: list[str],
    content_observation: ContentSourceObservation | None,
    now: datetime,
) -> Impingement | None:
    if action in {"ignore", "watch"}:
        return None
    programme_allowed = observation.programme_relevant and action in {
        "research_more",
        "frame_candidate",
        "emit_content_observation",
        "refusal_candidate",
    }
    return Impingement(
        timestamp=now.timestamp(),
        source="topic_interest_engine",
        type=_impingement_type(action, score_vector),
        strength=score,
        content={
            "metric": "topic_interest",
            "topic_interest_version": "v0",
            "subject": observation.subject,
            "subject_cluster": observation.subject_cluster,
            "content_summary": observation.subject,
            "action_tendency": action,
            "grounding_question": observation.grounding_question,
            "source_kind": observation.source_kind,
            "source_id": observation.source_id,
            "format_id": observation.format_id,
            "score": round(score, 6),
            "score_vector": _rounded_score_vector(score_vector),
            "evidence_refs": list(observation.evidence_refs),
            "provenance_refs": list(observation.provenance_refs),
            "substrate_refs": list(observation.substrate_refs),
            "blocked_reasons": _unique(tuple(blocked_reasons)),
            "downgrade_reasons": _unique(tuple(downgrade_reasons)),
            "publication_candidate_allowed": content_observation is not None,
            "programme_impingement_allowed": programme_allowed,
            "learning_policy": "feedback_updates_topic_interest_priors_after_downstream_outcome",
            "inhibition_policy": "duplicate_and_staleness_pressure_suppress_repeated_interrupts",
            "public_claim_evidence_ref": content_observation.observation_id
            if content_observation is not None
            else "not_public_claim",
            "trajectory": f"{score_vector.trajectory:.3f}",
            "concerns": list(_unique(tuple(blocked_reasons + downgrade_reasons))),
        },
        context={
            "public_mode": observation.public_mode,
            "rights_state": observation.rights_state,
            "current_event_claim": observation.current_event_claim,
            "trend_current_event": observation.trend_current_event,
        },
        parent_id=observation.parent_impingement_id,
        trace_id=observation.trace_id,
        intent_family="topic.interest",
    )


def _impingement_type(
    action: TopicInterestAction,
    score_vector: TopicInterestScoreVector,
) -> ImpingementType:
    if action == "research_more" and (
        score_vector.novelty >= 0.60 or score_vector.surprise >= 0.60
    ):
        return ImpingementType.CURIOSITY
    if action == "frame_candidate":
        return ImpingementType.EXPLORATION_OPPORTUNITY
    return ImpingementType.SALIENCE_INTEGRATION


def _status(
    action: TopicInterestAction,
    *,
    blocked_reasons: list[str],
    impingement: Impingement | None,
) -> TopicInterestStatus:
    if action == "ignore":
        return "ignored"
    if action == "watch":
        return "watched"
    if action == "emit_content_observation":
        return "emitted"
    if blocked_reasons:
        return "held" if impingement is not None else "blocked"
    return "emitted"


def _gating_reasons(
    observation: TopicInterestObservation,
    score_vector: TopicInterestScoreVector,
    now: datetime,
) -> tuple[list[str], list[str]]:
    blocked: list[str] = []
    downgraded: list[str] = []
    if not observation.evidence_refs:
        blocked.append("evidence_refs_missing")
    if not observation.provenance_refs:
        blocked.append("provenance_refs_missing")
    if observation.freshness_ttl_s is None:
        blocked.append("freshness_ttl_missing")
    elif observation.source_age_s(now) > observation.freshness_ttl_s:
        blocked.append("source_refresh_required")
    if observation.rights_state in UNSAFE_RIGHTS_STATES:
        blocked.append("rights_state_uncleared")
    if observation.trend_used_as_truth:
        blocked.append("trend_used_as_truth_forbidden")
    if score_vector.duplicate_pressure >= 0.55:
        downgraded.append("duplicate_pressure_present")
    if score_vector.staleness >= 0.30:
        downgraded.append("staleness_present")
    if score_vector.claim_risk >= 0.45:
        downgraded.append("claim_risk_present")
    if score_vector.rights_privacy_risk >= 0.40:
        downgraded.append("rights_privacy_risk_present")
    return blocked, downgraded


def _effective_score_vector(
    observation: TopicInterestObservation,
    *,
    now: datetime,
    policy: TopicInterestPolicy,
) -> TopicInterestScoreVector:
    staleness = observation.signals.staleness
    if observation.freshness_ttl_s is not None and observation.freshness_ttl_s > 0:
        staleness = max(
            staleness,
            _clamp(observation.source_age_s(now) / observation.freshness_ttl_s),
        )
    duplicate_pressure = max(
        observation.signals.duplicate_pressure,
        _clamp(observation.recent_duplicate_count / policy.duplicate_count_saturation),
    )
    return observation.signals.model_copy(
        update={
            "staleness": staleness,
            "duplicate_pressure": duplicate_pressure,
        }
    )


def _rounded_score_vector(score_vector: TopicInterestScoreVector) -> dict[str, float]:
    return {key: round(float(value), 6) for key, value in score_vector.model_dump().items()}


def _finite_source_priors(values: dict[str, float]) -> dict[str, float]:
    return {
        key: float(value)
        for key, value in values.items()
        if isinstance(value, int | float) and math.isfinite(float(value))
    }


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


__all__ = [
    "TopicInterestDecision",
    "TopicInterestObservation",
    "TopicInterestPolicy",
    "TopicInterestScoreVector",
    "decide_topic_interest",
    "decide_topic_interests",
]
