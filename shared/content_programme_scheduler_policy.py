"""Content programme scheduler policy.

This module converts discovered content opportunities into auditable scheduling
decisions. It deliberately stops before runner execution, public-event writes,
manual calendars, request queues, supporter show control, or moderation flows.
"""

from __future__ import annotations

import enum
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from shared.content_candidate_discovery import ContentDiscoveryDecision
from shared.format_wcs_requirement_matrix import (
    FormatWCSMode,
    FormatWCSRequirementRow,
    decide_format_wcs_readiness,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEDULER_POLICY_PATH = REPO_ROOT / "config" / "content-programme-scheduler-policy.json"

type DiscoveryStatus = Literal["emitted", "held", "blocked"]
type SchedulerAction = Literal["emit_candidate", "hold_for_refresh", "block"]
type DiscoverySource = Literal["content_discovery_decision", "operator_nominated"]
type PublicPrivateMode = Literal[
    "private",
    "dry_run",
    "public_live",
    "public_archive",
    "public_monetizable",
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
type MediaReferenceDecision = Literal["allow", "downgrade", "refuse", "not_applicable"]
type MediaReferenceMode = Literal["excerpt", "link_along", "metadata_first", "none"]
type BudgetWindow = Literal["run", "daily", "weekly"]


class PromotionStage(enum.StrEnum):
    """Programme promotion ladder stages."""

    DISCOVERED = "discovered"
    SCORED = "scored"
    DRY_RUN = "dry_run"
    PRIVATE_ARCHIVE = "private_archive"
    PUBLIC_LIVE = "public_live"
    CLIPPED_REPLAYED = "clipped_replayed"
    MONETIZED = "monetized"


class ScheduleRoute(enum.StrEnum):
    """Mutually separate scheduler routes."""

    PRIVATE = "private"
    DRY_RUN = "dry_run"
    PUBLIC_LIVE = "public_live"
    PUBLIC_ARCHIVE = "public_archive"
    MONETIZED = "monetized"
    REFUSAL = "refusal"
    CORRECTION = "correction"


class RiskTier(enum.StrEnum):
    """Risk tier used for public/exploration ceilings."""

    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


PROMOTION_LADDER: tuple[PromotionStage, ...] = (
    PromotionStage.DISCOVERED,
    PromotionStage.SCORED,
    PromotionStage.DRY_RUN,
    PromotionStage.PRIVATE_ARCHIVE,
    PromotionStage.PUBLIC_LIVE,
    PromotionStage.CLIPPED_REPLAYED,
    PromotionStage.MONETIZED,
)
ALL_ROUTES: tuple[ScheduleRoute, ...] = (
    ScheduleRoute.PRIVATE,
    ScheduleRoute.DRY_RUN,
    ScheduleRoute.PUBLIC_LIVE,
    ScheduleRoute.PUBLIC_ARCHIVE,
    ScheduleRoute.MONETIZED,
    ScheduleRoute.REFUSAL,
    ScheduleRoute.CORRECTION,
)
PUBLIC_ROUTES: frozenset[ScheduleRoute] = frozenset(
    {
        ScheduleRoute.PUBLIC_LIVE,
        ScheduleRoute.PUBLIC_ARCHIVE,
        ScheduleRoute.MONETIZED,
    }
)
ROUTE_TO_STAGE: dict[ScheduleRoute, PromotionStage] = {
    ScheduleRoute.PRIVATE: PromotionStage.PRIVATE_ARCHIVE,
    ScheduleRoute.DRY_RUN: PromotionStage.DRY_RUN,
    ScheduleRoute.PUBLIC_LIVE: PromotionStage.PUBLIC_LIVE,
    ScheduleRoute.PUBLIC_ARCHIVE: PromotionStage.CLIPPED_REPLAYED,
    ScheduleRoute.MONETIZED: PromotionStage.MONETIZED,
    ScheduleRoute.REFUSAL: PromotionStage.DISCOVERED,
    ScheduleRoute.CORRECTION: PromotionStage.CLIPPED_REPLAYED,
}
STAGE_TO_ROUTE: dict[PromotionStage, ScheduleRoute] = {
    PromotionStage.DRY_RUN: ScheduleRoute.DRY_RUN,
    PromotionStage.PRIVATE_ARCHIVE: ScheduleRoute.PRIVATE,
    PromotionStage.PUBLIC_LIVE: ScheduleRoute.PUBLIC_LIVE,
    PromotionStage.CLIPPED_REPLAYED: ScheduleRoute.PUBLIC_ARCHIVE,
    PromotionStage.MONETIZED: ScheduleRoute.MONETIZED,
}
PUBLIC_MODE_TO_ROUTE: dict[PublicPrivateMode, ScheduleRoute] = {
    "private": ScheduleRoute.PRIVATE,
    "dry_run": ScheduleRoute.DRY_RUN,
    "public_live": ScheduleRoute.PUBLIC_LIVE,
    "public_archive": ScheduleRoute.PUBLIC_ARCHIVE,
    "public_monetizable": ScheduleRoute.MONETIZED,
}
ROUTE_TO_FORMAT_WCS_MODE: dict[ScheduleRoute, FormatWCSMode] = {
    ScheduleRoute.PRIVATE: "private",
    ScheduleRoute.DRY_RUN: "dry_run",
    ScheduleRoute.PUBLIC_LIVE: "public_live",
    ScheduleRoute.PUBLIC_ARCHIVE: "public_archive",
    ScheduleRoute.MONETIZED: "public_monetizable",
}
RISK_ORDER: dict[RiskTier, int] = {
    RiskTier.MINIMAL: 0,
    RiskTier.LOW: 1,
    RiskTier.MEDIUM: 2,
    RiskTier.HIGH: 3,
}


class SchedulerPolicyError(ValueError):
    """Raised when the scheduler policy packet cannot be loaded."""


class SchedulerModel(BaseModel):
    """Strict immutable base for scheduler policy records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class OperatorBoundaryPolicy(SchedulerModel):
    """Single-operator boundary: no manual calendar or community obligations."""

    single_operator_only: Literal[True] = True
    manual_calendar_allowed: Literal[False] = False
    operator_nominated_default_allowed: Literal[False] = False
    request_queue_allowed: Literal[False] = False
    supporter_controlled_show_allowed: Literal[False] = False
    community_moderation_allowed: Literal[False] = False
    personalized_supporter_treatment_allowed: Literal[False] = False


class ExplorationBudgetState(SchedulerModel):
    """Runtime exploration budget consumed by scheduler decisions."""

    budget_window: BudgetWindow = "daily"
    max_exploration_fraction: float = Field(ge=0, le=1)
    used_fraction: float = Field(ge=0, le=1)
    remaining_fraction: float = Field(ge=0, le=1)
    private_first: Literal[True] = True
    max_public_risk_tier: RiskTier = RiskTier.LOW

    @model_validator(mode="after")
    def _validate_budget_accounting(self) -> ExplorationBudgetState:
        if self.used_fraction + self.remaining_fraction > self.max_exploration_fraction + 1e-9:
            raise ValueError("exploration used + remaining cannot exceed max fraction")
        return self

    @property
    def exhausted(self) -> bool:
        """Whether no exploration budget remains."""

        return self.remaining_fraction <= 0


class CooldownPolicy(SchedulerModel):
    """Cooldown windows in seconds."""

    format_cooldown_s: int = Field(ge=0)
    source_cooldown_s: int = Field(ge=0)
    subject_cluster_cooldown_s: int = Field(ge=0)
    public_mode_cooldown_s: int = Field(ge=0)
    refusal_cooldown_s: int = Field(ge=0)


class CooldownLedger(SchedulerModel):
    """Last-selection timestamps used to enforce cooldowns."""

    format_last_selected_at: dict[str, datetime] = Field(default_factory=dict)
    source_last_selected_at: dict[str, datetime] = Field(default_factory=dict)
    subject_cluster_last_selected_at: dict[str, datetime] = Field(default_factory=dict)
    public_mode_last_selected_at: dict[str, datetime] = Field(default_factory=dict)
    refusal_last_at: dict[str, datetime] = Field(default_factory=dict)


class SchedulerRuntimeState(SchedulerModel):
    """Dynamic policy state for one scheduler evaluation."""

    exploration_budget: ExplorationBudgetState
    cooldowns: CooldownLedger = Field(default_factory=CooldownLedger)


class ContentProgrammeSchedulerPolicy(SchedulerModel):
    """Machine-readable scheduler policy packet."""

    schema_version: Literal[1]
    policy_id: Literal["content_programme_scheduler_policy"]
    schema_ref: Literal["schemas/content-programme-scheduler-policy.schema.json"]
    default_discovery_source: Literal["content_discovery_decision"]
    promotion_ladder: tuple[PromotionStage, ...]
    routes: tuple[ScheduleRoute, ...]
    public_routes: tuple[ScheduleRoute, ...]
    hard_public_gates: tuple[str, ...] = Field(min_length=1)
    operator_boundary_policy: OperatorBoundaryPolicy
    default_exploration_budget: ExplorationBudgetState
    cooldowns: CooldownPolicy
    audit_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_policy_contract(self) -> ContentProgrammeSchedulerPolicy:
        if self.promotion_ladder != PROMOTION_LADDER:
            raise ValueError("promotion ladder must match canonical scheduler ladder")
        if self.routes != ALL_ROUTES:
            raise ValueError("routes must keep public/private/refusal/correction surfaces separate")
        if set(self.public_routes) != set(PUBLIC_ROUTES):
            raise ValueError("public_routes must be public_live, public_archive, monetized")
        required_gates = {
            "no_expert_system",
            "rights",
            "provenance",
            "privacy",
            "monetization",
            "audio",
            "egress",
            "wcs_health",
            "evidence",
            "witness",
            "public_event",
        }
        missing = required_gates - set(self.hard_public_gates)
        if missing:
            raise ValueError(f"hard_public_gates missing: {sorted(missing)}")
        return self


class MediaReferenceGateView(SchedulerModel):
    """Scheduler view of rights-safe media reference evaluation."""

    decision: MediaReferenceDecision = "not_applicable"
    safe_reference_mode: MediaReferenceMode = "none"
    refused_factors: tuple[str, ...] = Field(default_factory=tuple)


class SchedulerOpportunity(SchedulerModel):
    """Minimal opportunity view consumed by the scheduler."""

    decision_id: str
    opportunity_id: str
    format_id: str
    input_source_id: str
    subject_cluster: str
    public_mode: PublicPrivateMode
    rights_state: str
    grounding_question: str
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    source_priors: dict[str, float] = Field(default_factory=dict)
    public_selectable: bool = False
    monetizable: bool = False
    discovery_status: DiscoveryStatus = "emitted"
    scheduler_action: SchedulerAction = "emit_candidate"
    discovery_blocked_reasons: tuple[str, ...] = Field(default_factory=tuple)
    discovered_from: DiscoverySource = "content_discovery_decision"
    completed_stages: tuple[PromotionStage, ...] = (
        PromotionStage.DISCOVERED,
        PromotionStage.SCORED,
    )
    risk_tier: RiskTier = RiskTier.LOW
    exploration: bool = False
    correction_required: bool = False
    provenance_complete: bool = True
    supporter_controlled: bool = False
    per_person_request: bool = False
    manual_calendar_requested: bool = False
    community_moderation_required: bool = False


class SchedulerWorldSurfaceSnapshot(SchedulerModel):
    """World-surface evidence snapshot consumed by public gate checks."""

    available_surface_ids: tuple[str, ...] = Field(default_factory=tuple)
    fresh_surface_ids: tuple[str, ...] = Field(default_factory=tuple)
    stale_surface_ids: tuple[str, ...] = Field(default_factory=tuple)
    blocked_reason_codes: tuple[str, ...] = Field(default_factory=tuple)
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    missing_evidence_refs: tuple[str, ...] = Field(default_factory=tuple)
    missing_witness_refs: tuple[str, ...] = Field(default_factory=tuple)
    unavailable_profile_reasons: tuple[str, ...] = Field(default_factory=tuple)
    health_state: WcsHealthState = "unknown"
    no_expert_system_passed: bool = False
    rights_clear: bool = False
    privacy_clear: bool = False
    provenance_complete: bool = False
    public_event_ready: bool = False
    audio_safe: bool = False
    egress_ready: bool = False
    archive_ready: bool = False
    monetization_ready: bool = False
    claim_shape_declared: bool = False
    media_reference_gate: MediaReferenceGateView = Field(default_factory=MediaReferenceGateView)


class SchedulingDecision(SchedulerModel):
    """Auditable result emitted by the scheduler policy."""

    decision_id: str
    opportunity_id: str
    requested_route: ScheduleRoute
    route: ScheduleRoute
    promotion_stage: PromotionStage
    selected: bool
    eligible: bool
    public_claim_allowed: bool
    monetization_allowed: bool
    public_route_blocked: bool
    scheduling_reasons: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    audit_refs: tuple[str, ...]
    operator_boundary_policy: OperatorBoundaryPolicy
    default_discovery_path_enforced: Literal[True] = True


def load_policy(
    path: Path = DEFAULT_SCHEDULER_POLICY_PATH,
) -> ContentProgrammeSchedulerPolicy:
    """Load and validate the scheduler policy packet."""

    try:
        return ContentProgrammeSchedulerPolicy.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
    except Exception as exc:  # noqa: BLE001
        raise SchedulerPolicyError(f"invalid content programme scheduler policy: {exc}") from exc


def scheduler_opportunity_from_discovery(
    decision: ContentDiscoveryDecision,
    *,
    completed_stages: tuple[PromotionStage, ...] = (
        PromotionStage.DISCOVERED,
        PromotionStage.SCORED,
    ),
    risk_tier: RiskTier = RiskTier.LOW,
    exploration: bool = False,
) -> SchedulerOpportunity:
    """Build the scheduler's default opportunity input from discovery output."""

    opportunity = decision.opportunity
    return SchedulerOpportunity(
        decision_id=decision.decision_id,
        opportunity_id=opportunity.opportunity_id,
        format_id=opportunity.format_id,
        input_source_id=opportunity.input_source_id,
        subject_cluster=opportunity.subject_cluster,
        public_mode=opportunity.public_mode,
        rights_state=opportunity.rights_state,
        grounding_question=opportunity.grounding_question,
        evidence_refs=opportunity.evidence_refs,
        source_priors=opportunity.source_priors,
        public_selectable=opportunity.public_selectable,
        monetizable=opportunity.monetizable,
        discovery_status=decision.status,
        scheduler_action=decision.scheduler_action,
        discovery_blocked_reasons=decision.blocked_reasons,
        completed_stages=completed_stages,
        risk_tier=risk_tier,
        exploration=exploration,
    )


def decide_schedule(
    opportunity: SchedulerOpportunity,
    world: SchedulerWorldSurfaceSnapshot,
    *,
    policy: ContentProgrammeSchedulerPolicy | None = None,
    runtime_state: SchedulerRuntimeState | None = None,
    format_row: FormatWCSRequirementRow | None = None,
    scrim_profile_result: Any | None = None,
    now: datetime | None = None,
) -> SchedulingDecision:
    """Evaluate one opportunity into a scheduler route.

    The function is pure: it emits a decision record and mutates no run store,
    calendar, platform adapter, or public surface.
    """

    resolved_policy = policy or load_policy()
    resolved_now = _utc(now)
    resolved_state = runtime_state or SchedulerRuntimeState(
        exploration_budget=resolved_policy.default_exploration_budget
    )
    requested_route = PUBLIC_MODE_TO_ROUTE[opportunity.public_mode]
    reasons: list[str] = [
        "input_source:content_discovery_decision",
        f"requested_route:{requested_route.value}",
    ]
    blocked: list[str] = []

    hard_blockers = _hard_scheduler_blockers(
        opportunity,
        resolved_policy,
        resolved_state,
        resolved_now,
    )
    if hard_blockers:
        blocked.extend(hard_blockers)
        return _decision(
            opportunity,
            resolved_policy,
            requested_route=requested_route,
            route=ScheduleRoute.REFUSAL,
            promotion_stage=PromotionStage.DISCOVERED,
            selected=False,
            reasons=(*reasons, "hard_scheduler_blocker"),
            blocked=blocked,
            world=world,
        )

    if opportunity.correction_required:
        return _decision(
            opportunity,
            resolved_policy,
            requested_route=requested_route,
            route=ScheduleRoute.CORRECTION,
            promotion_stage=PromotionStage.CLIPPED_REPLAYED,
            selected=True,
            reasons=(*reasons, "correction_required_route"),
            blocked=blocked,
            world=world,
        )

    target_route = requested_route
    if (
        opportunity.exploration
        and resolved_state.exploration_budget.private_first
        and PromotionStage.DRY_RUN not in opportunity.completed_stages
        and target_route in PUBLIC_ROUTES
    ):
        target_route = ScheduleRoute.DRY_RUN
        reasons.append("exploration_private_first_requires_dry_run")

    route, stage, ladder_reasons = _route_after_ladder(
        opportunity.completed_stages,
        target_route,
        resolved_policy,
    )
    reasons.extend(ladder_reasons)

    public_blockers: tuple[str, ...] = ()
    if route in PUBLIC_ROUTES:
        public_blockers = _public_route_blockers(
            opportunity,
            world,
            route=route,
            runtime_state=resolved_state,
            format_row=format_row,
            scrim_profile_result=scrim_profile_result,
        )
        if public_blockers:
            blocked.extend(public_blockers)
            route = _safe_fallback_route(opportunity)
            stage = ROUTE_TO_STAGE[route]
            reasons.append(f"public_route_blocked_downgraded_to:{route.value}")

    selected = route is not ScheduleRoute.REFUSAL
    return _decision(
        opportunity,
        resolved_policy,
        requested_route=requested_route,
        route=route,
        promotion_stage=stage,
        selected=selected,
        reasons=reasons,
        blocked=blocked,
        world=world,
        public_route_blocked=bool(public_blockers),
    )


def _decision(
    opportunity: SchedulerOpportunity,
    policy: ContentProgrammeSchedulerPolicy,
    *,
    requested_route: ScheduleRoute,
    route: ScheduleRoute,
    promotion_stage: PromotionStage,
    selected: bool,
    reasons: tuple[str, ...] | list[str],
    blocked: tuple[str, ...] | list[str],
    world: SchedulerWorldSurfaceSnapshot,
    public_route_blocked: bool = False,
) -> SchedulingDecision:
    public_claim_allowed = selected and route in PUBLIC_ROUTES and not public_route_blocked
    monetization_allowed = public_claim_allowed and route is ScheduleRoute.MONETIZED
    audit_refs = _unique(
        (
            *policy.audit_refs,
            *opportunity.evidence_refs,
            *world.evidence_refs,
            *world.blocked_reason_codes,
        )
    )
    return SchedulingDecision(
        decision_id=f"scheduler:{opportunity.decision_id}:{route.value}",
        opportunity_id=opportunity.opportunity_id,
        requested_route=requested_route,
        route=route,
        promotion_stage=promotion_stage,
        selected=selected,
        eligible=selected and route is not ScheduleRoute.REFUSAL,
        public_claim_allowed=public_claim_allowed,
        monetization_allowed=monetization_allowed,
        public_route_blocked=public_route_blocked,
        scheduling_reasons=_unique(tuple(reasons)),
        blocked_reasons=_unique(tuple(blocked)),
        audit_refs=audit_refs,
        operator_boundary_policy=policy.operator_boundary_policy,
    )


def _hard_scheduler_blockers(
    opportunity: SchedulerOpportunity,
    policy: ContentProgrammeSchedulerPolicy,
    runtime_state: SchedulerRuntimeState,
    now: datetime,
) -> tuple[str, ...]:
    blockers: list[str] = []
    boundary = policy.operator_boundary_policy

    if opportunity.discovered_from != policy.default_discovery_source:
        blockers.append("operator_nominated_topic_default_path_forbidden")
    if opportunity.manual_calendar_requested or boundary.manual_calendar_allowed is not False:
        blockers.append("manual_content_calendar_forbidden")
    if opportunity.supporter_controlled or boundary.supporter_controlled_show_allowed is not False:
        blockers.append("supporter_show_control_forbidden")
    if opportunity.per_person_request or boundary.request_queue_allowed is not False:
        blockers.append("operator_request_queue_forbidden")
    if (
        opportunity.community_moderation_required
        or boundary.community_moderation_allowed is not False
    ):
        blockers.append("community_moderation_obligation_forbidden")

    if (
        opportunity.discovery_status != "emitted"
        or opportunity.scheduler_action != "emit_candidate"
    ):
        blockers.append(f"discovery_status:{opportunity.discovery_status}")
        blockers.extend(opportunity.discovery_blocked_reasons)

    if PromotionStage.DISCOVERED not in opportunity.completed_stages:
        blockers.append("promotion_ladder_missing_discovered_stage")
    if PromotionStage.SCORED not in opportunity.completed_stages:
        blockers.append("promotion_ladder_missing_scored_stage")

    if opportunity.exploration and runtime_state.exploration_budget.exhausted:
        blockers.append("exploration_budget_exhausted")

    blockers.extend(_cooldown_blockers(opportunity, policy.cooldowns, runtime_state.cooldowns, now))
    return _unique(tuple(blockers))


def _cooldown_blockers(
    opportunity: SchedulerOpportunity,
    policy: CooldownPolicy,
    ledger: CooldownLedger,
    now: datetime,
) -> tuple[str, ...]:
    checks = (
        (
            ledger.format_last_selected_at.get(opportunity.format_id),
            policy.format_cooldown_s,
            "format_cooldown_active",
        ),
        (
            ledger.source_last_selected_at.get(opportunity.input_source_id),
            policy.source_cooldown_s,
            "source_cooldown_active",
        ),
        (
            ledger.subject_cluster_last_selected_at.get(opportunity.subject_cluster),
            policy.subject_cluster_cooldown_s,
            "subject_cluster_cooldown_active",
        ),
        (
            ledger.public_mode_last_selected_at.get(opportunity.public_mode),
            policy.public_mode_cooldown_s,
            "public_mode_cooldown_active",
        ),
        (
            ledger.refusal_last_at.get(opportunity.opportunity_id),
            policy.refusal_cooldown_s,
            "refusal_cooldown_active",
        ),
    )
    return tuple(
        blocker
        for last_at, window_s, blocker in checks
        if _cooldown_active(last_at, window_s=window_s, now=now)
    )


def _cooldown_active(last_at: datetime | None, *, window_s: int, now: datetime) -> bool:
    if last_at is None or window_s <= 0:
        return False
    return (_utc(now) - _utc(last_at)).total_seconds() < window_s


def _route_after_ladder(
    completed_stages: tuple[PromotionStage, ...],
    requested_route: ScheduleRoute,
    policy: ContentProgrammeSchedulerPolicy,
) -> tuple[ScheduleRoute, PromotionStage, tuple[str, ...]]:
    target_stage = ROUTE_TO_STAGE[requested_route]
    completed = set(completed_stages)
    reasons: list[str] = []

    for stage in policy.promotion_ladder:
        if stage == target_stage:
            if stage in completed:
                reasons.append(f"promotion_ladder_target_already_completed:{stage.value}")
            else:
                reasons.append(f"promotion_ladder_next_stage:{stage.value}")
            return STAGE_TO_ROUTE.get(stage, requested_route), stage, tuple(reasons)
        if stage not in completed:
            route = STAGE_TO_ROUTE.get(stage)
            if route is None:
                return ScheduleRoute.REFUSAL, stage, (f"promotion_ladder_missing:{stage.value}",)
            reasons.append(f"promotion_ladder_requires_prior_stage:{stage.value}")
            return route, stage, tuple(reasons)

    return requested_route, target_stage, ("promotion_ladder_complete",)


def _public_route_blockers(
    opportunity: SchedulerOpportunity,
    world: SchedulerWorldSurfaceSnapshot,
    *,
    route: ScheduleRoute,
    runtime_state: SchedulerRuntimeState,
    format_row: FormatWCSRequirementRow | None,
    scrim_profile_result: Any | None,
) -> tuple[str, ...]:
    blockers: list[str] = []

    if route is ScheduleRoute.MONETIZED and not opportunity.monetizable:
        blockers.append("candidate_not_monetizable")
    elif not opportunity.public_selectable:
        blockers.append("candidate_not_public_selectable")

    if opportunity.exploration and _risk_exceeds(
        opportunity.risk_tier,
        runtime_state.exploration_budget.max_public_risk_tier,
    ):
        blockers.append("exploration_public_risk_ceiling_exceeded")
    if _risk_exceeds(opportunity.risk_tier, RiskTier.LOW):
        blockers.append("public_risk_ceiling_exceeded")

    if not world.no_expert_system_passed:
        blockers.append("no_expert_system_gate_failed")
    if not world.claim_shape_declared:
        blockers.append("missing_claim_shape")
    if not _rights_state_is_public_safe(opportunity.rights_state) or not world.rights_clear:
        blockers.append("rights_gate_blocked")
    if not opportunity.provenance_complete or not world.provenance_complete:
        blockers.append("provenance_gate_blocked")
    if not world.privacy_clear:
        blockers.append("privacy_gate_blocked")
    if world.health_state in {"blocked", "unsafe", "stale", "missing", "unknown"}:
        blockers.append(f"wcs_health_{world.health_state}")
    if world.stale_surface_ids:
        blockers.append("world_surface_stale")
    if not opportunity.evidence_refs or not world.evidence_refs or world.missing_evidence_refs:
        blockers.append("missing_evidence")
    if world.missing_witness_refs:
        blockers.append("missing_witness")
    if not world.public_event_ready:
        blockers.append("public_event_missing")
    if not world.audio_safe:
        blockers.append("audio_safety_gate_blocked")
    if route is ScheduleRoute.PUBLIC_LIVE and not world.egress_ready:
        blockers.append("egress_gate_blocked")
    if route is ScheduleRoute.PUBLIC_ARCHIVE and not world.archive_ready:
        blockers.append("archive_gate_blocked")
    if route is ScheduleRoute.MONETIZED and not world.monetization_ready:
        blockers.append("monetization_gate_blocked")

    blockers.extend(world.blocked_reason_codes)
    blockers.extend(world.unavailable_profile_reasons)
    blockers.extend(_media_reference_blockers(world.media_reference_gate, route))
    blockers.extend(_format_matrix_blockers(format_row, route, world.available_surface_ids))
    blockers.extend(_scrim_profile_blockers(scrim_profile_result))
    return _unique(tuple(blockers))


def _rights_state_is_public_safe(rights_state: str) -> bool:
    return rights_state in {
        "operator_original",
        "operator_controlled",
        "public_domain",
        "cc_compatible",
        "cleared",
    }


def _media_reference_blockers(
    gate: MediaReferenceGateView,
    route: ScheduleRoute,
) -> tuple[str, ...]:
    if gate.decision == "not_applicable" or gate.decision == "allow":
        return ()
    if gate.decision == "refuse":
        return _unique(("media_reference_rights_refused", *gate.refused_factors))
    if route in {ScheduleRoute.PUBLIC_LIVE, ScheduleRoute.MONETIZED}:
        return _unique(("media_reference_downgrade_required", *gate.refused_factors))
    return ()


def _format_matrix_blockers(
    row: FormatWCSRequirementRow | None,
    route: ScheduleRoute,
    available_surface_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if row is None or route not in ROUTE_TO_FORMAT_WCS_MODE:
        return ()
    decision = decide_format_wcs_readiness(
        row,
        requested_mode=ROUTE_TO_FORMAT_WCS_MODE[route],
        available_surface_ids=available_surface_ids,
    )
    if decision.allowed:
        return ()
    return _unique((*decision.blocked_reason_codes, *decision.missing_surface_ids))


def _scrim_profile_blockers(scrim_profile_result: Any | None) -> tuple[str, ...]:
    if scrim_profile_result is None:
        return ()
    blocked = bool(getattr(scrim_profile_result, "blocked", False))
    if not blocked:
        return ()
    unavailable = tuple(getattr(scrim_profile_result, "unavailable_profile_reasons", ()))
    return _unique(("scrim_profile_unavailable", *unavailable))


def _risk_exceeds(actual: RiskTier, ceiling: RiskTier) -> bool:
    return RISK_ORDER[actual] > RISK_ORDER[ceiling]


def _safe_fallback_route(opportunity: SchedulerOpportunity) -> ScheduleRoute:
    if PromotionStage.DRY_RUN not in opportunity.completed_stages:
        return ScheduleRoute.DRY_RUN
    return ScheduleRoute.PRIVATE


def _unique(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "ALL_ROUTES",
    "DEFAULT_SCHEDULER_POLICY_PATH",
    "PROMOTION_LADDER",
    "PUBLIC_ROUTES",
    "ContentProgrammeSchedulerPolicy",
    "CooldownLedger",
    "CooldownPolicy",
    "ExplorationBudgetState",
    "MediaReferenceGateView",
    "OperatorBoundaryPolicy",
    "PromotionStage",
    "RiskTier",
    "ScheduleRoute",
    "SchedulerOpportunity",
    "SchedulerPolicyError",
    "SchedulerRuntimeState",
    "SchedulerWorldSurfaceSnapshot",
    "SchedulingDecision",
    "decide_schedule",
    "load_policy",
    "scheduler_opportunity_from_discovery",
]
