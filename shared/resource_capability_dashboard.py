"""Private observe-only resource-capability dashboard substrate.

This module is intentionally inert. It validates dashboard snapshots over the
resource-capability and read-only backfill fixture layers, but it does not
publish UI, dispatch work, call providers, read credentials, send mail, write
calendars, or move money.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.resource_capability import (
    ActionClass,
    AuthorityCeiling,
    DecisionState,
    PublicClaimCeiling,
)
from shared.resource_capability_backfill import REQUIRED_STALE_CONFLICT_IDS

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_CAPABILITY_DASHBOARD_FIXTURES = (
    REPO_ROOT / "config" / "resource-capability-dashboard-fixtures.json"
)

REQUIRED_DASHBOARD_VIEW_KINDS = frozenset(
    {
        "account_resource_growth",
        "autonomy_debt_operator_touch",
        "prediction_status",
        "tax_evidence_gap",
        "dispute_fraud_stale_metric",
        "blocked_stale_conflict",
        "next_eligible_action_candidate",
    }
)


class ResourceCapabilityDashboardError(ValueError):
    """Raised when dashboard fixtures cannot be loaded safely."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DashboardViewKind(StrEnum):
    ACCOUNT_RESOURCE_GROWTH = "account_resource_growth"
    AUTONOMY_DEBT_OPERATOR_TOUCH = "autonomy_debt_operator_touch"
    PREDICTION_STATUS = "prediction_status"
    TAX_EVIDENCE_GAP = "tax_evidence_gap"
    DISPUTE_FRAUD_STALE_METRIC = "dispute_fraud_stale_metric"
    BLOCKED_STALE_CONFLICT = "blocked_stale_conflict"
    NEXT_ELIGIBLE_ACTION_CANDIDATE = "next_eligible_action_candidate"


class DashboardRecommendationState(StrEnum):
    OBSERVED = "observed"
    BLOCKED_RECOMMENDATION = "blocked_recommendation"
    NO_ACTION = "no_action"


class DashboardAuthorityBlock(StrictModel):
    """Dashboard output is observational only, even when inputs contain gates."""

    dashboard_action_authorized: Literal[False] = False
    output_action_authority: Literal[False] = False
    dispatch_authorized: Literal[False] = False
    provider_api_execution_authorized: Literal[False] = False
    credential_lookup_authorized: Literal[False] = False
    outbound_email_authorized: Literal[False] = False
    live_calendar_write_authorized: Literal[False] = False
    payment_movement_authorized: Literal[False] = False
    public_offer_authorized: Literal[False] = False
    public_claim_upgrade_authorized: Literal[False] = False
    public_projection_allowed: Literal[False] = False
    runtime_feeder_execution_authorized: Literal[False] = False
    external_action_authorized: Literal[False] = False


class DashboardRow(DashboardAuthorityBlock):
    """One private observe-only dashboard row."""

    row_id: str
    view_kind: DashboardViewKind
    source_ref: str
    evidence_refs: list[str] = Field(min_length=1)
    resource_refs: list[str] = Field(default_factory=list)
    metric_refs: list[str] = Field(default_factory=list)
    stale_conflict_refs: list[str] = Field(default_factory=list)
    action_candidate_refs: list[str] = Field(default_factory=list)
    underlying_action_classes: list[ActionClass] = Field(default_factory=list)
    observed_value: str
    freshness_ttl_s: int = Field(ge=0)
    stale_behavior: DecisionState
    decision_state: DecisionState
    recommendation_state: DashboardRecommendationState
    authority_ceiling: AuthorityCeiling = AuthorityCeiling.NO_CLAIM
    public_claim_ceiling: PublicClaimCeiling = PublicClaimCeiling.NONE
    operator_visible_reason: str

    @model_validator(mode="after")
    def _row_stays_private_and_non_actioning(self) -> Self:
        refs = (
            [self.source_ref]
            + self.evidence_refs
            + self.resource_refs
            + self.metric_refs
            + self.stale_conflict_refs
            + self.action_candidate_refs
        )
        if any(ref.startswith(("/", "~")) for ref in refs):
            raise ValueError("dashboard refs must stay repo-relative or symbolic")
        if any("@" in ref for ref in refs):
            raise ValueError("dashboard refs must not contain raw email addresses")
        if self.public_claim_ceiling is not PublicClaimCeiling.NONE:
            raise ValueError("dashboard rows cannot raise public claim ceiling")
        if self.authority_ceiling not in {
            AuthorityCeiling.NO_CLAIM,
            AuthorityCeiling.INTERNAL_ONLY,
        }:
            raise ValueError("dashboard rows cannot carry public/evidence authority")

        if self.view_kind is DashboardViewKind.BLOCKED_STALE_CONFLICT:
            if self.decision_state is not DecisionState.BLOCKED_STALE_CONFLICT:
                raise ValueError("blocked conflict dashboard rows must stay blocked")
            if not self.stale_conflict_refs:
                raise ValueError("blocked conflict dashboard rows require conflict refs")
        if (
            self.stale_conflict_refs
            and self.decision_state is not DecisionState.BLOCKED_STALE_CONFLICT
        ):
            raise ValueError("rows with stale_conflict_refs must stay blocked_stale_conflict")
        if (
            self.action_candidate_refs
            and self.recommendation_state is not DashboardRecommendationState.NO_ACTION
        ):
            raise ValueError("action candidates must remain no_action dashboard rows")
        return self


