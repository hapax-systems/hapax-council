"""Inert quota and spend ledger models for capacity routing.

This module validates local ledger fixtures and computes fail-closed paid/API
route eligibility. It does not call providers, read credentials, alter billing,
dispatch work, or mutate runtime state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

REPO_ROOT = Path(__file__).resolve().parents[1]
QUOTA_SPEND_LEDGER_FIXTURES = REPO_ROOT / "config" / "quota-spend-ledger-fixtures.json"

PAID_CAPACITY_POOLS = frozenset({"api_paid_spend", "bootstrap_budget", "incident_override"})


class QuotaSpendLedgerError(ValueError):
    """Raised when quota/spend ledger data cannot be trusted."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapacityPool(StrEnum):
    SUBSCRIPTION_QUOTA = "subscription_quota"
    LOCAL_COMPUTE = "local_compute"
    API_PAID_SPEND = "api_paid_spend"
    BOOTSTRAP_BUDGET = "bootstrap_budget"
    STEADY_STATE_TARGET = "steady_state_target"
    INCIDENT_OVERRIDE = "incident_override"


class AuthSurface(StrEnum):
    SUBSCRIPTION = "subscription"
    API_KEY = "api_key"
    VERTEX = "vertex"
    LOCAL = "local"
    UNKNOWN = "unknown"


class BudgetApproval(StrEnum):
    OPERATOR = "operator"
    LATER_AUTHORITY_PACKET = "later_authority_packet"


