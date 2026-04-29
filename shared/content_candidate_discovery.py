"""Content opportunity candidate discovery contract.

This module deliberately stops at candidate emission. Scheduling, programme
execution, and public fanout consume these records later through separate gates.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.trend_current_event_gate import (
    GateAction,
    TrendCurrentEventCandidate,
    TrendCurrentEventGateResult,
    evaluate_candidate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = REPO_ROOT / "config" / "content-candidate-discovery-daemon.json"

type SourceClass = Literal[
    "local_state",
    "owned_media",
    "platform_native_state",
    "trend_sources",
    "curated_watchlists",
    "public_web_references",
    "ambient_aggregate_audience",
    "internal_anomalies",
]
type PublicMode = Literal[
    "private",
    "dry_run",
    "public_live",
    "public_archive",
    "public_monetizable",
]
type RightsState = Literal[
    "operator_original",
    "operator_controlled",
    "public_domain",
    "cc_compatible",
    "third_party_attributed",
    "third_party_uncleared",
    "platform_embedded",
    "unknown",
]
type DiscoveryStatus = Literal["emitted", "held", "blocked"]
type SchedulerAction = Literal["emit_candidate", "hold_for_refresh", "block"]
type GateState = Literal["pass", "fail", "unknown", "not_applicable"]

PUBLIC_MODES: frozenset[PublicMode] = frozenset(
    {"public_live", "public_archive", "public_monetizable"}
)
DEFAULT_SOURCE_CLASS_MODES: dict[SourceClass, tuple[PublicMode, ...]] = {
    "local_state": ("private", "dry_run", "public_archive"),
    "owned_media": ("private", "dry_run", "public_live", "public_archive", "public_monetizable"),
    "platform_native_state": ("private", "dry_run", "public_archive"),
    "trend_sources": ("private", "dry_run", "public_archive"),
    "curated_watchlists": ("private", "dry_run", "public_archive"),
    "public_web_references": ("private", "dry_run", "public_archive"),
    "ambient_aggregate_audience": ("private", "dry_run"),
    "internal_anomalies": ("private", "dry_run"),
}


class DiscoveryModel(BaseModel):
    """Strict immutable base for discovery records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class DiscoveryPaths(DiscoveryModel):
    source_observations_jsonl: str
    candidate_jsonl: str
    audit_jsonl: str
    health_json: str


class DiscoveryCadence(DiscoveryModel):
    mode: Literal["systemd_timer"]
    interval_seconds: int = Field(gt=0)
    idle_update_seconds: int = Field(gt=0)


class DiscoveryGlobalPolicy(DiscoveryModel):
    single_operator_only: Literal[True] = True
    schedules_programmes_directly: Literal[False] = False
    creates_supporter_request_queue: Literal[False] = False
    trend_as_truth_allowed: Literal[False] = False
    missing_freshness_blocks_public_claim: Literal[True] = True
    private_dry_run_default: Literal[True] = True


class DiscoveryPolicy(DiscoveryModel):
    schema_version: Literal[1]
    daemon_id: str
    enabled: Literal[True]
    declared_at: datetime
    producer: str
    cadence: DiscoveryCadence
    paths: DiscoveryPaths
    global_policy: DiscoveryGlobalPolicy
    source_class_modes: dict[SourceClass, tuple[PublicMode, ...]]
    hard_block_reasons: tuple[str, ...]
    downstream_contract: dict[str, Any]