class PlanningOnlyBudgetEnvelope(DashboardAuthorityBlock):
    """Symbolic planning capacity only; it never records committed live funds."""

    envelope_id: str
    basis: Literal["operator_hypothetical_or_future_budget"] = (
        "operator_hypothetical_or_future_budget"
    )
    nominal_available_usd: None = None
    operator_commitment_confirmed: Literal[False] = False
    planning_authority: Literal[True] = True
    spend_authorized: Literal[False] = False
    cash_movement_authorized: Literal[False] = False
    evidence_refs: list[str] = Field(min_length=1)
    operator_visible_reason: str

    @model_validator(mode="after")
    def _budget_is_not_live_spend_authority(self) -> Self:
        if self.nominal_available_usd is not None:
            raise ValueError("planning-only budget cannot record a live budget amount")
        return self


class ResourceCapabilityDashboardSnapshot(DashboardAuthorityBlock):
    """Complete private observe-only dashboard snapshot."""

    schema_version: Literal[1] = 1
    snapshot_id: str
    observed_at: str
    authority_source: Literal["isap:resource-capability-observe-only-dashboard-20260508"]
    generated_from: list[str] = Field(min_length=1)
    source_fixture_refs: list[str] = Field(min_length=2)
    privacy_scope: Literal["private"] = "private"
    consumer_permission_after: Literal["private_observe_only_dashboard_tests_only"]
    dashboard_rows: list[DashboardRow] = Field(min_length=7)
    observer_posture_snapshot_refs: list[str] = Field(min_length=1)
    account_refs: list[str] = Field(min_length=1)
    prediction_refs: list[str] = Field(min_length=1)
    measurement_contract_refs: list[str] = Field(min_length=1)
    autonomy_debt_event_refs: list[str] = Field(default_factory=list)
    blocked_conflict_refs: list[str] = Field(min_length=1)
    next_eligible_action_candidate_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)
    freshness_ttl_s: int = Field(ge=0)

    @model_validator(mode="after")
    def _snapshot_contract(self) -> Self:
        generated = set(self.generated_from)
        required_generated = {
            "shared/resource_capability.py",
            "shared/resource_capability_backfill.py",
            "config/resource-capability-fixtures.json",
            "config/resource-capability-backfill-fixtures.json",
        }
        if not required_generated.issubset(generated):
            missing = required_generated - generated
            raise ValueError(f"dashboard snapshot missing generated_from refs: {sorted(missing)}")

        row_ids = [row.row_id for row in self.dashboard_rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("dashboard row_id values must be unique")

        view_kinds = {row.view_kind.value for row in self.dashboard_rows}
        if not REQUIRED_DASHBOARD_VIEW_KINDS.issubset(view_kinds):
            missing = REQUIRED_DASHBOARD_VIEW_KINDS - view_kinds
            raise ValueError(f"dashboard missing required view kinds: {sorted(missing)}")

        conflict_refs = set(self.blocked_conflict_refs)
        if not REQUIRED_STALE_CONFLICT_IDS.issubset(conflict_refs):
            missing = REQUIRED_STALE_CONFLICT_IDS - conflict_refs
            raise ValueError(f"dashboard missing required conflict refs: {sorted(missing)}")

        if any(row.dashboard_action_authorized for row in self.dashboard_rows):
            raise ValueError("dashboard rows cannot authorize actions")
        if any(row.output_action_authority for row in self.dashboard_rows):
            raise ValueError("dashboard rows cannot carry output action authority")
        if any(row.public_projection_allowed for row in self.dashboard_rows):
            raise ValueError("dashboard rows cannot allow public projection")
        return self


class ResourceCapabilityDashboardFixtureSet(StrictModel):
    """Private fixture set for RC-003 observe-only dashboard substrate."""

    schema_version: Literal[1] = 1
    fixture_set_id: str
    consumer_permission_after: Literal["private_observe_only_dashboard_tests_only"]
    dashboard_snapshots: list[ResourceCapabilityDashboardSnapshot] = Field(min_length=1)
    planning_only_budget_envelopes: list[PlanningOnlyBudgetEnvelope] = Field(min_length=1)

    @model_validator(mode="after")
    def _fixture_set_is_private_and_observe_only(self) -> Self:
        if any(snapshot.public_projection_allowed for snapshot in self.dashboard_snapshots):
            raise ValueError("dashboard snapshots cannot allow public projection")
        if any(snapshot.dashboard_action_authorized for snapshot in self.dashboard_snapshots):
            raise ValueError("dashboard snapshots cannot authorize actions")
        if any(envelope.spend_authorized for envelope in self.planning_only_budget_envelopes):
            raise ValueError("planning-only budget envelopes cannot authorize spend")
        return self


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResourceCapabilityDashboardError(f"{path} did not contain a JSON object")
    return payload


def load_resource_capability_dashboard_fixtures(
    path: Path = RESOURCE_CAPABILITY_DASHBOARD_FIXTURES,
) -> ResourceCapabilityDashboardFixtureSet:
    """Load RC-003 dashboard fixtures, failing closed on malformed data."""

    try:
        return ResourceCapabilityDashboardFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ResourceCapabilityDashboardError(
            f"invalid resource capability dashboard fixtures at {path}: {exc}"
        ) from exc


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    DashboardRow._row_stays_private_and_non_actioning,
    PlanningOnlyBudgetEnvelope._budget_is_not_live_spend_authority,
    ResourceCapabilityDashboardSnapshot._snapshot_contract,
    ResourceCapabilityDashboardFixtureSet._fixture_set_is_private_and_observe_only,
)


__all__ = [
    "REQUIRED_DASHBOARD_VIEW_KINDS",
    "RESOURCE_CAPABILITY_DASHBOARD_FIXTURES",
    "DashboardRecommendationState",
    "DashboardRow",
    "DashboardViewKind",
    "PlanningOnlyBudgetEnvelope",
    "ResourceCapabilityDashboardError",
    "ResourceCapabilityDashboardFixtureSet",
    "ResourceCapabilityDashboardSnapshot",
    "load_resource_capability_dashboard_fixtures",
]