class BudgetLifecycleState(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    REVOKED = "revoked"


class SpendReason(StrEnum):
    QUOTA_EXHAUSTION = "quota_exhaustion"
    BURST_CAPACITY = "burst_capacity"
    BOOTSTRAP_EQUILIBRIUM = "bootstrap_equilibrium"
    RETRY_AFTER = "retry_after"
    QUALITY_ESCALATION = "quality_escalation"


class SpendReconciliationState(StrEnum):
    PENDING = "pending"
    RECONCILED = "reconciled"
    FROZEN_REFUSED = "frozen_refused"


class SupportArtifactAuthority(StrEnum):
    NONE = "none"
    SUPPORT_NON_AUTHORITATIVE = "support_non_authoritative"
    ACCEPTED_AUTHORITATIVE = "accepted_authoritative"


class SupportArtifactDisposition(StrEnum):
    PENDING_REVIEW = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RETIRED = "retired"


class DependencyState(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"
    REPLACED = "replaced"


class SubscriptionQuotaState(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"
    EXHAUSTED = "exhausted"


class PaidApiBudgetState(StrEnum):
    NONE = "none"
    ACTIVE = "active"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    UNKNOWN = "unknown"


class BootstrapDependencyState(StrEnum):
    NONE = "none"
    ACTIVE = "active"
    EXPIRED = "expired"
    REPLACEMENT_OVERDUE = "replacement_overdue"


class LocalResourceState(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    STALE = "stale"
    UNKNOWN = "unknown"


class RouteAvailability(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class SpendGateDecisionState(StrEnum):
    ELIGIBLE_ACTIVE_BUDGET = "eligible_active_budget"
    REFUSED_NO_MATCHING_BUDGET = "refused_no_matching_budget"
    REFUSED_EXPIRED_BUDGET = "refused_expired_budget"
    REFUSED_EXHAUSTED_BUDGET = "refused_exhausted_budget"
    REFUSED_STALE_BUDGET_LEDGER = "refused_stale_budget_ledger"
    REFUSED_UNRECONCILED_SPEND = "refused_unreconciled_spend"
    REFUSED_BUDGET_GATE = "refused_budget_gate"


class SteadyStateReplacement(StrictModel):
    target_route_id: str | None = None
    blocker_to_remove: str | None = None
    exit_criterion: str | None = None

    def complete(self) -> bool:
        return all((self.target_route_id, self.blocker_to_remove, self.exit_criterion))


class TransitionBudget(StrictModel):
    """Time-boxed paid/API authority. Dates and caps are gates, not hints."""

    budget_schema: Literal[1] = 1
    budget_id: str = Field(pattern=r"^tb-\d{8}-[a-z0-9-]+$")
    authority_case: str = Field(min_length=1)
    approved_by: BudgetApproval
    created_at: datetime
    expires_at: datetime
    capacity_pool: CapacityPool
    providers_allowed: tuple[str, ...] = Field(min_length=1)
    profiles_allowed: tuple[str, ...] = Field(min_length=1)
    task_classes_allowed: tuple[str, ...] = Field(min_length=1)
    quality_floors_allowed: tuple[str, ...] = Field(min_length=1)
    total_cap_usd: Decimal = Field(ge=Decimal("0"))
    per_task_cap_usd: Decimal = Field(ge=Decimal("0"))
    daily_cap_usd: Decimal = Field(ge=Decimal("0"))
    auto_top_up_allowed: Literal[False] = False
    subscription_path_checked_at: datetime | None = None
    reason_subscription_path_not_used: str | None = None
    steady_state_replacement: SteadyStateReplacement = Field(default_factory=SteadyStateReplacement)
    ledger_owner: str | None = None
    dashboard_visibility: Literal["required"] = "required"
    lifecycle_state: BudgetLifecycleState = BudgetLifecycleState.ACTIVE

    @model_validator(mode="after")
    def _budget_contract(self) -> Self:
        _require_aware(self.created_at, "created_at")
        _require_aware(self.expires_at, "expires_at")
        if self.expires_at <= self.created_at:
            raise ValueError(f"{self.budget_id} expires_at must be after created_at")
        if self.capacity_pool.value not in PAID_CAPACITY_POOLS:
            raise ValueError(f"{self.budget_id} must use a paid/API capacity pool")
        if self.lifecycle_state is BudgetLifecycleState.ACTIVE:
            if self.total_cap_usd <= 0 or self.per_task_cap_usd <= 0 or self.daily_cap_usd <= 0:
                raise ValueError(f"{self.budget_id} active budgets require positive caps")
            if self.subscription_path_checked_at is None:
                raise ValueError(
                    f"{self.budget_id} active budgets require subscription path review"
                )
            _require_aware(self.subscription_path_checked_at, "subscription_path_checked_at")
            if not self.reason_subscription_path_not_used:
                raise ValueError(
                    f"{self.budget_id} active budgets require subscription-path rationale"
                )
        if self.capacity_pool is CapacityPool.BOOTSTRAP_BUDGET:
            if not self.steady_state_replacement.complete():
                raise ValueError(f"{self.budget_id} bootstrap budgets require replacement plan")
        _reject_private_or_identity_refs(
            _refs(
                self.budget_id,
                self.authority_case,
                *self.providers_allowed,
                *self.profiles_allowed,
                *self.task_classes_allowed,
                *self.quality_floors_allowed,
                self.ledger_owner,
            ),
            "transition budget",
        )
        return self

    def matches_request(self, request: PaidRouteRequest) -> bool:
        return (
            request.provider in self.providers_allowed
            and request.profile in self.profiles_allowed
            and request.task_class in self.task_classes_allowed
            and request.quality_floor in self.quality_floors_allowed
        )

    def is_unexpired_at(self, now: datetime) -> bool:
        return self.created_at <= now < self.expires_at


class SpendReceipt(StrictModel):
    """Estimated or reconciled spend event under a transition budget."""

    spend_receipt_schema: Literal[1] = 1
    spend_id: str = Field(pattern=r"^spend-\d{8}T\d{6}Z-[a-z0-9_.:-]+$")
    task_id: str = Field(min_length=1)
    authority_case: str = Field(min_length=1)
    route_id: str = Field(min_length=1)
    capacity_pool: CapacityPool
    budget_id: str | None = None
    provider: str = Field(min_length=1)
    model_or_engine: str | None = None
    auth_surface: AuthSurface
    quality_floor: str = Field(min_length=1)
    quality_preservation_reason: str = Field(min_length=1)
    spend_reason: SpendReason
    estimated_cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    actual_cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    cap_remaining_usd: Decimal | None = Field(default=None)
    created_at: datetime
    reconcile_by: datetime | None = None
    reconciliation_state: SpendReconciliationState = SpendReconciliationState.PENDING
    reconciled_at: datetime | None = None
    reconciliation_reason: str | None = None
    artifact_refs: tuple[str, ...] = Field(default=())
    support_artifact_authority: SupportArtifactAuthority = SupportArtifactAuthority.NONE

    @model_validator(mode="after")
    def _receipt_contract(self) -> Self:
        _require_aware(self.created_at, "created_at")
        if self.reconcile_by is not None:
            _require_aware(self.reconcile_by, "reconcile_by")
            if self.reconcile_by <= self.created_at:
                raise ValueError(f"{self.spend_id} reconcile_by must be after created_at")
        if self.capacity_pool.value in PAID_CAPACITY_POOLS:
            if not self.budget_id:
                raise ValueError(f"{self.spend_id} paid/API spend requires budget_id")
            if self.estimated_cost_usd is None and self.actual_cost_usd is None:
                raise ValueError(f"{self.spend_id} spend requires estimated or actual cost")
        if self.actual_cost_usd is None and self.estimated_cost_usd is not None:
            if self.reconcile_by is None:
                raise ValueError(f"{self.spend_id} estimated spend requires reconcile_by")
        if self.actual_cost_usd is not None and self.cap_remaining_usd is None:
            raise ValueError(f"{self.spend_id} reconciled spend requires cap_remaining_usd")
        if self.reconciled_at is not None:
            _require_aware(self.reconciled_at, "reconciled_at")
        if self.reconciliation_state is SpendReconciliationState.PENDING:
            if self.actual_cost_usd is not None:
                raise ValueError(f"{self.spend_id} actual spend requires reconciled state")
            if self.reconciled_at is not None or self.reconciliation_reason:
                raise ValueError(f"{self.spend_id} pending spend cannot carry reconciliation")
        elif self.reconciliation_state is SpendReconciliationState.RECONCILED:
            if self.actual_cost_usd is None:
                raise ValueError(f"{self.spend_id} reconciled spend requires actual cost")
            if self.reconciled_at is None or not self.reconciliation_reason:
                raise ValueError(f"{self.spend_id} reconciled spend requires review evidence")
        elif self.reconciliation_state is SpendReconciliationState.FROZEN_REFUSED:
            if self.actual_cost_usd is not None:
                raise ValueError(f"{self.spend_id} frozen/refused spend cannot claim actual cost")
            if self.reconciled_at is None or not self.reconciliation_reason:
                raise ValueError(f"{self.spend_id} frozen/refused spend requires review evidence")
        _reject_private_or_identity_refs(
            _refs(
                self.spend_id,
                self.task_id,
                self.authority_case,
                self.route_id,
                self.budget_id,
                self.provider,
                self.model_or_engine,
                self.quality_floor,
                self.quality_preservation_reason,
                self.reconciliation_reason,
                *self.artifact_refs,
            ),
            "spend receipt",
        )
        return self

    def cost_against_cap(self) -> Decimal:
        return self.actual_cost_usd or self.estimated_cost_usd or Decimal("0")

    def is_unreconciled_overdue(self, now: datetime) -> bool:
        return (
            self.reconciliation_state is SpendReconciliationState.PENDING
            and self.actual_cost_usd is None
            and self.estimated_cost_usd is not None
            and self.reconcile_by is not None
            and self.reconcile_by <= now
        )

    def is_frozen_refused(self) -> bool:
        return self.reconciliation_state is SpendReconciliationState.FROZEN_REFUSED


class ProviderDependencyRecord(StrictModel):
    dependency_schema: Literal[1] = 1
    dependency_id: str = Field(pattern=r"^dep-[a-z0-9_.:-]+$")
    route_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    capacity_pool: CapacityPool
    dependency_state: DependencyState = DependencyState.ACTIVE
    recurring: bool
    critical_path: bool
    transition_budget_id: str | None = None
    first_seen_at: datetime
    review_by: datetime
    last_reviewed_at: datetime | None = None
    replacement_route_id: str | None = None
    bootstrap_dependency: bool
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    operator_visible_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _dependency_contract(self) -> Self:
        _require_aware(self.first_seen_at, "first_seen_at")
        _require_aware(self.review_by, "review_by")
        if self.review_by <= self.first_seen_at:
            raise ValueError(f"{self.dependency_id} review_by must be after first_seen_at")
        if self.last_reviewed_at is not None:
            _require_aware(self.last_reviewed_at, "last_reviewed_at")
        if self.dependency_state is DependencyState.REPLACED and not self.replacement_route_id:
            raise ValueError(f"{self.dependency_id} replaced dependencies need replacement route")
        if self.dependency_state is not DependencyState.ACTIVE and self.last_reviewed_at is None:
            raise ValueError(f"{self.dependency_id} closed dependencies need review timestamp")
        if self.bootstrap_dependency:
            if self.capacity_pool is not CapacityPool.BOOTSTRAP_BUDGET:
                raise ValueError(f"{self.dependency_id} bootstrap dependencies need bootstrap pool")
            if not self.transition_budget_id:
                raise ValueError(f"{self.dependency_id} bootstrap dependencies need budget ref")
        _reject_private_or_identity_refs(
            _refs(
                self.dependency_id,
                self.route_id,
                self.provider,
                self.transition_budget_id,
                self.replacement_route_id,
                *self.evidence_refs,
                self.operator_visible_reason,
            ),
            "provider dependency",
        )
        return self


class ArtifactProvenanceRecord(StrictModel):
    provenance_schema: Literal[1] = 1
    provenance_id: str = Field(pattern=r"^prov-[a-z0-9_.:-]+$")
    artifact_refs: tuple[str, ...] = Field(min_length=1)
    produced_by_route_id: str = Field(min_length=1)
    produced_under_budget_id: str | None = None
    source_spend_receipt_ids: tuple[str, ...] = Field(default=())
    support_artifact_authority: SupportArtifactAuthority
    artifact_disposition: SupportArtifactDisposition = SupportArtifactDisposition.PENDING_REVIEW
    accepted_by_route_id: str | None = None
    accepted_at: datetime | None = None
    disposition_reviewed_at: datetime | None = None
    disposition_reason: str | None = None
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    operator_visible_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _provenance_contract(self) -> Self:
        if self.accepted_at is not None:
            _require_aware(self.accepted_at, "accepted_at")
        if self.disposition_reviewed_at is not None:
            _require_aware(self.disposition_reviewed_at, "disposition_reviewed_at")
        if self.support_artifact_authority is SupportArtifactAuthority.ACCEPTED_AUTHORITATIVE:
            if not self.accepted_by_route_id or self.accepted_at is None:
                raise ValueError(f"{self.provenance_id} accepted artifacts require acceptor")
            if self.artifact_disposition is not SupportArtifactDisposition.ACCEPTED:
                raise ValueError(
                    f"{self.provenance_id} accepted artifacts need accepted disposition"
                )
        else:
            if self.accepted_by_route_id or self.accepted_at is not None:
                raise ValueError(
                    f"{self.provenance_id} non-authoritative artifacts cannot carry acceptance"
                )
            if self.artifact_disposition is SupportArtifactDisposition.ACCEPTED:
                raise ValueError(
                    f"{self.provenance_id} accepted disposition requires authoritative acceptance"
                )
        if self.artifact_disposition in {
            SupportArtifactDisposition.REJECTED,
            SupportArtifactDisposition.RETIRED,
        }:
            if self.disposition_reviewed_at is None or not self.disposition_reason:
                raise ValueError(f"{self.provenance_id} closed artifacts require disposition")
        if (
            self.produced_under_budget_id
            and self.support_artifact_authority is SupportArtifactAuthority.NONE
        ):
            raise ValueError(
                f"{self.provenance_id} budget-produced artifacts require authority marker"
            )
        _reject_private_or_identity_refs(
            _refs(
                self.provenance_id,
                *self.artifact_refs,
                self.produced_by_route_id,
                self.produced_under_budget_id,
                *self.source_spend_receipt_ids,
                self.accepted_by_route_id,
                self.disposition_reason,
                *self.evidence_refs,
                self.operator_visible_reason,
            ),
            "artifact provenance",
        )
        return self

    def waiting_for_review(self) -> bool:
        return (
            self.produced_under_budget_id is not None
            and self.support_artifact_authority
            is SupportArtifactAuthority.SUPPORT_NON_AUTHORITATIVE
            and self.artifact_disposition is SupportArtifactDisposition.PENDING_REVIEW
        )


class RenewalRecord(StrictModel):
    renewal_schema: Literal[1] = 1
    renewal_id: str = Field(pattern=r"^renew-[a-z0-9_.:-]+$")
    provider: str = Field(min_length=1)
    auth_surface: AuthSurface
    capacity_pool: CapacityPool
    recurring_cost_usd: Decimal | None = Field(default=None, ge=Decimal("0"))
    subscription_renewal_at: datetime | None = None
    top_up_enabled: Literal[False] = False
    hard_expiry_review_at: datetime
    cancellation_or_exit_ref: str | None = None
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    operator_visible_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _renewal_contract(self) -> Self:
        if self.subscription_renewal_at is not None:
            _require_aware(self.subscription_renewal_at, "subscription_renewal_at")
        _require_aware(self.hard_expiry_review_at, "hard_expiry_review_at")
        if self.capacity_pool.value in PAID_CAPACITY_POOLS and self.recurring_cost_usd is None:
            raise ValueError(f"{self.renewal_id} paid/API renewals require cost marker")
        _reject_private_or_identity_refs(
            _refs(
                self.renewal_id,
                self.provider,
                self.cancellation_or_exit_ref,
                *self.evidence_refs,
                self.operator_visible_reason,
            ),
            "renewal",
        )
        return self


class QuotaSnapshot(StrictModel):
    quota_snapshot_schema: Literal[1] = 1
    snapshot_id: str = Field(pattern=r"^quota-[a-z0-9_.:-]+$")
    captured_at: datetime
    route_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    capacity_pool: CapacityPool
    subscription_quota_state: SubscriptionQuotaState
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    operator_visible_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def _quota_snapshot_contract(self) -> Self:
        _require_aware(self.captured_at, "captured_at")
        _reject_private_or_identity_refs(
            [
                self.snapshot_id,
                self.route_id,
                self.provider,
                *self.evidence_refs,
                self.operator_visible_reason,
            ],
            "quota snapshot",
        )
        return self


class PaidRouteRequest(StrictModel):
    route_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    task_class: str = Field(min_length=1)
    quality_floor: str = Field(min_length=1)
    estimated_cost_usd: Decimal = Field(gt=Decimal("0"))
    capacity_pool: CapacityPool = CapacityPool.API_PAID_SPEND

    @model_validator(mode="after")
    def _paid_route_request_contract(self) -> Self:
        if self.capacity_pool.value not in PAID_CAPACITY_POOLS:
            raise ValueError("paid route eligibility can only evaluate paid/API capacity pools")
        _reject_private_or_identity_refs(
            [
                self.route_id,
                self.provider,
                self.profile,
                self.task_class,
            ],
            "paid route request",
        )
        return self


class PaidRouteEligibility(StrictModel):
    eligible: bool
    state: str
    budget_id: str | None = None
    cap_remaining_usd: Decimal | None = None
    blocking_reasons: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())


class SpendGateDecisionRecord(StrictModel):
    """Recorded paid/API gate decision, including rejected decisions."""

    decision_schema: Literal[1] = 1
    decision_id: str = Field(pattern=r"^sgd-[a-z0-9_.:-]+$")
    created_at: datetime
    route_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    task_class: str = Field(min_length=1)
    quality_floor: str = Field(min_length=1)
    capacity_pool: CapacityPool
    requested_cost_usd: Decimal = Field(ge=Decimal("0"))
    decision_state: SpendGateDecisionState
    eligible: bool
    budget_id: str | None = None
    blocking_reasons: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())

    @model_validator(mode="after")
    def _decision_contract(self) -> Self:
        _require_aware(self.created_at, "created_at")
        if self.capacity_pool.value not in PAID_CAPACITY_POOLS:
            raise ValueError(f"{self.decision_id} spend gates require paid/API pool")
        if self.eligible:
            if self.decision_state is not SpendGateDecisionState.ELIGIBLE_ACTIVE_BUDGET:
                raise ValueError(f"{self.decision_id} eligible decisions need eligible state")
            if not self.budget_id:
                raise ValueError(f"{self.decision_id} eligible decisions require budget_id")
            if self.blocking_reasons:
                raise ValueError(f"{self.decision_id} eligible decisions cannot have blockers")
        else:
            if self.decision_state is SpendGateDecisionState.ELIGIBLE_ACTIVE_BUDGET:
                raise ValueError(f"{self.decision_id} refused decisions cannot use eligible state")
            if not self.blocking_reasons:
                raise ValueError(f"{self.decision_id} refused decisions require blockers")
        _reject_private_or_identity_refs(
            _refs(
                self.decision_id,
                self.route_id,
                self.provider,
                self.profile,
                self.task_class,
                self.quality_floor,
                self.budget_id,
                *self.blocking_reasons,
                *self.evidence_refs,
            ),
            "spend gate decision",
        )
        return self


class QuotaSpendDashboard(StrictModel):
    quality_preserving_routes_available: RouteAvailability
    blocked_quality_floor_reason: str | None = None
    subscription_quota_state: SubscriptionQuotaState
    paid_api_budget_state: PaidApiBudgetState
    bootstrap_dependency_state: BootstrapDependencyState
    local_resource_state: LocalResourceState
    current_capacity_pool: CapacityPool | None = None
    next_budget_review_at: datetime | None = None
    provider_dependency_count: int = Field(ge=0)
    support_artifacts_waiting_for_review: int = Field(ge=0)
    budget_ledger_stale: bool
    paid_api_route_eligible: bool
    paid_api_blocking_reasons: tuple[str, ...] = Field(default=())
    non_green_states: tuple[str, ...] = Field(default=())
    transition_budget_refs: tuple[str, ...] = Field(default=())
    unreconciled_spend_refs: tuple[str, ...] = Field(default=())
    frozen_spend_refs: tuple[str, ...] = Field(default=())
    provider_dependency_refs: tuple[str, ...] = Field(default=())
    closed_provider_dependency_refs: tuple[str, ...] = Field(default=())
    support_artifact_refs: tuple[str, ...] = Field(default=())
    closed_support_artifact_refs: tuple[str, ...] = Field(default=())
    renewal_review_refs: tuple[str, ...] = Field(default=())


class QuotaSpendLedger(StrictModel):
    """Complete local ledger fixture. Loading this grants no spend authority."""

    schema_version: Literal[1] = 1
    ledger_id: str = Field(min_length=1)
    captured_at: datetime
    authority_source: Literal["isap:quota-spend-ledger-20260509"]
    generated_from: tuple[str, ...] = Field(min_length=1)
    privacy_scope: Literal["private"] = "private"
    consumer_permission_after: Literal["private_capacity_routing_tests_only"]
    paid_api_budget_freshness_ttl_s: int = Field(default=60, ge=0)
    quality_preserving_routes_available: RouteAvailability = RouteAvailability.UNKNOWN
    blocked_quality_floor_reason: str | None = None
    local_resource_state: LocalResourceState = LocalResourceState.UNKNOWN
    quota_snapshots: tuple[QuotaSnapshot, ...] = Field(default=())
    transition_budgets: tuple[TransitionBudget, ...] = Field(default=())
    spend_receipts: tuple[SpendReceipt, ...] = Field(default=())
    spend_gate_decisions: tuple[SpendGateDecisionRecord, ...] = Field(default=())
    provider_dependencies: tuple[ProviderDependencyRecord, ...] = Field(default=())
    artifact_provenance: tuple[ArtifactProvenanceRecord, ...] = Field(default=())
    renewal_records: tuple[RenewalRecord, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ledger_contract(self) -> Self:
        _require_aware(self.captured_at, "captured_at")
        _reject_private_or_identity_refs(
            [self.ledger_id, *self.generated_from, *self.evidence_refs],
            "quota spend ledger",
        )
        _require_unique("budget_id", [budget.budget_id for budget in self.transition_budgets])
        _require_unique("spend_id", [receipt.spend_id for receipt in self.spend_receipts])
        _require_unique(
            "decision_id", [decision.decision_id for decision in self.spend_gate_decisions]
        )
        _require_unique(
            "dependency_id", [dependency.dependency_id for dependency in self.provider_dependencies]
        )
        _require_unique(
            "provenance_id", [record.provenance_id for record in self.artifact_provenance]
        )
        _require_unique("renewal_id", [record.renewal_id for record in self.renewal_records])
        _require_unique(
            "quota snapshot_id", [snapshot.snapshot_id for snapshot in self.quota_snapshots]
        )

        budget_ids = {budget.budget_id for budget in self.transition_budgets}
        spend_ids = {receipt.spend_id for receipt in self.spend_receipts}
        for receipt in self.spend_receipts:
            if receipt.budget_id and receipt.budget_id not in budget_ids:
                raise ValueError(f"{receipt.spend_id} references unknown budget")
        for decision in self.spend_gate_decisions:
            if decision.budget_id and decision.budget_id not in budget_ids:
                raise ValueError(f"{decision.decision_id} references unknown budget")
        for dependency in self.provider_dependencies:
            if (
                dependency.transition_budget_id
                and dependency.transition_budget_id not in budget_ids
            ):
                raise ValueError(f"{dependency.dependency_id} references unknown budget")
        for provenance in self.artifact_provenance:
            if (
                provenance.produced_under_budget_id
                and provenance.produced_under_budget_id not in budget_ids
            ):
                raise ValueError(f"{provenance.provenance_id} references unknown budget")
            missing_spends = set(provenance.source_spend_receipt_ids) - spend_ids
            if missing_spends:
                raise ValueError(
                    f"{provenance.provenance_id} references unknown spend receipts: "
                    f"{sorted(missing_spends)}"
                )
        return self

    def budget_by_id(self, budget_id: str) -> TransitionBudget:
        for budget in self.transition_budgets:
            if budget.budget_id == budget_id:
                return budget
        raise QuotaSpendLedgerError(f"missing transition budget {budget_id}")

    def active_paid_budgets(self, now: datetime | None = None) -> tuple[TransitionBudget, ...]:
        when = _coerce_now(now)
        return tuple(
            budget
            for budget in self.transition_budgets
            if budget.lifecycle_state is BudgetLifecycleState.ACTIVE
            and budget.capacity_pool.value in PAID_CAPACITY_POOLS
            and budget.is_unexpired_at(when)
            and self._budget_remaining_usd(budget) > 0
        )

    def _budget_receipts(self, budget: TransitionBudget) -> tuple[SpendReceipt, ...]:
        return tuple(
            receipt for receipt in self.spend_receipts if receipt.budget_id == budget.budget_id
        )

    def _budget_spent_usd(self, budget: TransitionBudget) -> Decimal:
        return sum(
            (receipt.cost_against_cap() for receipt in self._budget_receipts(budget)),
            start=Decimal("0"),
        )

    def _budget_spent_today_usd(self, budget: TransitionBudget, now: datetime) -> Decimal:
        today = now.date()
        return sum(
            (
                receipt.cost_against_cap()
                for receipt in self._budget_receipts(budget)
                if receipt.created_at.astimezone(UTC).date() == today
            ),
            start=Decimal("0"),
        )

    def _budget_remaining_usd(self, budget: TransitionBudget) -> Decimal:
        remaining = budget.total_cap_usd - self._budget_spent_usd(budget)
        return max(Decimal("0"), remaining)

    def budget_has_overdue_reconciliation(self, budget: TransitionBudget, now: datetime) -> bool:
        return any(
            receipt.is_unreconciled_overdue(now) for receipt in self._budget_receipts(budget)
        )

    def budget_has_frozen_refused_spend(self, budget: TransitionBudget) -> bool:
        return any(receipt.is_frozen_refused() for receipt in self._budget_receipts(budget))

    def ledger_stale(self, now: datetime | None = None) -> bool:
        when = _coerce_now(now)
        age_s = (when - self.captured_at).total_seconds()
        return age_s > self.paid_api_budget_freshness_ttl_s


def evaluate_paid_route_eligibility(
    ledger: QuotaSpendLedger,
    request: PaidRouteRequest,
    *,
    now: datetime | None = None,
) -> PaidRouteEligibility:
    """Return paid/API route eligibility; every uncertainty is a refusal."""

    when = _coerce_now(now)
    blocking: list[str] = []
    evidence_refs: list[str] = []
    matching = tuple(
        budget for budget in ledger.transition_budgets if budget.matches_request(request)
    )

    if ledger.ledger_stale(when):
        blocking.append("budget ledger stale")

    if not matching:
        blocking.append("no matching TransitionBudget")
        return PaidRouteEligibility(
            eligible=False,
            state="refused_no_matching_budget",
            blocking_reasons=tuple(blocking),
        )

    overdue = tuple(
        budget for budget in matching if ledger.budget_has_overdue_reconciliation(budget, when)
    )
    if overdue:
        blocking.append(
            "unreconciled spend receipts overdue for " + ", ".join(b.budget_id for b in overdue)
        )
    frozen = tuple(budget for budget in matching if ledger.budget_has_frozen_refused_spend(budget))
    if frozen:
        blocking.append(
            "frozen/refused spend receipts for " + ", ".join(b.budget_id for b in frozen)
        )

    unexpired = tuple(
        budget
        for budget in matching
        if budget.lifecycle_state is BudgetLifecycleState.ACTIVE and budget.is_unexpired_at(when)
    )
    if not unexpired:
        blocking.append("matching TransitionBudget expired or inactive")
        return PaidRouteEligibility(
            eligible=False,
            state="refused_expired_budget",
            blocking_reasons=tuple(blocking),
            evidence_refs=tuple(b.budget_id for b in matching),
        )

    cap_eligible: list[tuple[TransitionBudget, Decimal]] = []
    for budget in unexpired:
        remaining = ledger._budget_remaining_usd(budget)
        daily_remaining = budget.daily_cap_usd - ledger._budget_spent_today_usd(budget, when)
        if request.estimated_cost_usd > budget.per_task_cap_usd:
            continue
        if request.estimated_cost_usd > remaining:
            continue
        if request.estimated_cost_usd > daily_remaining:
            continue
        cap_eligible.append((budget, remaining - request.estimated_cost_usd))

    if not cap_eligible:
        blocking.append("matching TransitionBudget cap exhausted")
        return PaidRouteEligibility(
            eligible=False,
            state="refused_exhausted_budget",
            blocking_reasons=tuple(blocking),
            evidence_refs=tuple(b.budget_id for b in unexpired),
        )

    if blocking:
        return PaidRouteEligibility(
            eligible=False,
            state="refused_budget_gate",
            blocking_reasons=tuple(blocking),
            evidence_refs=tuple(b.budget_id for b, _ in cap_eligible),
        )

    budget, cap_remaining = cap_eligible[0]
    evidence_refs.append(budget.budget_id)
    return PaidRouteEligibility(
        eligible=True,
        state="eligible_active_budget",
        budget_id=budget.budget_id,
        cap_remaining_usd=cap_remaining,
        evidence_refs=tuple(evidence_refs),
    )


def build_dashboard(
    ledger: QuotaSpendLedger,
    *,
    now: datetime | None = None,
) -> QuotaSpendDashboard:
    """Build private dashboard JSON fields from the inert ledger state."""

    when = _coerce_now(now)
    ledger_stale = ledger.ledger_stale(when)
    paid_state = _paid_api_budget_state(ledger, when)
    bootstrap_state = _bootstrap_dependency_state(ledger, when)
    subscription_state = _subscription_quota_state(ledger)
    support_waiting = tuple(
        record for record in ledger.artifact_provenance if record.waiting_for_review()
    )
    overdue_receipts = tuple(
        receipt for receipt in ledger.spend_receipts if receipt.is_unreconciled_overdue(when)
    )
    frozen_receipts = tuple(
        receipt for receipt in ledger.spend_receipts if receipt.is_frozen_refused()
    )
    active_dependency_refs = tuple(
        dependency.dependency_id
        for dependency in ledger.provider_dependencies
        if dependency.dependency_state is DependencyState.ACTIVE
    )
    closed_dependency_refs = tuple(
        dependency.dependency_id
        for dependency in ledger.provider_dependencies
        if dependency.dependency_state is not DependencyState.ACTIVE
    )
    closed_support_artifact_refs = tuple(
        ref
        for record in ledger.artifact_provenance
        if record.artifact_disposition
        in {SupportArtifactDisposition.REJECTED, SupportArtifactDisposition.RETIRED}
        for ref in record.artifact_refs
    )
    non_green = _non_green_states(
        ledger_stale=ledger_stale,
        paid_state=paid_state,
        bootstrap_state=bootstrap_state,
        subscription_state=subscription_state,
        local_resource_state=ledger.local_resource_state,
        overdue_receipts=overdue_receipts,
    )
    return QuotaSpendDashboard(
        quality_preserving_routes_available=ledger.quality_preserving_routes_available,
        blocked_quality_floor_reason=ledger.blocked_quality_floor_reason,
        subscription_quota_state=subscription_state,
        paid_api_budget_state=paid_state,
        bootstrap_dependency_state=bootstrap_state,
        local_resource_state=ledger.local_resource_state,
        current_capacity_pool=(
            ledger.active_paid_budgets(when)[0].capacity_pool
            if ledger.active_paid_budgets(when) and not ledger_stale
            else None
        ),
        next_budget_review_at=_next_budget_review_at(ledger),
        provider_dependency_count=len(active_dependency_refs),
        support_artifacts_waiting_for_review=len(support_waiting),
        budget_ledger_stale=ledger_stale,
        paid_api_route_eligible=paid_state is PaidApiBudgetState.ACTIVE and not ledger_stale,
        paid_api_blocking_reasons=tuple(non_green),
        non_green_states=tuple(non_green),
        transition_budget_refs=tuple(budget.budget_id for budget in ledger.transition_budgets),
        unreconciled_spend_refs=tuple(receipt.spend_id for receipt in overdue_receipts),
        frozen_spend_refs=tuple(receipt.spend_id for receipt in frozen_receipts),
        provider_dependency_refs=active_dependency_refs,
        closed_provider_dependency_refs=closed_dependency_refs,
        support_artifact_refs=tuple(
            ref for record in support_waiting for ref in record.artifact_refs
        ),
        closed_support_artifact_refs=closed_support_artifact_refs,
        renewal_review_refs=tuple(record.renewal_id for record in ledger.renewal_records),
    )


def load_quota_spend_ledger(path: Path = QUOTA_SPEND_LEDGER_FIXTURES) -> QuotaSpendLedger:
    """Load quota/spend fixtures, failing closed on malformed data."""

    try:
        return QuotaSpendLedger.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise QuotaSpendLedgerError(f"invalid quota/spend ledger at {path}: {exc}") from exc


def _paid_api_budget_state(ledger: QuotaSpendLedger, now: datetime) -> PaidApiBudgetState:
    if not ledger.transition_budgets:
        return PaidApiBudgetState.NONE
    if ledger.active_paid_budgets(now):
        if any(
            ledger.budget_has_overdue_reconciliation(budget, now)
            for budget in ledger.active_paid_budgets(now)
        ):
            return PaidApiBudgetState.UNKNOWN
        return PaidApiBudgetState.ACTIVE
    active_lifecycle = tuple(
        budget
        for budget in ledger.transition_budgets
        if budget.lifecycle_state is BudgetLifecycleState.ACTIVE
    )
    if active_lifecycle and all(budget.expires_at <= now for budget in active_lifecycle):
        return PaidApiBudgetState.EXPIRED
    if active_lifecycle and all(
        ledger._budget_remaining_usd(budget) <= 0 for budget in active_lifecycle
    ):
        return PaidApiBudgetState.EXHAUSTED
    return PaidApiBudgetState.UNKNOWN


def _bootstrap_dependency_state(
    ledger: QuotaSpendLedger, now: datetime
) -> BootstrapDependencyState:
    dependencies = tuple(
        dependency
        for dependency in ledger.provider_dependencies
        if dependency.dependency_state is DependencyState.ACTIVE and dependency.bootstrap_dependency
    )
    if not dependencies:
        return BootstrapDependencyState.NONE
    for dependency in dependencies:
        if dependency.transition_budget_id:
            budget = ledger.budget_by_id(dependency.transition_budget_id)
            if budget.expires_at <= now:
                return BootstrapDependencyState.EXPIRED
    if any(
        dependency.review_by <= now or not dependency.replacement_route_id
        for dependency in dependencies
    ):
        return BootstrapDependencyState.REPLACEMENT_OVERDUE
    return BootstrapDependencyState.ACTIVE


def _subscription_quota_state(ledger: QuotaSpendLedger) -> SubscriptionQuotaState:
    if not ledger.quota_snapshots:
        return SubscriptionQuotaState.UNKNOWN
    if any(
        snapshot.subscription_quota_state is SubscriptionQuotaState.FRESH
        for snapshot in ledger.quota_snapshots
    ):
        return SubscriptionQuotaState.FRESH
    if any(
        snapshot.subscription_quota_state is SubscriptionQuotaState.EXHAUSTED
        for snapshot in ledger.quota_snapshots
    ):
        return SubscriptionQuotaState.EXHAUSTED
    if any(
        snapshot.subscription_quota_state is SubscriptionQuotaState.STALE
        for snapshot in ledger.quota_snapshots
    ):
        return SubscriptionQuotaState.STALE
    return SubscriptionQuotaState.UNKNOWN


def _next_budget_review_at(ledger: QuotaSpendLedger) -> datetime | None:
    candidates: list[datetime] = []
    candidates.extend(
        budget.expires_at
        for budget in ledger.transition_budgets
        if budget.lifecycle_state is BudgetLifecycleState.ACTIVE
    )
    candidates.extend(
        dependency.review_by
        for dependency in ledger.provider_dependencies
        if dependency.dependency_state is DependencyState.ACTIVE
    )
    candidates.extend(record.hard_expiry_review_at for record in ledger.renewal_records)
    return min(candidates) if candidates else None


def _non_green_states(
    *,
    ledger_stale: bool,
    paid_state: PaidApiBudgetState,
    bootstrap_state: BootstrapDependencyState,
    subscription_state: SubscriptionQuotaState,
    local_resource_state: LocalResourceState,
    overdue_receipts: tuple[SpendReceipt, ...],
) -> list[str]:
    states: list[str] = []
    if ledger_stale:
        states.append("budget_ledger_stale")
    if paid_state is not PaidApiBudgetState.ACTIVE:
        states.append(f"paid_api_budget_state:{paid_state.value}")
    if bootstrap_state not in {
        BootstrapDependencyState.NONE,
        BootstrapDependencyState.ACTIVE,
    }:
        states.append(f"bootstrap_dependency_state:{bootstrap_state.value}")
    if subscription_state is not SubscriptionQuotaState.FRESH:
        states.append(f"subscription_quota_state:{subscription_state.value}")
    if local_resource_state not in {LocalResourceState.GREEN, LocalResourceState.YELLOW}:
        states.append(f"local_resource_state:{local_resource_state.value}")
    if overdue_receipts:
        states.append("spend_reconciliation_overdue")
    return states


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise QuotaSpendLedgerError(f"{path} did not contain a JSON object")
    return payload


def _coerce_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(tz=UTC)
    _require_aware(now, "now")
    return now.astimezone(UTC)


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_unique(label: str, values: list[str]) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} values must be unique")


def _reject_private_or_identity_refs(refs: list[str], label: str) -> None:
    if any(ref.startswith(("/", "~")) for ref in refs):
        raise ValueError(f"{label} refs must stay repo-relative or symbolic")
    if any("@" in ref for ref in refs):
        raise ValueError(f"{label} refs must not contain raw email addresses")


def _refs(*values: str | None) -> list[str]:
    return [value for value in values if value is not None]


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    TransitionBudget._budget_contract,
    SpendReceipt._receipt_contract,
    ProviderDependencyRecord._dependency_contract,
    ArtifactProvenanceRecord._provenance_contract,
    RenewalRecord._renewal_contract,
    QuotaSnapshot._quota_snapshot_contract,
    PaidRouteRequest._paid_route_request_contract,
    SpendGateDecisionRecord._decision_contract,
    QuotaSpendLedger._ledger_contract,
)


__all__ = [
    "PAID_CAPACITY_POOLS",
    "QUOTA_SPEND_LEDGER_FIXTURES",
    "ArtifactProvenanceRecord",
    "AuthSurface",
    "BootstrapDependencyState",
    "BudgetApproval",
    "BudgetLifecycleState",
    "CapacityPool",
    "DependencyState",
    "LocalResourceState",
    "PaidApiBudgetState",
    "PaidRouteEligibility",
    "PaidRouteRequest",
    "ProviderDependencyRecord",
    "QuotaSnapshot",
    "QuotaSpendDashboard",
    "QuotaSpendLedger",
    "QuotaSpendLedgerError",
    "RenewalRecord",
    "RouteAvailability",
    "SpendReason",
    "SpendGateDecisionRecord",
    "SpendGateDecisionState",
    "SpendReceipt",
    "SteadyStateReplacement",
    "SubscriptionQuotaState",
    "SupportArtifactAuthority",
    "TransitionBudget",
    "build_dashboard",
    "evaluate_paid_route_eligibility",
    "load_quota_spend_ledger",
]
