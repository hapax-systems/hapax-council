"""Private read-only resource-capability backfill projections.

This module is deliberately inert. It loads typed fixture rows and projects
local documentation/registry facts into the private resource-capability schema;
it does not import provider rails, read credentials, call services, publish
claims, write calendars, send mail, or move money.
"""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from shared.resource_capability import (
    AuthorityCeiling,
    DecisionState,
    PublicClaimCeiling,
    ResourceClass,
    ResourceOpportunity,
    ResourceValuation,
    SemanticTransactionTrace,
    TransactionPressureLedger,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_CAPABILITY_BACKFILL_FIXTURES = (
    REPO_ROOT / "config" / "resource-capability-backfill-fixtures.json"
)

REQUIRED_STALE_CONFLICT_IDS = frozenset(
    {
        "stale-conflict:stripe-refusal-vs-payment-link-wiring",
        "stale-conflict:omg-lol-pay-vaporware-vs-wired-code",
        "stale-conflict:legacy-payment-processors-vs-receive-only-doctrine",
        "stale-conflict:x402-path-a-vs-path-b-status",
    }
)

REQUIRED_RESOURCE_CLASS_PROJECTIONS = frozenset(
    {
        ResourceClass.CASH,
        ResourceClass.CREDIT,
        ResourceClass.COMPUTE,
        ResourceClass.ACCESS,
        ResourceClass.INSTITUTIONAL_SUPPORT,
        ResourceClass.TRUST_COST,
    }
)


class ResourceCapabilityBackfillError(ValueError):
    """Raised when backfill fixtures cannot be loaded safely."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BackfillSourceKind(StrEnum):
    RESOURCE_CLASS_BASELINE = "resource_class_baseline"
    SUPPORT_SURFACE_REGISTRY = "support_surface_registry"
    RECEIVE_ONLY_RAIL = "receive_only_rail"
    STALE_CONFLICT = "stale_conflict"


class ProjectionStatus(StrEnum):
    PROJECTED_PRIVATE = "projected_private"
    READ_RECEIVE_EVIDENCE = "read_receive_evidence"
    BLOCKED_STALE_CONFLICT = "blocked_stale_conflict"


class PrivacyClass(StrEnum):
    PRIVATE_PROJECTION = "private_projection"
    AGGREGATE_ONLY = "aggregate_only"
    REDACTED_EVIDENCE = "redacted_evidence"
    NO_PUBLIC_PROJECTION = "no_public_projection"


class SupportSurfaceDecision(StrEnum):
    ALLOWED = "allowed"
    GUARDED = "guarded"
    REFUSAL_CONVERSION = "refusal_conversion"


class SupportAutomationClass(StrEnum):
    AUTO = "AUTO"
    BOOTSTRAP = "BOOTSTRAP"
    GUARDED = "GUARDED"
    REFUSAL_ARTIFACT = "REFUSAL_ARTIFACT"


class ProjectionAuthorityBlock(StrictModel):
    """All authority-bearing effects stay false in this read-only slice."""

    source_mutation_authorized: Literal[False] = False
    runtime_feeder_execution_authorized: Literal[False] = False
    provider_api_execution_authorized: Literal[False] = False
    credential_lookup_authorized: Literal[False] = False
    outbound_email_authorized: Literal[False] = False
    live_calendar_write_authorized: Literal[False] = False
    payment_movement_authorized: Literal[False] = False
    public_offer_authorized: Literal[False] = False
    public_claim_upgrade_authorized: Literal[False] = False
    public_publication_authorized: Literal[False] = False
    external_action_authorized: Literal[False] = False
    value_may_drive_public_claim_or_action: Literal[False] = False


class BackfillProjectionRow(ProjectionAuthorityBlock):
    """One private projection row from a local source/evidence path."""

    row_id: str
    source_kind: BackfillSourceKind
    stable_source_id: str
    source_ref: str
    evidence_refs: list[str] = Field(min_length=1)
    projection_status: ProjectionStatus
    privacy_class: PrivacyClass
    resource_class: ResourceClass
    valuation: ResourceValuation
    decision_state: DecisionState
    authority_ceiling: AuthorityCeiling = AuthorityCeiling.NO_CLAIM
    public_claim_ceiling: PublicClaimCeiling = PublicClaimCeiling.NONE
    stale_conflict_refs: list[str] = Field(default_factory=list)
    operator_visible_reason: str

    @model_validator(mode="after")
    def _projection_stays_read_only_private(self) -> Self:
        refs = [self.source_ref, *self.evidence_refs, *self.stale_conflict_refs]
        if any(ref.startswith(("/", "~")) for ref in refs):
            raise ValueError("backfill refs must stay repo-relative or symbolic")
        if any("@" in ref for ref in refs):
            raise ValueError("backfill refs must not contain raw email addresses")

        if self.public_claim_ceiling is not PublicClaimCeiling.NONE:
            raise ValueError("backfill rows cannot raise public claim ceiling")
        if self.authority_ceiling not in {
            AuthorityCeiling.NO_CLAIM,
            AuthorityCeiling.INTERNAL_ONLY,
        }:
            raise ValueError("backfill rows cannot carry public/evidence authority")

        blocked = self.projection_status is ProjectionStatus.BLOCKED_STALE_CONFLICT
        if self.stale_conflict_refs or blocked:
            if self.decision_state is not DecisionState.BLOCKED_STALE_CONFLICT:
                raise ValueError("stale conflicts must stay blocked_stale_conflict")
            if not self.stale_conflict_refs:
                raise ValueError("blocked_stale_conflict rows require stale_conflict_refs")
        return self


class SupportSurfaceProjection(BackfillProjectionRow):
    """Private projection of one support-surface registry row."""

    source_kind: Literal[BackfillSourceKind.SUPPORT_SURFACE_REGISTRY] = (
        BackfillSourceKind.SUPPORT_SURFACE_REGISTRY
    )
    surface_id: str
    display_name: str
    surface_family: str
    money_form: str
    registry_decision: SupportSurfaceDecision
    automation_class: SupportAutomationClass
    no_perk_required: Literal[True] = True
    aggregate_only_receipts: Literal[True] = True
    readiness_gates: list[str] = Field(default_factory=list)
    refusal_brief_refs: list[str] = Field(default_factory=list)
    buildable_conversion: str | None = None
    registry_allowed_public_copy_entry_count: int = Field(ge=0)
    registry_public_copy_text_projected: Literal[False] = False

    @model_validator(mode="after")
    def _support_surface_projection_has_no_offer_authority(self) -> Self:
        if self.stable_source_id != self.surface_id:
            raise ValueError("support surface stable_source_id must equal surface_id")
        if self.registry_decision is SupportSurfaceDecision.REFUSAL_CONVERSION:
            if self.automation_class is not SupportAutomationClass.REFUSAL_ARTIFACT:
                raise ValueError("refusal conversions must stay refusal artifacts")
            if self.registry_allowed_public_copy_entry_count != 0:
                raise ValueError("refusal conversions cannot project public copy")
        return self


class ReceiveOnlyRailProjection(BackfillProjectionRow):
    """Read/receive evidence row for a local receive-only rail fact."""

    source_kind: Literal[BackfillSourceKind.RECEIVE_ONLY_RAIL] = (
        BackfillSourceKind.RECEIVE_ONLY_RAIL
    )
    rail_id: str
    module_path: str
    accepted_event_kinds: list[str] = Field(min_length=1)
    receive_only: Literal[True] = True
    outbound_fetch_authorized: Literal[False] = False
    raw_payload_persisted: Literal[False] = False
    pii_retained: Literal[False] = False
    public_surface_enabled: Literal[False] = False

    @model_validator(mode="after")
    def _receive_only_rows_stay_evidence_only(self) -> Self:
        if self.projection_status is not ProjectionStatus.READ_RECEIVE_EVIDENCE:
            raise ValueError("receive-only rail rows must be read_receive_evidence")
        if self.module_path != self.source_ref:
            raise ValueError("receive-only rail source_ref must equal module_path")
        if self.decision_state is not DecisionState.OBSERVE_ONLY:
            raise ValueError("receive-only rail rows must stay observe_only")
        return self


class StaleConflictProjection(BackfillProjectionRow):
    """Blocked row for contradictory local authority/evidence."""

    source_kind: Literal[BackfillSourceKind.STALE_CONFLICT] = BackfillSourceKind.STALE_CONFLICT
    conflict_id: str
    conflict_class: str
    contradictory_refs: list[str] = Field(min_length=2)
    required_resolution: str
    normalization_allowed_without_later_isap: Literal[False] = False
    may_activate_capability: Literal[False] = False
    projection_status: Literal[ProjectionStatus.BLOCKED_STALE_CONFLICT] = (
        ProjectionStatus.BLOCKED_STALE_CONFLICT
    )
    privacy_class: Literal[PrivacyClass.NO_PUBLIC_PROJECTION] = PrivacyClass.NO_PUBLIC_PROJECTION
    decision_state: Literal[DecisionState.BLOCKED_STALE_CONFLICT] = (
        DecisionState.BLOCKED_STALE_CONFLICT
    )

    @model_validator(mode="after")
    def _conflict_identity_is_fail_closed(self) -> Self:
        if self.stable_source_id != self.conflict_id:
            raise ValueError("stale conflict stable_source_id must equal conflict_id")
        if self.row_id != self.conflict_id:
            raise ValueError("stale conflict row_id must equal conflict_id")
        if self.conflict_id not in self.stale_conflict_refs:
            raise ValueError("stale conflict row must cite itself in stale_conflict_refs")
        return self


class ResourceCapabilityBackfillFixtureSet(StrictModel):
    """Complete private fixture set for RC-002 read-only backfill."""

    schema_version: Literal[1] = 1
    fixture_set_id: str
    authority_source: Literal["isap:resource-capability-read-only-backfill-20260508"]
    generated_from: list[str] = Field(min_length=1)
    declared_at: str
    producer: str
    consumer_permission_after: Literal["private_projection_tests_only"]
    resource_class_projection_rows: list[BackfillProjectionRow] = Field(min_length=6)
    support_surface_projections: list[SupportSurfaceProjection] = Field(min_length=1)
    receive_only_rail_projections: list[ReceiveOnlyRailProjection] = Field(min_length=1)
    stale_conflict_projections: list[StaleConflictProjection] = Field(min_length=4)
    projected_resource_opportunities: list[ResourceOpportunity] = Field(min_length=1)
    semantic_transaction_traces: list[SemanticTransactionTrace] = Field(min_length=1)
    transaction_pressure_ledgers: list[TransactionPressureLedger] = Field(min_length=1)

    def all_projection_rows(self) -> list[BackfillProjectionRow]:
        return [
            *self.resource_class_projection_rows,
            *self.support_surface_projections,
            *self.receive_only_rail_projections,
            *self.stale_conflict_projections,
        ]

    def conflict_by_id(self, conflict_id: str) -> StaleConflictProjection:
        for conflict in self.stale_conflict_projections:
            if conflict.conflict_id == conflict_id:
                return conflict
        raise KeyError(conflict_id)

    @model_validator(mode="after")
    def _validate_backfill_contract(self) -> Self:
        generated = set(self.generated_from)
        if "shared/resource_capability.py" not in generated:
            raise ValueError("backfill fixtures must cite shared/resource_capability.py")
        if "config/support-surface-registry.json" not in generated:
            raise ValueError("backfill fixtures must cite support surface registry")

        rows = self.all_projection_rows()
        row_ids = [row.row_id for row in rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("backfill row_id values must be unique")

        classes = {row.resource_class for row in self.resource_class_projection_rows}
        if not REQUIRED_RESOURCE_CLASS_PROJECTIONS.issubset(classes):
            missing = REQUIRED_RESOURCE_CLASS_PROJECTIONS - classes
            raise ValueError(f"missing required resource class projections: {sorted(missing)}")

        conflict_ids = {conflict.conflict_id for conflict in self.stale_conflict_projections}
        if not REQUIRED_STALE_CONFLICT_IDS.issubset(conflict_ids):
            missing = REQUIRED_STALE_CONFLICT_IDS - conflict_ids
            raise ValueError(f"missing required stale conflict rows: {sorted(missing)}")

        if not any(
            surface.surface_id == "stripe_payment_links"
            and surface.registry_decision is SupportSurfaceDecision.REFUSAL_CONVERSION
            for surface in self.support_surface_projections
        ):
            raise ValueError("stripe_payment_links refusal conversion must be projected")

        if not any(
            rail.rail_id == "stripe_payment_link" for rail in self.receive_only_rail_projections
        ):
            raise ValueError("stripe payment link rail fact must be projected as evidence")

        if any(row.public_offer_authorized for row in rows):
            raise ValueError("backfill rows cannot authorize public offers")

        if any(row.payment_movement_authorized for row in rows):
            raise ValueError("backfill rows cannot authorize payment movement")

        if any(trace.public_projection_allowed for trace in self.semantic_transaction_traces):
            raise ValueError("semantic transaction traces must stay private")

        if any(ledger.external_effect_authorized for ledger in self.transaction_pressure_ledgers):
            raise ValueError("transaction pressure ledgers cannot authorize external effects")

        return self


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ResourceCapabilityBackfillError(f"{path} did not contain a JSON object")
    return payload


def load_resource_capability_backfill_fixtures(
    path: Path = RESOURCE_CAPABILITY_BACKFILL_FIXTURES,
) -> ResourceCapabilityBackfillFixtureSet:
    """Load RC-002 backfill fixtures, failing closed on malformed data."""

    try:
        return ResourceCapabilityBackfillFixtureSet.model_validate(_load_json_object(path))
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise ResourceCapabilityBackfillError(
            f"invalid resource capability backfill fixtures at {path}: {exc}"
        ) from exc


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    BackfillProjectionRow._projection_stays_read_only_private,
    SupportSurfaceProjection._support_surface_projection_has_no_offer_authority,
    ReceiveOnlyRailProjection._receive_only_rows_stay_evidence_only,
    StaleConflictProjection._conflict_identity_is_fail_closed,
    ResourceCapabilityBackfillFixtureSet.all_projection_rows,
    ResourceCapabilityBackfillFixtureSet.conflict_by_id,
    ResourceCapabilityBackfillFixtureSet._validate_backfill_contract,
)


__all__ = [
    "REQUIRED_RESOURCE_CLASS_PROJECTIONS",
    "REQUIRED_STALE_CONFLICT_IDS",
    "RESOURCE_CAPABILITY_BACKFILL_FIXTURES",
    "BackfillProjectionRow",
    "BackfillSourceKind",
    "PrivacyClass",
    "ProjectionStatus",
    "ReceiveOnlyRailProjection",
    "ResourceCapabilityBackfillError",
    "ResourceCapabilityBackfillFixtureSet",
    "StaleConflictProjection",
    "SupportAutomationClass",
    "SupportSurfaceDecision",
    "SupportSurfaceProjection",
    "load_resource_capability_backfill_fixtures",
]