class TimeWindow(DiscoveryModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    freshness_ttl_s: int | None = Field(default=None, ge=0)


class ContentSourceObservation(DiscoveryModel):
    observation_id: str
    source_class: SourceClass
    source_id: str
    format_id: str
    subject: str
    subject_cluster: str
    retrieved_at: datetime
    published_at: datetime | None = None
    freshness_ttl_s: int | None = Field(default=None, ge=0)
    public_mode: PublicMode = "dry_run"
    rights_state: RightsState = "unknown"
    rights_hints: tuple[str, ...] = ()
    substrate_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    provenance_refs: tuple[str, ...] = ()
    source_priors: dict[str, float] = Field(default_factory=dict)
    grounding_question: str
    quota_available: bool = True
    provenance_complete: bool = True
    supporter_controlled: bool = False
    per_person_request: bool = False
    current_event_claim: bool = False
    sensitive_event: bool = False
    trend_used_as_truth: bool = False
    trend_decay_score: float | None = None
    source_bias_score: float | None = None
    primary_source_count: int = Field(default=0, ge=0)
    official_source_count: int = Field(default=0, ge=0)
    corroborating_source_count: int = Field(default=0, ge=0)
    recency_label_present: bool = False
    title_uncertainty_present: bool = False
    description_uncertainty_present: bool = False
    edsa_context_present: bool = False

    def source_age_s(self, now: datetime) -> float:
        return max(0.0, (now - self.retrieved_at).total_seconds())

    def event_age_s(self, now: datetime) -> float | None:
        if self.published_at is None:
            return None
        return max(0.0, (now - self.published_at).total_seconds())


class CandidateGate(DiscoveryModel):
    state: GateState
    gate_ref: str | None = None
    blockers: tuple[str, ...] = ()
    unavailable_reasons: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()


class ContentOpportunityCandidate(DiscoveryModel):
    opportunity_id: str
    format_id: str
    input_source_id: str
    subject: str
    subject_cluster: str
    time_window: TimeWindow
    substrate_refs: tuple[str, ...]
    public_mode: PublicMode
    rights_state: RightsState
    grounding_question: str
    evidence_refs: tuple[str, ...]
    source_priors: dict[str, float]
    rights_hints: tuple[str, ...]
    trend_decay_score: float | None = None
    source_bias_score: float | None = None
    public_selectable: bool
    monetizable: bool


class ContentDiscoveryDecision(DiscoveryModel):
    decision_id: str
    discovered_at: datetime
    producer: Literal["content_candidate_discovery_daemon"] = "content_candidate_discovery_daemon"
    status: DiscoveryStatus
    scheduler_action: SchedulerAction
    scheduled_show_created: Literal[False] = False
    observation_id: str
    source_class: SourceClass
    opportunity: ContentOpportunityCandidate
    gates: dict[str, CandidateGate]
    blocked_reasons: tuple[str, ...]
    audit_refs: tuple[str, ...]


def load_policy(path: Path = DEFAULT_POLICY_PATH) -> DiscoveryPolicy:
    """Load and validate the daemon policy config."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return DiscoveryPolicy.model_validate(payload)


def discover_candidates(
    observations: list[ContentSourceObservation],
    *,
    now: datetime | None = None,
    policy: DiscoveryPolicy | None = None,
) -> list[ContentDiscoveryDecision]:
    """Convert source observations into auditable content opportunity candidates."""

    now = _utc(now)
    policy = policy or load_policy()
    return [_discover_one(observation, now=now, policy=policy) for observation in observations]


def _discover_one(
    observation: ContentSourceObservation,
    *,
    now: datetime,
    policy: DiscoveryPolicy,
) -> ContentDiscoveryDecision:
    blocked: list[str] = []
    gates: dict[str, CandidateGate] = {}
    public_mode = observation.public_mode
    public_selectable = public_mode in PUBLIC_MODES
    monetizable = public_mode == "public_monetizable"
    status: DiscoveryStatus = "emitted"
    scheduler_action: SchedulerAction = "emit_candidate"

    if observation.supporter_controlled:
        blocked.append("supporter_controlled_programming_forbidden")
    if observation.per_person_request:
        blocked.append("per_person_request_queue_forbidden")
    if blocked:
        status = "blocked"
        scheduler_action = "block"
        public_selectable = False
        monetizable = False

    allowed_modes = policy.source_class_modes.get(
        observation.source_class,
        DEFAULT_SOURCE_CLASS_MODES[observation.source_class],
    )
    if public_mode not in allowed_modes:
        blocked.append("source_class_public_mode_not_allowed")
        public_mode = "dry_run"
        public_selectable = False
        monetizable = False

    freshness_gate = _freshness_gate(observation, now)
    gates["freshness"] = freshness_gate
    if freshness_gate.state == "fail":
        blocked.extend(freshness_gate.blockers)
        if status != "blocked":
            status = "held"
            scheduler_action = "hold_for_refresh"
        public_selectable = False
        monetizable = False

    quota_gate = _boolean_gate(
        observation.quota_available,
        gate_ref="quota_rate_limit",
        blocker="quota_or_rate_limit_unavailable",
        evidence_refs=("source_registry:quota_rate_limits",),
    )
    gates["quota"] = quota_gate
    if quota_gate.state == "fail":
        blocked.extend(quota_gate.blockers)
        if status != "blocked":
            status = "held"
            scheduler_action = "hold_for_refresh"
        public_selectable = False
        monetizable = False

    provenance_gate = _boolean_gate(
        observation.provenance_complete,
        gate_ref="source_provenance",
        blocker="source_provenance_incomplete",
        evidence_refs=observation.provenance_refs,
    )
    gates["provenance"] = provenance_gate
    if provenance_gate.state == "fail":
        blocked.extend(provenance_gate.blockers)
        if status != "blocked":
            status = "held"
            scheduler_action = "hold_for_refresh"
        public_selectable = False
        monetizable = False

    trend_result = _trend_gate_result(observation, now=now)
    if trend_result is not None:
        gates["trend_current_event"] = CandidateGate(
            state="pass" if trend_result.action is GateAction.ALLOW_PUBLIC_CLAIM else "fail",
            gate_ref="trend_current_event_constraint_gate_v1",
            blockers=trend_result.blockers,
            unavailable_reasons=tuple(infraction.value for infraction in trend_result.infractions),
            evidence_refs=("config/trend-current-event-constraint-gate.json",),
        )
        if trend_result.action is GateAction.BLOCK_PUBLIC_CLAIM:
            status = "held" if status != "blocked" else status
            scheduler_action = (
                "hold_for_refresh" if scheduler_action != "block" else scheduler_action
            )
        if trend_result.action is not GateAction.ALLOW_PUBLIC_CLAIM:
            blocked.extend(trend_result.blockers)
            public_mode = "dry_run"
        public_selectable = public_selectable and trend_result.public_claim_allowed
        monetizable = monetizable and trend_result.monetization_allowed
    else:
        gates["trend_current_event"] = CandidateGate(state="not_applicable")

    if status == "emitted" and public_mode in PUBLIC_MODES and not public_selectable:
        public_mode = "dry_run"

    blocked_reasons = _unique(blocked)
    opportunity = ContentOpportunityCandidate(
        opportunity_id=f"opp_{observation.observation_id}",
        format_id=observation.format_id,
        input_source_id=observation.source_id,
        subject=observation.subject,
        subject_cluster=observation.subject_cluster,
        time_window=TimeWindow(
            starts_at=observation.published_at,
            ends_at=None,
            freshness_ttl_s=observation.freshness_ttl_s,
        ),
        substrate_refs=_unique(observation.substrate_refs),
        public_mode=public_mode,
        rights_state=observation.rights_state,
        grounding_question=observation.grounding_question,
        evidence_refs=_unique(observation.evidence_refs),
        source_priors=observation.source_priors,
        rights_hints=_unique(observation.rights_hints),
        trend_decay_score=observation.trend_decay_score,
        source_bias_score=observation.source_bias_score,
        public_selectable=public_selectable,
        monetizable=monetizable,
    )
    return ContentDiscoveryDecision(
        decision_id=f"cdd_{observation.observation_id}",
        discovered_at=now,
        status=status,
        scheduler_action=scheduler_action,
        observation_id=observation.observation_id,
        source_class=observation.source_class,
        opportunity=opportunity,
        gates=gates,
        blocked_reasons=blocked_reasons,
        audit_refs=_unique(
            (
                "schemas/content-opportunity-model.schema.json",
                "schemas/content-opportunity-input-source-registry.schema.json",
                "schemas/trend-current-event-constraint-gate.schema.json",
            )
        ),
    )


def _freshness_gate(observation: ContentSourceObservation, now: datetime) -> CandidateGate:
    if observation.freshness_ttl_s is None:
        return CandidateGate(
            state="fail",
            gate_ref="source_freshness",
            blockers=("source_freshness_ttl_missing",),
            unavailable_reasons=("missing_freshness",),
            evidence_refs=observation.evidence_refs,
        )
    if observation.source_age_s(now) > observation.freshness_ttl_s:
        return CandidateGate(
            state="fail",
            gate_ref="source_freshness",
            blockers=("source_refresh_required",),
            unavailable_reasons=("stale_source",),
            evidence_refs=observation.evidence_refs,
        )
    return CandidateGate(
        state="pass",
        gate_ref="source_freshness",
        evidence_refs=observation.evidence_refs,
    )


def _boolean_gate(
    value: bool,
    *,
    gate_ref: str,
    blocker: str,
    evidence_refs: tuple[str, ...],
) -> CandidateGate:
    if value:
        return CandidateGate(state="pass", gate_ref=gate_ref, evidence_refs=evidence_refs)
    return CandidateGate(
        state="fail",
        gate_ref=gate_ref,
        blockers=(blocker,),
        unavailable_reasons=(blocker,),
        evidence_refs=evidence_refs,
    )


def _trend_gate_result(
    observation: ContentSourceObservation,
    *,
    now: datetime,
) -> TrendCurrentEventGateResult | None:
    applies = observation.source_class in {"trend_sources", "public_web_references"}
    if not applies and not observation.current_event_claim:
        return None
    return evaluate_candidate(
        TrendCurrentEventCandidate(
            candidate_id=observation.observation_id,
            claim_type="current_event_claim"
            if observation.current_event_claim
            else "trend_candidate",
            proposed_format=observation.format_id,
            public_mode=observation.public_mode,
            source_age_s=observation.source_age_s(now),
            source_ttl_s=float(observation.freshness_ttl_s)
            if observation.freshness_ttl_s is not None
            else None,
            event_age_s=observation.event_age_s(now),
            primary_source_count=observation.primary_source_count,
            official_source_count=observation.official_source_count,
            corroborating_source_count=observation.corroborating_source_count,
            recency_label_present=observation.recency_label_present,
            title_uncertainty_present=observation.title_uncertainty_present,
            description_uncertainty_present=observation.description_uncertainty_present,
            sensitivity_categories=("sensitive",) if observation.sensitive_event else (),
            edsa_context_present=observation.edsa_context_present,
            monetized=observation.public_mode == "public_monetizable",
            trend_used_as_truth=observation.trend_used_as_truth,
            trend_decay_score=observation.trend_decay_score,
            source_bias_score=observation.source_bias_score,
        )
    )


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


__all__ = [
    "ContentDiscoveryDecision",
    "ContentOpportunityCandidate",
    "ContentSourceObservation",
    "DiscoveryPolicy",
    "discover_candidates",
    "load_policy",
]
