"""Fail-closed dispatcher policy for capacity routing.

The evaluator in this module is intentionally pure: it does not launch lanes,
shell out, read credentials, or mutate task state. Runtime integration is
limited to building a typed request from local state and writing append-only
route decision receipts.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, model_validator

from shared.capability_surface_delta import (
    CapabilitySurfaceDelta,
    CapabilitySurfaceDeltaError,
    load_capability_surface_delta_file,
)
from shared.platform_capability_receipts import (
    DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR,
    PLATFORM_CAPABILITY_RECEIPT_DIR_ENV,
)
from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
    Effort,
    PlatformCapabilityRegistry,
    PlatformCapabilityRegistryError,
    PlatformCapabilityRoute,
    SupplyDescriptor,
    SupplyVector,
    build_supply_vector,
    check_registry_freshness,
    load_platform_capability_registry,
    normalize_route_id,
)
from shared.quota_spend_ledger import (
    QUOTA_SPEND_LEDGER_LIVE_ENV,
    PaidRouteRequest,
    QuotaSpendLedger,
    QuotaSpendLedgerError,
    build_dashboard,
    evaluate_paid_route_eligibility,
    load_quota_spend_ledger,
    load_quota_spend_ledger_resolved,
    subscription_quota_state_for_route,
)
from shared.route_metadata_schema import (
    DemandVector,
    FreshnessState,
    RouteMetadataAssessment,
    assess_route_metadata,
    build_demand_vector,
    route_envelope_gate_enforced,
    stable_payload_hash,
)

ROUTE_DECISION_SCHEMA_VERSION = 1
ROUTE_DECISION_LEDGER = "route-decisions.jsonl"
DIMENSIONAL_ROUTE_RECEIPT_SCHEMA_VERSION = 1
ROUTE_AUTHORITY_RECEIPT_SCHEMA_VERSION = 1
ROUTE_AUTHORITY_RECEIPT_DIRNAME = "route-authority"
ROUTING_MODEL_VERSION = "capacity-dimensional-v1"
CAPABILITY_SURFACE_DELTA_PATH_ENV = "HAPAX_CAPABILITY_SURFACE_DELTA_FILE"
GLOBAL_SURFACE_DELTA_ROUTE_KEY = "__all__"
PAID_CAPACITY_POOLS = frozenset({"api_paid_spend", "bootstrap_budget", "incident_override"})
UNKNOWN_OR_RISKY_PRIVACY_POSTURES = frozenset(
    {"provider_training_unknown", "public_risk", "unknown"}
)
FALLBACK_PROFILES = frozenset({"flash", "jr", "lite", "sonnet", "spark"})
AUTHORITATIVE_CEILINGS = frozenset({"authoritative"})
SUPPORT_CEILINGS = frozenset(
    {"authoritative", "frontier_review_required", "support_only", "read_only"}
)
NON_MUTATING_SURFACES = frozenset({"none"})
CLOUD_BURST_ROUTE_IDS = frozenset({"api.headless.api_frontier"})
LOCAL_DEV_PLATFORMS = frozenset({"antigrav", "claude", "codex", "vibe"})
LOCAL_DEV_TARGET = "appendix"
# GLMCP false-negative recovery is receipt-plane: create a fresh short-lived
# supported-tool admission receipt and rerun quota telemetry. There is no
# environment kill switch for stale/unknown subscription quota.
ROUTE_SPECIFIC_SUBSCRIPTION_QUOTA_REQUIRED = frozenset({"glmcp.review.direct"})


class DispatchAction(StrEnum):
    LAUNCH = "launch"
    HOLD = "hold"
    SUPPORT_ONLY = "support_only"
    REFUSE = "refuse"


class CandidateStatus(StrEnum):
    SELECTED = "selected"
    ELIGIBLE_SKIPPED = "eligible_skipped"
    VETOED = "vetoed"
    STALE = "stale"
    INCOMPARABLE = "incomparable"


class DominanceRelation(StrEnum):
    DOMINATES = "dominates"
    DOMINATED_BY_SELECTED = "dominated_by_selected"
    TIED = "tied"
    INCOMPARABLE = "incomparable"
    NOT_EVALUATED = "not_evaluated"


class ClogRouteState(StrEnum):
    POLICY_GREEN = "policy_green"
    COMPATIBILITY_DEGRADED = "compatibility_degraded"
    HELD = "held"
    REFUSED = "refused"
    SUPPORT_ONLY = "support_only"


class _PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RouteCapabilityState(_PolicyModel):
    route_id: str
    supported: bool
    route_state: str | None = None
    blocked_reasons: tuple[str, ...] = Field(default=())
    capacity_pool: str | None = None
    authority_ceiling: str | None = None
    approval_posture: str | None = None
    capability_tier: str | None = None
    worker_tier: str | None = None
    sanctioned_wrapper: str | None = None
    paid_provider: str | None = None
    paid_profile: str | None = None
    privacy_posture: str | None = None
    eligible_quality_floors: tuple[str, ...] = Field(default=())
    explicit_equivalence_records: tuple[str, ...] = Field(default=())
    excluded_task_classes: tuple[str, ...] = Field(default=())
    mutability: dict[str, bool] = Field(default_factory=dict)
    freshness_ok: bool = False
    freshness_errors: tuple[str, ...] = Field(default=())
    surface_delta_refs: tuple[str, ...] = Field(default=())
    surface_delta_blockers: tuple[str, ...] = Field(default=())
    telemetry_quota_source: str | None = None
    telemetry_resource_source: str | None = None


class QuotaSpendState(_PolicyModel):
    available: bool
    load_error: str | None = None
    budget_ledger_stale: bool | None = None
    subscription_quota_state: str | None = None
    route_subscription_quota_state: str | None = None
    paid_api_budget_state: str | None = None
    local_resource_state: str | None = None
    paid_api_route_eligible: bool | None = None
    paid_api_blocking_reasons: tuple[str, ...] = Field(default=())
    paid_route_eligibility_state: str | None = None
    paid_route_eligibility_reasons: tuple[str, ...] = Field(default=())
    route_quota_evidence_refs: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())


class DimensionalVeto(_PolicyModel):
    code: str
    field: str
    evidence_ref: str | None = None
    message: str


class DimensionalScore(_PolicyModel):
    dimension: str
    demand: int | str | bool
    supply: int | float | str | bool
    score: float
    confidence: float
    evidence_refs: tuple[str, ...] = Field(default=())


class DemandVectorRef(_PolicyModel):
    artifact_path: str
    hash: str
    freshness_state: str


class CandidateSnapshotRef(_PolicyModel):
    artifact_path: str | None = None
    hash: str


class OperatorConstraintReceipt(_PolicyModel):
    applied: tuple[str, ...] = Field(default=())
    vetoes: tuple[str, ...] = Field(default=())


class DimensionalCandidateReceipt(_PolicyModel):
    route_id: str
    platform: str
    lane_id: str | None = None
    status: CandidateStatus
    freshness_state: str
    vetoes: tuple[DimensionalVeto, ...] = Field(default=())
    dimensional_scores: tuple[DimensionalScore, ...] = Field(default=())
    aggregate_score: float | None = None
    dominance_relation: DominanceRelation = DominanceRelation.NOT_EVALUATED
    skipped_reason: str | None = None


class StaleMetadataReceipt(_PolicyModel):
    source_id: str
    field: str
    observed_at: datetime | None = None
    stale_after: str | None = None
    effect: str


class ConfidenceReceipt(_PolicyModel):
    route_confidence: int = Field(ge=0, le=5)
    reason: str


class ReviewRequirementReceipt(_PolicyModel):
    support_artifact_allowed: bool = False
    independent_review_required: bool = False
    authoritative_acceptor_profile: str | None = None


class RouteAuthorityReceipt(_PolicyModel):
    route_authority_receipt_schema: Literal[1] = ROUTE_AUTHORITY_RECEIPT_SCHEMA_VERSION
    receipt_id: str
    receipt_type: Literal[
        "opus_model_entitlement",
        "quality_equivalence",
        "runtime_actuation",
        "connector_mutation",
    ]
    route_id: str
    issued_at: datetime
    stale_after: str
    signed_by: str
    signed_payload_sha256: str
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    quality_floors: tuple[str, ...] = Field(default=())
    task_ids: tuple[str, ...] = Field(default=())
    mutation_surfaces: tuple[str, ...] = Field(default=())

    @model_validator(mode="after")
    def _valid_signed_receipt(self) -> RouteAuthorityReceipt:
        _parse_duration_spec(self.stale_after)
        if not self.signed_by.strip():
            raise ValueError("signed_by is required")
        expected = route_authority_receipt_payload_hash(self)
        if self.signed_payload_sha256 != expected:
            raise ValueError("signed payload hash mismatch")
        if self.receipt_type == "quality_equivalence" and not self.quality_floors:
            raise ValueError("quality_equivalence receipts require quality_floors")
        if self.receipt_type == "opus_model_entitlement" and not self.route_id.endswith(".opus"):
            raise ValueError("opus_model_entitlement receipts must target an opus route")
        if self.receipt_type in {"runtime_actuation", "connector_mutation"}:
            if not self.task_ids:
                raise ValueError(f"{self.receipt_type} receipts require task_ids")
            if not self.mutation_surfaces:
                raise ValueError(f"{self.receipt_type} receipts require mutation_surfaces")
        return self


class DimensionalRouteReceipt(_PolicyModel):
    dimensional_route_receipt_schema: Literal[1] = DIMENSIONAL_ROUTE_RECEIPT_SCHEMA_VERSION
    decision_id: str
    created_at: datetime
    routing_model_version: Literal["capacity-dimensional-v1"] = ROUTING_MODEL_VERSION
    task_id: str
    authority_case: str
    decision: DispatchAction
    selected_route_id: str | None = None
    degraded_mode: bool = False
    degraded_authority_ref: str | None = None
    demand_vector_ref: DemandVectorRef
    candidate_snapshot_ref: CandidateSnapshotRef
    operator_constraints: OperatorConstraintReceipt = Field(
        default_factory=OperatorConstraintReceipt
    )
    candidates: tuple[DimensionalCandidateReceipt, ...] = Field(default=())
    stale_metadata: tuple[StaleMetadataReceipt, ...] = Field(default=())
    confidence: ConfidenceReceipt
    review_requirement: ReviewRequirementReceipt = Field(default_factory=ReviewRequirementReceipt)
    downstream_review_point: str | None = None


class DispatchRequest(_PolicyModel):
    request_schema: Literal[1] = 1
    task_id: str
    lane: str
    platform: str
    mode: str
    profile: str
    route_id: str
    task_status: str | None = None
    assigned_to: str | None = None
    authority_case: str | None = None
    route_metadata_status: str
    route_metadata_hold_reasons: tuple[str, ...] = Field(default=())
    route_metadata_missing_fields: tuple[str, ...] = Field(default=())
    route_metadata_validation_errors: tuple[str, ...] = Field(default=())
    quality_floor: str | None = None
    authority_level: str | None = None
    mutation_surface: str | None = None
    mutation_scope_refs: tuple[str, ...] = Field(default=())
    operator_coupled: bool = False
    operator_coupled_evidence_refs: tuple[str, ...] = Field(default=())
    risk_flags: dict[str, bool] = Field(default_factory=dict)
    context_shape: dict[str, object] = Field(default_factory=dict)
    cloud_burst: dict[str, object] = Field(default_factory=dict)
    route_constraints: dict[str, object] = Field(default_factory=dict)
    review_requirement: dict[str, object] = Field(default_factory=dict)
    capability: RouteCapabilityState | None = None
    quota: QuotaSpendState | None = None
    demand_vector: DemandVector | None = None
    supply_vector: SupplyVector | None = None
    degraded_mode_authority_ref: str | None = None
    resource_state_refs: tuple[str, ...] = Field(default=())
    route_authority_receipts: tuple[RouteAuthorityReceipt, ...] = Field(default=())
    rollback_mode: bool = False
    legacy_route_supported: bool = False
    legacy_route_mutable: bool = False


class RouteDecision(_PolicyModel):
    decision_schema: Literal[1] = ROUTE_DECISION_SCHEMA_VERSION
    decision_id: str
    created_at: datetime
    task_id: str
    lane: str
    route_id: str
    platform: str
    mode: str
    profile: str
    action: DispatchAction
    policy_outcome: str
    launch_allowed: bool
    prompt_allowed: bool
    route_policy_green: bool = False
    clog_state: ClogRouteState = ClogRouteState.HELD
    compatibility_mode: Literal["none", "rollback_full_profile"] = "none"
    degraded_state: str | None = None
    registry_freshness_green: bool = False
    quota_freshness_green: bool = False
    resource_freshness_green: bool = False
    route_selection_authority: Literal[False] = False
    quality_floor_satisfied: bool
    authority_allowed: bool
    # advisory result metadata: the descriptor LEAF (route_id#variant_id) the launcher should run
    # for the demanded execution axes, or None when the base descriptor satisfies. The base
    # route_id stays the dispatch key; the launcher reads this to set the effort/context knob.
    selected_descriptor_leaf: str | None = None
    cloud_burst_eligible: bool = False
    cloud_burst_guard_state: str = "not_applicable"
    cloud_burst_spike_reasons: tuple[str, ...] = Field(default=())
    cloud_burst_guard_reasons: tuple[str, ...] = Field(default=())
    local_execution_target: str | None = None
    reason_codes: tuple[str, ...] = Field(default=())
    message: str
    quota_evidence_refs: tuple[str, ...] = Field(default=())
    resource_state_refs: tuple[str, ...] = Field(default=())
    _dimensional_receipt: DimensionalRouteReceipt | None = PrivateAttr(default=None)

    @property
    def dimensional_receipt(self) -> DimensionalRouteReceipt | None:
        return self._dimensional_receipt


class DispatchPolicySources(_PolicyModel):
    registry: PlatformCapabilityRegistry | None = None
    registry_error: str | None = None
    quota_ledger: QuotaSpendLedger | None = None
    quota_error: str | None = None
    quota_ledger_source: str | None = None
    quota_live_error: str | None = None
    route_authority_receipts: tuple[RouteAuthorityReceipt, ...] = Field(default=())
    surface_delta_refs_by_route: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    surface_delta_blockers_by_route: dict[str, tuple[str, ...]] = Field(default_factory=dict)


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def load_dispatch_policy_sources(
    *,
    registry_path: Path | None = None,
    quota_ledger_path: Path | None = None,
    receipt_dir: Path | None = None,
    surface_delta_path: Path | None = None,
    now: datetime | None = None,
) -> DispatchPolicySources:
    """Load inert policy sources, turning failures into request evidence."""

    registry: PlatformCapabilityRegistry | None = None
    registry_error: str | None = None
    quota_ledger: QuotaSpendLedger | None = None
    quota_error: str | None = None
    quota_ledger_source: str | None = None
    quota_live_error: str | None = None
    route_authority_receipts: tuple[RouteAuthorityReceipt, ...] = ()
    surface_delta_refs_by_route: dict[str, tuple[str, ...]] = {}
    surface_delta_blockers_by_route: dict[str, tuple[str, ...]] = {}

    try:
        effective_receipt_dir = receipt_dir or _receipt_dir_from_env()
        registry = load_platform_capability_registry(
            registry_path or PLATFORM_CAPABILITY_REGISTRY,
            receipt_dir=effective_receipt_dir,
            now=now,
        )
        if registry is not None and effective_receipt_dir is not None:
            route_authority_receipts = _load_fresh_route_authority_receipts(
                effective_receipt_dir / ROUTE_AUTHORITY_RECEIPT_DIRNAME,
                now=now,
            )
            registry = apply_route_authority_receipts(
                registry,
                receipt_dir=effective_receipt_dir,
                now=now,
            )
    except (IndexError, PlatformCapabilityRegistryError, OSError, ValueError) as exc:
        registry = None
        registry_error = str(exc)

    try:
        if quota_ledger_path is not None:
            quota_ledger = load_quota_spend_ledger(quota_ledger_path)
            quota_ledger_source = "explicit"
        else:
            resolved = load_quota_spend_ledger_resolved(
                live_path=quota_spend_ledger_live_path_from_env()
            )
            quota_ledger = resolved.ledger
            quota_ledger_source = resolved.source
            quota_live_error = resolved.live_error
    except (IndexError, QuotaSpendLedgerError, OSError, ValueError) as exc:
        quota_ledger = None
        quota_error = str(exc)

    surface_delta_file = surface_delta_path or _surface_delta_path_from_env()
    if surface_delta_file is not None:
        try:
            (
                surface_delta_refs_by_route,
                surface_delta_blockers_by_route,
            ) = _surface_delta_route_index(surface_delta_file)
        except (CapabilitySurfaceDeltaError, OSError, ValueError) as exc:
            error_ref = _surface_delta_producer_error_ref(surface_delta_file, exc)
            surface_delta_refs_by_route = {GLOBAL_SURFACE_DELTA_ROUTE_KEY: (error_ref,)}
            surface_delta_blockers_by_route = {GLOBAL_SURFACE_DELTA_ROUTE_KEY: (error_ref,)}

    return DispatchPolicySources(
        registry=registry,
        registry_error=registry_error,
        quota_ledger=quota_ledger,
        quota_error=quota_error,
        quota_ledger_source=quota_ledger_source,
        quota_live_error=quota_live_error,
        route_authority_receipts=route_authority_receipts,
        surface_delta_refs_by_route=surface_delta_refs_by_route,
        surface_delta_blockers_by_route=surface_delta_blockers_by_route,
    )


def quota_spend_ledger_live_path_from_env() -> Path | None:
    """Resolve the live quota ledger path, honoring the env override.

    Returns None to use the inert module default; the env value (when set)
    redirects the live read for tests and relocation.
    """

    configured = os.environ.get(QUOTA_SPEND_LEDGER_LIVE_ENV)
    if configured:
        return Path(configured).expanduser()
    return None


def _receipt_dir_from_env() -> Path | None:
    """Resolve the route/platform capability receipt directory for the read-path.

    Defaults to ``DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR`` when
    ``HAPAX_PLATFORM_CAPABILITY_RECEIPT_DIR`` is unset, so the live dispatch
    read-path discovers minted route-authority receipts without the env var
    being set — otherwise opus un-degrade is silently gated on an unset var.
    Set the env var to a path to override the directory, or to one of
    ``{"", "0", "none", "false"}`` (``none``/``false`` case-insensitive) to
    disable receipt loading entirely.
    """
    configured = os.environ.get(PLATFORM_CAPABILITY_RECEIPT_DIR_ENV)
    if configured is None:
        return DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR
    if configured.strip() in {"", "0", "none", "None", "false", "False"}:
        return None
    return Path(configured).expanduser()


def _surface_delta_path_from_env() -> Path | None:
    configured = os.environ.get(CAPABILITY_SURFACE_DELTA_PATH_ENV)
    if configured is None:
        return None
    if configured.strip() in {"", "0", "none", "None", "false", "False"}:
        return None
    return Path(configured).expanduser()


def _surface_delta_route_index(
    path: Path,
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
    producer_file = load_capability_surface_delta_file(path)
    descriptor_keys_by_ref: dict[str, tuple[str, ...]] = {}
    for descriptor in producer_file.descriptors:
        keys = _surface_delta_descriptor_route_keys(descriptor)
        for descriptor_ref in {
            descriptor.descriptor_ref,
            descriptor.surface_id,
            *descriptor.evidence_refs,
        }:
            descriptor_keys_by_ref[descriptor_ref] = keys
    refs: dict[str, list[str]] = {}
    blockers: dict[str, list[str]] = {}
    for delta in producer_file.deltas:
        delta_ref = _surface_delta_ref(delta)
        for key in _surface_delta_route_keys(delta, descriptor_keys_by_ref):
            refs.setdefault(key, []).append(delta_ref)
            if not delta.allows_demand_fulfillment():
                blockers.setdefault(key, []).append(delta_ref)
    return (
        {key: tuple(dict.fromkeys(values)) for key, values in refs.items()},
        {key: tuple(dict.fromkeys(values)) for key, values in blockers.items()},
    )


def _surface_delta_producer_error_ref(path: Path, exc: Exception) -> str:
    digest = hashlib.sha256(f"{path}:{exc}".encode()).hexdigest()[:16]
    return (
        f"capability_surface_delta:unknown:producer_file:{path.name}:{digest}:invalid_or_unreadable"
    )


def _surface_delta_ref(delta: CapabilitySurfaceDelta) -> str:
    return (
        f"capability_surface_delta:{delta.freshness_state.value}:"
        f"{delta.surface_id}:{delta.delta_id}"
    )


def _surface_delta_descriptor_route_keys(descriptor: Any) -> tuple[str, ...]:
    keys = {descriptor.surface_id, descriptor.descriptor_ref}
    if descriptor.surface_id.startswith("route."):
        keys.add(normalize_route_id(descriptor.surface_id.removeprefix("route.")))
    if descriptor.route_id:
        keys.add(normalize_route_id(descriptor.route_id))
    return tuple(sorted(keys))


def _surface_delta_route_keys(
    delta: CapabilitySurfaceDelta,
    descriptor_keys_by_ref: Mapping[str, Sequence[str]],
) -> tuple[str, ...]:
    keys = {delta.surface_id}
    if delta.surface_id.startswith("route."):
        keys.add(normalize_route_id(delta.surface_id.removeprefix("route.")))
    keys.update(descriptor_keys_by_ref.get(delta.surface_id, ()))
    if delta.prior_descriptor_ref:
        keys.add(delta.prior_descriptor_ref)
        keys.update(descriptor_keys_by_ref.get(delta.prior_descriptor_ref, ()))
    if delta.observed_descriptor_ref:
        keys.add(delta.observed_descriptor_ref)
        keys.update(descriptor_keys_by_ref.get(delta.observed_descriptor_ref, ()))
    return tuple(sorted(keys))


def _surface_delta_values_for_route(
    mapping: Mapping[str, Sequence[str]] | None,
    route_id: str,
) -> tuple[str, ...]:
    if not mapping:
        return ()
    route_values = tuple(mapping.get(route_id, ()))
    global_values = tuple(mapping.get(GLOBAL_SURFACE_DELTA_ROUTE_KEY, ()))
    return tuple(dict.fromkeys((*route_values, *global_values)))


def build_dispatch_request(
    *,
    task_id: str,
    lane: str,
    platform: str,
    mode: str,
    profile: str,
    task_fields: Mapping[str, Any],
    registry: PlatformCapabilityRegistry | None,
    registry_error: str | None = None,
    quota_ledger: QuotaSpendLedger | None = None,
    quota_error: str | None = None,
    route_authority_receipts: Sequence[RouteAuthorityReceipt] = (),
    surface_delta_refs_by_route: Mapping[str, Sequence[str]] | None = None,
    surface_delta_blockers_by_route: Mapping[str, Sequence[str]] | None = None,
    rollback_mode: bool = False,
    legacy_route_supported: bool = False,
    legacy_route_mutable: bool = False,
    now: datetime | None = None,
) -> DispatchRequest:
    """Build the typed request consumed by the pure policy evaluator."""

    route_id = _route_id(platform, mode, profile)
    metadata = assess_route_metadata(task_fields)
    capability = _capability_state(
        registry,
        route_id,
        registry_error,
        now=now,
        surface_delta_refs_by_route=surface_delta_refs_by_route,
        surface_delta_blockers_by_route=surface_delta_blockers_by_route,
    )
    route = registry.route_map().get(normalize_route_id(route_id)) if registry is not None else None
    try:
        demand_vector = build_demand_vector(
            {**dict(task_fields), "task_id": task_id},
            note_path=_optional_string(task_fields.get("__task_note_path")),
            observed_at=now,
            preserve_route_envelope_hold=True,
        )
    except ValueError:
        demand_vector = None
    supply_vector = build_supply_vector(route, lane_id=lane, now=now) if route is not None else None
    quota = _quota_state(
        quota_ledger,
        quota_error,
        capability=capability,
        metadata=metadata,
        task_id=task_id,
        authority_case=_optional_string(task_fields.get("authority_case")),
        now=now,
    )
    route_metadata = metadata.metadata
    operator_evidence_refs = _operator_coupled_evidence_refs(task_fields)
    operator_coupled = (
        _truthy(task_fields.get("operator_coupled"))
        or _optional_string(task_fields.get("dispatch_mode")) == "interactive_only"
        or bool(operator_evidence_refs)
    )
    return DispatchRequest(
        task_id=task_id,
        lane=lane,
        platform=platform,
        mode=mode,
        profile=profile,
        route_id=route_id,
        task_status=_optional_string(task_fields.get("status")),
        assigned_to=_optional_string(task_fields.get("assigned_to")),
        authority_case=_optional_string(task_fields.get("authority_case")),
        route_metadata_status=metadata.status.value,
        route_metadata_hold_reasons=tuple(metadata.hold_reasons),
        route_metadata_missing_fields=tuple(metadata.missing_fields),
        route_metadata_validation_errors=tuple(metadata.validation_errors),
        quality_floor=route_metadata.quality_floor.value if route_metadata else None,
        authority_level=route_metadata.authority_level.value if route_metadata else None,
        mutation_surface=route_metadata.mutation_surface.value if route_metadata else None,
        mutation_scope_refs=tuple(route_metadata.mutation_scope_refs) if route_metadata else (),
        operator_coupled=operator_coupled,
        operator_coupled_evidence_refs=operator_evidence_refs,
        risk_flags=route_metadata.risk_flags.model_dump(mode="json") if route_metadata else {},
        context_shape=route_metadata.context_shape.model_dump(mode="json")
        if route_metadata
        else {},
        cloud_burst=route_metadata.cloud_burst.model_dump(mode="json") if route_metadata else {},
        route_constraints=route_metadata.route_constraints.model_dump(mode="json")
        if route_metadata
        else {},
        review_requirement=route_metadata.review_requirement.model_dump(mode="json")
        if route_metadata
        else {},
        capability=capability,
        quota=quota,
        demand_vector=demand_vector,
        supply_vector=supply_vector,
        degraded_mode_authority_ref=_optional_string(
            task_fields.get("degraded_mode_authority_ref")
            or task_fields.get("degraded_authority_ref")
        ),
        resource_state_refs=_resource_state_refs(capability, quota),
        route_authority_receipts=tuple(route_authority_receipts),
        rollback_mode=rollback_mode,
        legacy_route_supported=legacy_route_supported,
        legacy_route_mutable=legacy_route_mutable,
    )


def evaluate_dispatch_policy(
    request: DispatchRequest,
    *,
    now: datetime | None = None,
    candidate_requests: tuple[DispatchRequest, ...] | None = None,
) -> RouteDecision:
    """Return a fail-closed route decision without side effects."""

    checked_at = now_utc() if now is None else _coerce_utc(now)
    if request.rollback_mode:
        return _decision(
            request,
            DispatchAction.HOLD,
            ("policy_rollback_retired", "signed_route_authority_receipt_required"),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    if request.route_metadata_status == "hold":
        return _decision(
            request,
            DispatchAction.HOLD,
            ("route_metadata_missing_or_incomplete", *request.route_metadata_hold_reasons),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )
    if request.route_metadata_status == "malformed":
        return _decision(
            request,
            DispatchAction.HOLD,
            ("route_metadata_malformed", *request.route_metadata_validation_errors),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    route_envelope_reasons = _route_envelope_hold_reasons(request)
    if route_envelope_reasons and route_envelope_gate_enforced():
        return _decision(
            request,
            DispatchAction.HOLD,
            route_envelope_reasons,
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    if request.operator_coupled and request.mode == "headless":
        return _decision(
            request,
            DispatchAction.REFUSE,
            (
                "operator_coupled_interactive_only",
                "interactive_path:hapax-claude --terminal tmux",
                *request.operator_coupled_evidence_refs,
            ),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    if candidate_requests is not None:
        return _evaluate_dimensional_candidate_set(
            request,
            candidate_requests=candidate_requests,
            checked_at=checked_at,
        )

    capability = request.capability
    if capability is None:
        reasons = ["capability_registry_unavailable"]
        if _requires_route_specific_subscription_quota(request.route_id):
            reasons.extend(
                [
                    "subscription_route_quota_not_fresh",
                    "route_subscription_quota_state:unknown",
                    "subscription_route_capability_missing",
                ]
            )
        return _decision(
            request,
            DispatchAction.HOLD,
            tuple(reasons),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )
    if normalize_route_id(capability.route_id) != normalize_route_id(request.route_id):
        return _decision(
            request,
            DispatchAction.REFUSE,
            (
                "capability_route_mismatch",
                f"request_route_id:{normalize_route_id(request.route_id)}",
                f"capability_route_id:{normalize_route_id(capability.route_id)}",
                *_subscription_quota_hold_reasons(request, capability),
            ),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )
    if not capability.supported:
        unsupported_reasons = ["unsupported_route"]
        unsupported_reasons.extend(_unsupported_route_subscription_quota_reasons(request))
        return _decision(
            request,
            DispatchAction.REFUSE,
            tuple(unsupported_reasons),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    cloud_action, cloud_reasons = _cloud_burst_policy_gate(request)
    if cloud_reasons:
        return _decision(
            request,
            cloud_action,
            cloud_reasons,
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    constraint_reasons = _route_constraint_reasons(request)
    if constraint_reasons:
        return _decision(
            request,
            DispatchAction.REFUSE,
            constraint_reasons,
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    if (
        _privacy_sensitive(request)
        and capability.privacy_posture in UNKNOWN_OR_RISKY_PRIVACY_POSTURES
    ):
        return _decision(
            request,
            DispatchAction.REFUSE,
            ("privacy_unknown_sensitive_route",),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    mutation_reason = _mutation_refusal_reason(request, capability, checked_at=checked_at)
    if mutation_reason:
        return _decision(
            request,
            DispatchAction.REFUSE,
            (mutation_reason,),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    paid_reasons = _paid_route_refusal_reasons(request, capability)
    if paid_reasons:
        return _decision(
            request,
            DispatchAction.REFUSE,
            paid_reasons,
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    subscription_quota_reasons = _subscription_quota_hold_reasons(request, capability)
    if subscription_quota_reasons:
        return _decision(
            request,
            DispatchAction.HOLD,
            subscription_quota_reasons,
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    freshness_reasons = _freshness_hold_reasons(capability)
    if freshness_reasons:
        return _decision(
            request,
            DispatchAction.HOLD,
            freshness_reasons,
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )

    quality_floor_satisfied = bool(
        request.quality_floor and request.quality_floor in capability.eligible_quality_floors
    )
    authority_allowed = _authority_allowed(request, capability)
    if not quality_floor_satisfied:
        return _quality_or_authority_failure_decision(
            request,
            capability,
            checked_at,
            quality_floor_satisfied=quality_floor_satisfied,
            authority_allowed=authority_allowed,
            base_reason="quality_floor_not_satisfied",
        )
    if not authority_allowed:
        return _quality_or_authority_failure_decision(
            request,
            capability,
            checked_at,
            quality_floor_satisfied=quality_floor_satisfied,
            authority_allowed=authority_allowed,
            base_reason="authority_ceiling_not_satisfied",
        )

    if (
        request.profile in FALLBACK_PROFILES
        and request.authority_level == "authoritative"
        and not capability.explicit_equivalence_records
    ):
        return _quality_or_authority_failure_decision(
            request,
            capability,
            checked_at,
            quality_floor_satisfied=quality_floor_satisfied,
            authority_allowed=authority_allowed,
            base_reason="fallback_profile_without_equivalence_record",
        )

    return _decision(
        request,
        DispatchAction.LAUNCH,
        _launch_reason_codes(request, checked_at=checked_at),
        checked_at,
        quality_floor_satisfied=quality_floor_satisfied,
        authority_allowed=authority_allowed,
    )


def write_route_decision_receipt(
    decision: RouteDecision,
    *,
    ledger_dir: Path | None = None,
) -> Path:
    target_dir = ledger_dir or Path.home() / ".cache" / "hapax" / "orchestration"
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / ROUTE_DECISION_LEDGER
    payload = decision.model_dump(mode="json")
    if decision.dimensional_receipt is not None:
        payload.update(decision.dimensional_receipt.model_dump(mode="json"))
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")
    return path


def route_decision_receipt_payload(decision: RouteDecision) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "route_decision_id": decision.decision_id,
        "route_policy_action": decision.action.value,
        "route_policy_outcome": decision.policy_outcome,
        "route_policy_reason_codes": list(decision.reason_codes),
        "route_policy_launch_allowed": decision.launch_allowed,
        "route_policy_green": decision.route_policy_green,
        "route_policy_clog_state": decision.clog_state.value,
        "route_policy_compatibility_mode": decision.compatibility_mode,
        "route_policy_degraded_state": decision.degraded_state,
        "route_policy_registry_freshness_green": decision.registry_freshness_green,
        "route_policy_quota_freshness_green": decision.quota_freshness_green,
        "route_policy_quota_evidence_refs": list(decision.quota_evidence_refs),
        "route_policy_resource_freshness_green": decision.resource_freshness_green,
        "route_policy_route_selection_authority": decision.route_selection_authority,
        "route_policy_quality_floor_satisfied": decision.quality_floor_satisfied,
        "route_policy_authority_allowed": decision.authority_allowed,
        "route_policy_cloud_burst_eligible": decision.cloud_burst_eligible,
        "route_policy_cloud_burst_guard_state": decision.cloud_burst_guard_state,
        "route_policy_cloud_burst_spike_reasons": list(decision.cloud_burst_spike_reasons),
        "route_policy_cloud_burst_guard_reasons": list(decision.cloud_burst_guard_reasons),
        "route_policy_local_execution_target": decision.local_execution_target,
    }
    if decision.dimensional_receipt is not None:
        payload.update(
            {
                "dimensional_route_receipt_schema": (
                    decision.dimensional_receipt.dimensional_route_receipt_schema
                ),
                "dimensional_selected_route_id": decision.dimensional_receipt.selected_route_id,
                "dimensional_candidate_count": len(decision.dimensional_receipt.candidates),
                "dimensional_degraded_mode": decision.dimensional_receipt.degraded_mode,
                "dimensional_evidence_refs": list(
                    _dimensional_receipt_evidence_refs(decision.dimensional_receipt)
                ),
            }
        )
    return payload


def route_authority_receipt_payload_hash(
    payload: Mapping[str, Any] | RouteAuthorityReceipt,
) -> str:
    if isinstance(payload, RouteAuthorityReceipt):
        raw = payload.model_dump(mode="json")
    else:
        raw = dict(payload)
    raw.pop("signed_payload_sha256", None)
    # These fields were added for runtime_actuation receipts after the Opus and
    # quality-equivalence receipt formats were already live. Empty defaults are
    # not part of those older signed payloads, so omit them for backward
    # compatibility while preserving non-empty runtime scope in the signature.
    for optional_empty in ("task_ids", "mutation_surfaces"):
        if not raw.get(optional_empty):
            raw.pop(optional_empty, None)
    return stable_payload_hash(raw)


def route_authority_receipt_reference(receipt: RouteAuthorityReceipt) -> str:
    route_id = normalize_route_id(receipt.route_id)
    return f"route-authority-receipt:{receipt.receipt_type}:{route_id}:{receipt.receipt_id}"


def _default_route_authority_receipt_id(
    receipt_type: str,
    route_id: str,
    issued_at: datetime,
) -> str:
    slug = normalize_route_id(route_id).replace(".", "-")
    stamp = _coerce_utc(issued_at).strftime("%Y%m%dT%H%M%SZ")
    return f"{receipt_type}-{slug}-{stamp}"


def build_route_authority_receipt(
    *,
    receipt_type: Literal[
        "opus_model_entitlement",
        "quality_equivalence",
        "runtime_actuation",
        "connector_mutation",
    ],
    route_id: str,
    evidence_refs: Sequence[str],
    receipt_id: str | None = None,
    signed_by: str = "operator",
    stale_after: str = "24h",
    quality_floors: Sequence[str] = (),
    task_ids: Sequence[str] = (),
    mutation_surfaces: Sequence[str] = (),
    issued_at: datetime | None = None,
) -> RouteAuthorityReceipt:
    """Build a signed route-authority receipt (the canonical minting path).

    Computes ``signed_payload_sha256`` over the canonical payload and returns a
    validated :class:`RouteAuthorityReceipt`. Raises if the receipt is invalid
    (e.g. an ``opus_model_entitlement`` not targeting an ``.opus`` route, or a
    ``quality_equivalence`` without ``quality_floors``) so callers fail closed.
    Backs ``scripts/hapax-mint-route-authority-receipt`` (the executable form of
    OQ-5: the operator signs the entitlement that un-degrades opus).
    """
    issued = _coerce_utc(now_utc() if issued_at is None else issued_at)
    payload: dict[str, Any] = {
        "route_authority_receipt_schema": ROUTE_AUTHORITY_RECEIPT_SCHEMA_VERSION,
        "receipt_id": receipt_id
        or _default_route_authority_receipt_id(receipt_type, route_id, issued),
        "receipt_type": receipt_type,
        "route_id": route_id,
        "issued_at": issued.isoformat().replace("+00:00", "Z"),
        "stale_after": stale_after,
        "signed_by": signed_by,
        "evidence_refs": list(evidence_refs),
        "quality_floors": list(quality_floors),
        "task_ids": list(task_ids),
        "mutation_surfaces": list(mutation_surfaces),
    }
    payload["signed_payload_sha256"] = route_authority_receipt_payload_hash(payload)
    return RouteAuthorityReceipt.model_validate(payload)


def write_route_authority_receipt(
    receipt: RouteAuthorityReceipt,
    *,
    receipt_dir: Path,
) -> Path:
    """Write a route-authority receipt to ``<receipt_dir>/route-authority/<id>.json``.

    This is the directory the dispatch read-path scans
    (:func:`apply_route_authority_receipts`); the default ``receipt_dir`` is
    ``DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR``.
    """
    target_dir = receipt_dir / ROUTE_AUTHORITY_RECEIPT_DIRNAME
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{receipt.receipt_id}.json"
    target.write_text(
        json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def apply_route_authority_receipts(
    registry: PlatformCapabilityRegistry,
    *,
    receipt_dir: Path,
    now: datetime | None = None,
) -> PlatformCapabilityRegistry:
    authority_receipts = _load_fresh_route_authority_receipts(
        receipt_dir / ROUTE_AUTHORITY_RECEIPT_DIRNAME,
        now=now,
    )
    if not authority_receipts:
        return registry

    payload = registry.model_dump(mode="json")
    routes_by_id = {route["route_id"]: route for route in payload["routes"]}
    for receipt in authority_receipts:
        if receipt.receipt_type in {"runtime_actuation", "connector_mutation"}:
            continue
        route_id = normalize_route_id(receipt.route_id)
        route_payload = routes_by_id.get(route_id)
        if route_payload is None:
            raise ValueError(
                f"route authority receipt {receipt.receipt_id!r} targets unsupported route "
                f"{route_id!r}"
            )
        _apply_route_authority_receipt_to_route_payload(route_payload, receipt)
    return PlatformCapabilityRegistry.model_validate(payload)


def _load_fresh_route_authority_receipts(
    receipt_dir: Path,
    *,
    now: datetime | None,
) -> tuple[RouteAuthorityReceipt, ...]:
    if not receipt_dir.exists():
        return ()
    checked_now = _coerce_utc(now_utc() if now is None else now)
    receipts: dict[tuple[str, ...], RouteAuthorityReceipt] = {}
    for path in sorted(receipt_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            receipt = RouteAuthorityReceipt.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
            raise ValueError(f"invalid route authority receipt at {path}: {exc}") from exc
        if not _route_authority_receipt_is_fresh(receipt, now=checked_now):
            continue
        if receipt.receipt_type in {"runtime_actuation", "connector_mutation"}:
            key = (
                normalize_route_id(receipt.route_id),
                receipt.receipt_type,
                ",".join(sorted(receipt.task_ids)),
                ",".join(sorted(receipt.mutation_surfaces)),
            )
        else:
            key = (normalize_route_id(receipt.route_id), receipt.receipt_type)
        prior = receipts.get(key)
        if prior is None or _coerce_utc(receipt.issued_at) > _coerce_utc(prior.issued_at):
            receipts[key] = receipt
    return tuple(receipts[key] for key in sorted(receipts))


def _route_authority_receipt_is_fresh(
    receipt: RouteAuthorityReceipt,
    *,
    now: datetime,
) -> bool:
    issued_at = _coerce_utc(receipt.issued_at)
    return now - issued_at <= _parse_duration_spec(receipt.stale_after)


def _apply_route_authority_receipt_to_route_payload(
    route_payload: dict[str, Any],
    receipt: RouteAuthorityReceipt,
) -> None:
    receipt_ref = route_authority_receipt_reference(receipt)
    removable_reasons = _route_authority_removable_reasons(receipt)

    top_blockers = [
        reason
        for reason in route_payload.get("blocked_reasons", [])
        if reason not in removable_reasons
    ]
    freshness = route_payload["freshness"]
    capability_evidence = freshness["evidence"]["capability"]
    capability_evidence["blocked_reasons"] = [
        reason
        for reason in capability_evidence.get("blocked_reasons", [])
        if reason not in removable_reasons
    ]
    capability_evidence["evidence_refs"] = list(
        dict.fromkeys(
            [
                *capability_evidence.get("evidence_refs", []),
                *receipt.evidence_refs,
                receipt_ref,
            ]
        )
    )
    issued_at = _coerce_utc(receipt.issued_at).isoformat().replace("+00:00", "Z")
    freshness["capability_checked_at"] = issued_at
    freshness["capability_stale_after"] = receipt.stale_after

    quality_envelope = route_payload["quality_envelope"]
    quality_envelope["explicit_equivalence_records"] = list(
        dict.fromkeys(
            [
                *quality_envelope.get("explicit_equivalence_records", []),
                receipt_ref,
            ]
        )
    )
    if receipt.receipt_type == "quality_equivalence":
        quality_envelope["eligible_quality_floors"] = list(
            dict.fromkeys(
                [
                    *quality_envelope.get("eligible_quality_floors", []),
                    *receipt.quality_floors,
                ]
            )
        )
        quality_envelope["excluded_task_classes"] = [
            item
            for item in quality_envelope.get("excluded_task_classes", [])
            if item != "frontier_required_without_equivalence_record"
        ]

    surface_blockers: list[str] = []
    for surface_payload in freshness["evidence"].values():
        surface_blockers.extend(surface_payload.get("blocked_reasons", []))
    route_payload["blocked_reasons"] = list(dict.fromkeys([*top_blockers, *surface_blockers]))
    route_payload["route_state"] = "blocked" if route_payload["blocked_reasons"] else "active"


def _route_authority_removable_reasons(receipt: RouteAuthorityReceipt) -> set[str]:
    if receipt.receipt_type == "opus_model_entitlement":
        return {"opus_model_entitlement_receipt_absent", "fresh_capability_evidence_absent"}
    if receipt.receipt_type in {"runtime_actuation", "connector_mutation"}:
        return set()
    return {"quality_equivalence_record_absent", "fresh_capability_evidence_absent"}


def _dimensional_receipt_evidence_refs(
    receipt: DimensionalRouteReceipt,
) -> tuple[str, ...]:
    refs: list[str] = []
    refs.append(receipt.demand_vector_ref.artifact_path)
    for candidate in receipt.candidates:
        for veto in candidate.vetoes:
            if veto.evidence_ref:
                refs.append(veto.evidence_ref)
        for score in candidate.dimensional_scores:
            refs.extend(score.evidence_refs)
    for item in receipt.stale_metadata:
        refs.append(item.source_id)
    return tuple(dict.fromkeys(ref for ref in refs if ref))


DIMENSION_WEIGHTS: Mapping[str, int] = {
    "grounding_governance_fit": 24,
    "implementation_architecture_fit": 20,
    "context_tools_execution_fit": 18,
    "verification_fit": 14,
    "coordination_worktree_fit": 10,
    "historical_local_calibration": 8,
    "quota_latency_scarcity": 6,
    # conditional execution-axis dimensions: present in a candidate's scores ONLY when the
    # task declares the matching demand, so _aggregate_score (which normalizes over PRESENT
    # dimensions) leaves undemanded-task scoring byte-identical. The raw sum is no longer 100;
    # _aggregate_score never assumes a constant divisor, so this is harmless.
    "effort_fit": 12,
    "context_mode_fit": 12,
    "fixed_route_overhead": 6,
}

#: The reasoning-effort ordinal ladder (none < low < ... < max), derived from the supply-side
#: Effort enum so a future reorder cannot silently mis-score; pinned by the demand drift test.
_EFFORT_LADDER: tuple[str, ...] = tuple(e.value for e in Effort)


def _evaluate_dimensional_candidate_set(
    request: DispatchRequest,
    *,
    candidate_requests: tuple[DispatchRequest, ...],
    checked_at: datetime,
) -> RouteDecision:
    candidates = _candidate_set_with_primary(request, candidate_requests)
    receipts: list[DimensionalCandidateReceipt] = []
    eligible: list[DimensionalCandidateReceipt] = []
    incomparable_present = False

    for candidate in candidates:
        gate = evaluate_dispatch_policy(candidate, now=checked_at)
        candidate_receipt = _candidate_receipt(candidate, gate, checked_at=checked_at)
        if candidate_receipt.status is CandidateStatus.ELIGIBLE_SKIPPED:
            if candidate_receipt.aggregate_score is None or _low_confidence(candidate_receipt):
                candidate_receipt = candidate_receipt.model_copy(
                    update={
                        "status": CandidateStatus.INCOMPARABLE,
                        "dominance_relation": DominanceRelation.INCOMPARABLE,
                        "skipped_reason": "low_confidence_or_missing_dimensional_score",
                    }
                )
                incomparable_present = True
            else:
                eligible.append(candidate_receipt)
        elif candidate_receipt.status is CandidateStatus.INCOMPARABLE:
            incomparable_present = True
        receipts.append(candidate_receipt)

    if not eligible:
        reason = (
            "dimensional_candidates_incomparable_hold"
            if incomparable_present
            else "no_eligible_dimensional_candidates"
        )
        return _decision(
            request,
            DispatchAction.HOLD,
            (reason,),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
            dimensional_candidates=tuple(receipts),
        )

    best_score = max(candidate.aggregate_score or 0.0 for candidate in eligible)
    tied = [
        candidate
        for candidate in eligible
        if candidate.aggregate_score is not None
        and abs(candidate.aggregate_score - best_score) < 0.000001
    ]
    primary_receipt = next(
        (candidate for candidate in eligible if candidate.route_id == request.route_id),
        None,
    )

    if len(tied) > 1 or incomparable_present:
        if request.degraded_mode_authority_ref and primary_receipt is not None:
            updated = _mark_candidate_relations(
                receipts,
                selected_route_id=request.route_id,
                tied_route_ids={candidate.route_id for candidate in tied},
            )
            return _decision(
                request,
                DispatchAction.LAUNCH,
                ("degraded_mode_authorized_dimensional_tie_break",),
                checked_at,
                quality_floor_satisfied=True,
                authority_allowed=True,
                dimensional_candidates=updated,
                selected_route_id=request.route_id,
                degraded_mode=True,
                degraded_authority_ref=request.degraded_mode_authority_ref,
            )
        reason = (
            "dimensional_candidates_incomparable_hold"
            if incomparable_present
            else "dimensional_candidate_tie_hold"
        )
        updated = _mark_candidate_relations(
            receipts,
            selected_route_id=None,
            tied_route_ids={candidate.route_id for candidate in tied},
        )
        return _decision(
            request,
            DispatchAction.HOLD,
            (reason,),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
            dimensional_candidates=updated,
        )

    winner = tied[0]
    updated = _mark_candidate_relations(receipts, selected_route_id=winner.route_id)
    if winner.route_id != request.route_id:
        return _decision(
            request,
            DispatchAction.HOLD,
            (
                "requested_route_dominated_by_higher_scoring_candidate",
                f"selected_candidate:{winner.route_id}",
            ),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
            dimensional_candidates=updated,
            selected_route_id=winner.route_id,
        )

    return _decision(
        request,
        DispatchAction.LAUNCH,
        ("dimensional_unique_dominant_route",),
        checked_at,
        quality_floor_satisfied=True,
        authority_allowed=True,
        dimensional_candidates=updated,
        selected_route_id=winner.route_id,
    )


def _candidate_set_with_primary(
    request: DispatchRequest, candidates: tuple[DispatchRequest, ...]
) -> tuple[DispatchRequest, ...]:
    by_route = {request.route_id: request}
    for candidate in candidates:
        if candidate.route_id != request.route_id:
            by_route[candidate.route_id] = candidate
    return tuple(by_route[route_id] for route_id in sorted(by_route))


def _candidate_receipt(
    request: DispatchRequest,
    gate: RouteDecision,
    *,
    checked_at: datetime,
) -> DimensionalCandidateReceipt:
    vetoes = list(_policy_vetoes(gate))
    vetoes.extend(_dimensional_vetoes(request, checked_at=checked_at))
    stale_metadata = _stale_supply_metadata(request, checked_at=checked_at)
    if stale_metadata:
        vetoes.extend(
            DimensionalVeto(
                code="stale_supply_field",
                field=item.field,
                evidence_ref=item.source_id,
                message=f"{item.field} is stale or missing",
            )
            for item in stale_metadata
            if item.effect == "veto"
        )
    scores = _score_candidate(request)
    aggregate = _aggregate_score(scores)

    if vetoes:
        status = (
            CandidateStatus.STALE
            if any(veto.code == "stale_supply_field" for veto in vetoes)
            else CandidateStatus.VETOED
        )
        return DimensionalCandidateReceipt(
            route_id=request.route_id,
            platform=request.platform,
            lane_id=request.lane,
            status=status,
            freshness_state=FreshnessState.STALE.value
            if status is CandidateStatus.STALE
            else _candidate_freshness_state(request),
            vetoes=tuple(vetoes),
            dimensional_scores=scores,
            aggregate_score=None,
            dominance_relation=DominanceRelation.NOT_EVALUATED,
            skipped_reason="; ".join(veto.code for veto in vetoes),
        )

    return DimensionalCandidateReceipt(
        route_id=request.route_id,
        platform=request.platform,
        lane_id=request.lane,
        status=CandidateStatus.ELIGIBLE_SKIPPED,
        freshness_state=FreshnessState.FRESH.value,
        dimensional_scores=scores,
        aggregate_score=aggregate,
        dominance_relation=DominanceRelation.NOT_EVALUATED,
    )


def _policy_vetoes(gate: RouteDecision) -> tuple[DimensionalVeto, ...]:
    if gate.action is DispatchAction.LAUNCH:
        return ()
    return tuple(
        DimensionalVeto(
            code=f"policy_{gate.action.value}",
            field="dispatch_policy",
            evidence_ref=gate.decision_id,
            message=reason,
        )
        for reason in gate.reason_codes
    )


def _route_envelope_hold_reasons(request: DispatchRequest) -> tuple[str, ...]:
    demand = request.demand_vector
    if demand is None:
        return ("missing_demand_vector", "route_envelope_missing")
    admission = demand.route_envelope.admission
    action = admission.admission_action.value
    if action == "route":
        return ()
    return tuple(
        dict.fromkeys(
            [
                f"route_envelope_admission_{action}",
                *admission.reason_codes,
            ]
        )
    )


def _dimensional_vetoes(
    request: DispatchRequest,
    *,
    checked_at: datetime,
) -> tuple[DimensionalVeto, ...]:
    demand = request.demand_vector
    supply = request.supply_vector
    vetoes: list[DimensionalVeto] = []
    if demand is None:
        vetoes.append(
            DimensionalVeto(
                code="missing_demand_vector",
                field="demand_vector",
                message="candidate cannot be scored without a demand vector",
            )
        )
    if supply is None:
        vetoes.append(
            DimensionalVeto(
                code="missing_supply_vector",
                field="supply_vector",
                message="candidate cannot be scored without a supply vector",
            )
        )
        return tuple(vetoes)
    if not supply.operator_constraints.allowed:
        vetoes.append(
            DimensionalVeto(
                code="operator_constraint_veto",
                field="operator_constraints.allowed",
                message="operator constraints mark route as disallowed",
            )
        )
    if demand is None:
        return tuple(vetoes)

    tool_by_id = {tool.tool_id: tool for tool in supply.tool_state}
    for required_tool in demand.task_demand.required_tools:
        if not required_tool.required:
            continue
        tool = tool_by_id.get(required_tool.tool_id)
        if tool is None or not tool.available:
            vetoes.append(
                DimensionalVeto(
                    code="required_tool_unavailable",
                    field=f"tool_state.{required_tool.tool_id}",
                    message=f"required tool {required_tool.tool_id} is unavailable",
                )
            )
            continue
        if required_tool.authority_use not in tool.authority_use:
            vetoes.append(
                DimensionalVeto(
                    code="required_tool_authority_mismatch",
                    field=f"tool_state.{required_tool.tool_id}.authority_use",
                    evidence_ref=tool.evidence_ref,
                    message=(
                        f"required tool {required_tool.tool_id} lacks "
                        f"{required_tool.authority_use.value} authority"
                    ),
                )
            )

    if demand.task_demand.execution_environment.required:
        for surface in demand.task_demand.execution_environment.surfaces:
            if not getattr(supply.execution_access, surface.value, False):
                vetoes.append(
                    DimensionalVeto(
                        code="required_execution_surface_unavailable",
                        field=f"execution_access.{surface.value}",
                        message=f"required execution surface {surface.value} is unavailable",
                    )
                )

    if (
        request.mutation_surface
        and request.mutation_surface not in supply.authority.supported_mutation_surfaces
        and not (
            request.mutation_surface == "runtime"
            and _runtime_actuation_refusal_reason(request, checked_at=checked_at) is None
        )
    ):
        vetoes.append(
            DimensionalVeto(
                code="mutation_surface_mismatch",
                field="authority.supported_mutation_surfaces",
                message=f"route does not support mutation surface {request.mutation_surface}",
            )
        )
    return tuple(vetoes)


def _stale_supply_metadata(
    request: DispatchRequest,
    *,
    checked_at: datetime,
) -> tuple[StaleMetadataReceipt, ...]:
    supply = request.supply_vector
    if supply is None:
        return ()
    stale: list[StaleMetadataReceipt] = []
    for dimension, score in supply.capability_scores.model_dump().items():
        observed_at = score.get("observed_at")
        stale_after = score.get("stale_after")
        if observed_at is None:
            stale.append(
                StaleMetadataReceipt(
                    source_id=request.route_id,
                    field=f"capability_scores.{dimension}.observed_at",
                    stale_after=str(stale_after) if stale_after else None,
                    effect="veto",
                )
            )
            continue
        checked = (
            observed_at
            if isinstance(observed_at, datetime)
            else datetime.fromisoformat(str(observed_at))
        )
        if _is_stale(checked, str(stale_after), checked_at):
            stale.append(
                StaleMetadataReceipt(
                    source_id=request.route_id,
                    field=f"capability_scores.{dimension}",
                    observed_at=_coerce_utc(checked),
                    stale_after=str(stale_after),
                    effect="veto",
                )
            )
    for tool in supply.tool_state:
        if tool.observed_at is None:
            stale.append(
                StaleMetadataReceipt(
                    source_id=request.route_id,
                    field=f"tool_state.{tool.tool_id}.observed_at",
                    stale_after=tool.stale_after,
                    effect="veto",
                )
            )
            continue
        if _is_stale(tool.observed_at, tool.stale_after, checked_at):
            stale.append(
                StaleMetadataReceipt(
                    source_id=request.route_id,
                    field=f"tool_state.{tool.tool_id}",
                    observed_at=_coerce_utc(tool.observed_at),
                    stale_after=tool.stale_after,
                    effect="veto",
                )
            )
    return tuple(stale)


def _score_candidate(request: DispatchRequest) -> tuple[DimensionalScore, ...]:
    demand = request.demand_vector
    supply = request.supply_vector
    if demand is None or supply is None:
        return ()
    scores = supply.capability_scores
    legacy: tuple[DimensionalScore, ...] = (
        _dimension_score(
            "grounding_governance_fit",
            demand.task_demand.grounding_criticality,
            [
                scores.grounding,
                scores.governance_reasoning,
                scores.privacy_safety,
                scores.public_claim_safety,
            ],
        ),
        _dimension_score(
            "implementation_architecture_fit",
            demand.task_demand.implementation_complexity,
            [scores.source_editing, scores.architecture, scores.ambiguity_resolution],
        ),
        _dimension_score(
            "context_tools_execution_fit",
            demand.task_demand.estimated_context_tokens,
            [scores.long_context, scores.current_docs_grounding, scores.runtime_debugging],
        ),
        _dimension_score(
            "verification_fit",
            bool(demand.task_demand.verification_demand.deterministic_tests),
            [scores.test_authoring, scores.multimodal_verification],
        ),
        _dimension_score(
            "coordination_worktree_fit",
            demand.task_demand.coordination_load,
            [scores.coordination_reliability],
        ),
        _dimension_score(
            "historical_local_calibration",
            demand.task_demand.failure_cost,
            [scores.local_calibration],
        ),
        DimensionalScore(
            dimension="quota_latency_scarcity",
            demand=demand.priority_context.urgency.value,
            supply=supply.state.quota_state,
            score=5.0
            if supply.state.quota_state in {"available", "low"}
            and supply.state.resource_pressure in {"green", "yellow"}
            else 2.0,
            confidence=3.0 if supply.state.quota_state != "unknown" else 1.0,
            evidence_refs=tuple(supply.freshness.source_refs),
        ),
    )
    return legacy + _capability_fit_scores(request)


def _capability_fit_scores(request: DispatchRequest) -> tuple[DimensionalScore, ...]:
    """The conditional execution-axis dimensions. Each is emitted ONLY when the task declares
    the matching demand (and 'standard'/'not_applicable' context-mode is treated as no demand —
    every base satisfies it). Omitting the dimension when undemanded is THE non-perturbation
    lever: _aggregate_score normalizes over present dimensions, so an undemanded task scores
    byte-identically to pre-change. Fails CLOSED: a present demand with no supply_descriptor
    (a route that cannot describe its execution axes) omits the dimension rather than crashing."""

    demand = request.demand_vector
    supply = request.supply_vector
    if demand is None or supply is None or supply.supply_descriptor is None:
        return ()
    descriptor = supply.supply_descriptor
    task_demand = demand.task_demand
    fits: list[DimensionalScore] = []

    context_mode_demand = task_demand.context_mode_demand
    if context_mode_demand is not None and context_mode_demand not in {
        "standard",
        "not_applicable",
    }:
        satisfied = context_mode_demand in descriptor.reachable_context_modes
        fits.append(
            DimensionalScore(
                dimension="context_mode_fit",
                demand=context_mode_demand,
                supply=";".join(descriptor.reachable_context_modes),
                score=5.0 if satisfied else 1.0,
                confidence=3.0,
            )
        )

    effort_demand = task_demand.effort_demand
    if effort_demand is not None:
        fits.append(
            DimensionalScore(
                dimension="effort_fit",
                demand=effort_demand,
                supply=";".join(descriptor.reachable_efforts),
                score=_effort_fit_score(effort_demand, descriptor.reachable_efforts),
                confidence=3.0,
            )
        )

    if task_demand.fixed_route_overhead_sensitivity > 0:
        overhead = supply.historical_performance.fixed_route_overhead
        fits.append(
            DimensionalScore(
                dimension="fixed_route_overhead",
                demand=task_demand.fixed_route_overhead_sensitivity,
                supply=overhead.fixed_cost_score,
                score=_fixed_route_overhead_fit_score(
                    overhead.fixed_cost_score,
                    task_demand.fixed_route_overhead_sensitivity,
                ),
                confidence=3.0 if overhead.evidence_refs else 1.0,
                evidence_refs=tuple(overhead.evidence_refs),
            )
        )

    return tuple(fits)


def _fixed_route_overhead_fit_score(overhead_score: int, sensitivity: int) -> float:
    """Bounded setup-cost penalty: fixed overhead can affect a demanded route, not dominate it."""

    bounded_overhead = max(0, min(5, overhead_score))
    bounded_sensitivity = max(0, min(5, sensitivity))
    if bounded_sensitivity == 0:
        return 5.0
    penalty = min(4.0, (bounded_overhead * bounded_sensitivity) / 5.0)
    return round(max(1.0, 5.0 - penalty), 4)


def _effort_fit_score(effort_demand: str, reachable_efforts: tuple[str, ...]) -> float:
    """Meet-or-exceed ladder: the route's STRONGEST reachable effort vs the demand. Meets or
    exceeds -> 5.0; exactly one rung short -> 3.0; further short or unknown -> 1.0 (fail-closed).
    Downward cost discrimination (a 'low' demand preferring the cheap leaf) is done by the leaf
    RESOLVER, not this score, per the design's meet-or-exceed semantics."""

    if effort_demand not in _EFFORT_LADDER:
        return 1.0
    demand_index = _EFFORT_LADDER.index(effort_demand)
    reachable_indexes = [
        _EFFORT_LADDER.index(effort) for effort in reachable_efforts if effort in _EFFORT_LADDER
    ]
    if not reachable_indexes:
        return 1.0
    best = max(reachable_indexes)
    if best >= demand_index:
        return 5.0
    if best == demand_index - 1:
        return 3.0
    return 1.0


def _resolve_descriptor_leaf(request: DispatchRequest) -> str | None:
    """Resolve the descriptor LEAF a launching route should run for the demanded axes:
    ``route_id#variant_id`` when a variant is needed, or ``None`` when the base descriptor
    already satisfies (or nothing is demanded). Reads the SAME supply_descriptor the
    satisfiability score read, so score and resolution cannot diverge. context_mode takes
    precedence (exact-match material axis); effort resolves the CHEAPEST reachable leaf that
    meets-or-exceeds the demand (so 'low' picks an effort_low variant over a frontier base)."""

    demand = request.demand_vector
    supply = request.supply_vector
    if demand is None or supply is None or supply.supply_descriptor is None:
        return None
    descriptor = supply.supply_descriptor
    task_demand = demand.task_demand

    context_mode_demand = task_demand.context_mode_demand
    if (
        context_mode_demand is not None
        and context_mode_demand not in {"standard", "not_applicable"}
        and context_mode_demand in descriptor.context_mode_to_variant
    ):
        variant_id = descriptor.context_mode_to_variant[context_mode_demand]
        if variant_id is not None:
            return f"{request.route_id}#{variant_id}"
        return None

    effort_demand = task_demand.effort_demand
    if effort_demand is not None and effort_demand in _EFFORT_LADDER:
        variant_id = _resolve_effort_leaf(descriptor, effort_demand)
        if variant_id is not None:
            return f"{request.route_id}#{variant_id}"
    return None


def _resolve_effort_leaf(descriptor: SupplyDescriptor, effort_demand: str) -> str | None:
    """The CHEAPEST reachable leaf (lowest effort) that still meets-or-exceeds the demand;
    its variant_id, or None when the base descriptor is the cheapest satisfying leaf."""

    demand_index = _EFFORT_LADDER.index(effort_demand)
    meeting = [
        effort
        for effort in descriptor.reachable_efforts
        if effort in _EFFORT_LADDER and _EFFORT_LADDER.index(effort) >= demand_index
    ]
    if not meeting:
        return None
    cheapest = min(meeting, key=_EFFORT_LADDER.index)
    return descriptor.effort_to_variant.get(cheapest)


def _dimension_score(
    dimension: str,
    demand: int | str | bool,
    supplies: list[Any],
) -> DimensionalScore:
    score = sum(float(item.score) for item in supplies) / max(len(supplies), 1)
    confidence = sum(float(item.confidence) for item in supplies) / max(len(supplies), 1)
    evidence_refs: list[str] = []
    for item in supplies:
        evidence_refs.extend(item.evidence_refs)
    return DimensionalScore(
        dimension=dimension,
        demand=demand,
        supply=round(score, 4),
        score=round(score, 4),
        confidence=round(confidence, 4),
        evidence_refs=tuple(evidence_refs),
    )


def _aggregate_score(scores: tuple[DimensionalScore, ...]) -> float | None:
    if not scores:
        return None
    weighted = 0.0
    total_weight = 0
    by_dimension = {score.dimension: score for score in scores}
    for dimension, weight in DIMENSION_WEIGHTS.items():
        score = by_dimension.get(dimension)
        if score is None:
            continue
        weighted += score.score * weight
        total_weight += weight
    return round(weighted / total_weight, 6) if total_weight else None


def _low_confidence(candidate: DimensionalCandidateReceipt) -> bool:
    return any(score.confidence < 2.0 for score in candidate.dimensional_scores)


def _mark_candidate_relations(
    receipts: list[DimensionalCandidateReceipt],
    *,
    selected_route_id: str | None,
    tied_route_ids: set[str] | None = None,
) -> tuple[DimensionalCandidateReceipt, ...]:
    tied_route_ids = tied_route_ids or set()
    updated: list[DimensionalCandidateReceipt] = []
    for candidate in receipts:
        if candidate.status in {CandidateStatus.VETOED, CandidateStatus.STALE}:
            updated.append(candidate)
            continue
        if selected_route_id and candidate.route_id == selected_route_id:
            updated.append(
                candidate.model_copy(
                    update={
                        "status": CandidateStatus.SELECTED,
                        "dominance_relation": DominanceRelation.DOMINATES,
                    }
                )
            )
        elif candidate.route_id in tied_route_ids:
            updated.append(
                candidate.model_copy(update={"dominance_relation": DominanceRelation.TIED})
            )
        elif selected_route_id:
            updated.append(
                candidate.model_copy(
                    update={"dominance_relation": DominanceRelation.DOMINATED_BY_SELECTED}
                )
            )
        else:
            updated.append(
                candidate.model_copy(update={"dominance_relation": DominanceRelation.INCOMPARABLE})
            )
    return tuple(updated)


def _build_dimensional_route_receipt(
    decision: RouteDecision,
    request: DispatchRequest,
    *,
    dimensional_candidates: tuple[DimensionalCandidateReceipt, ...] | None = None,
    selected_route_id: str | None = None,
    degraded_mode: bool = False,
    degraded_authority_ref: str | None = None,
) -> DimensionalRouteReceipt:
    candidates = dimensional_candidates or (_single_candidate_receipt(request, decision),)
    snapshot_hash = stable_payload_hash(
        {
            "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
            "selected_route_id": selected_route_id
            or (request.route_id if decision.launch_allowed else None),
        }
    )
    stale_metadata = tuple(_receipt_stale_metadata(candidate) for candidate in candidates)
    flattened_stale = tuple(item for group in stale_metadata for item in group)
    return DimensionalRouteReceipt(
        decision_id=decision.decision_id,
        created_at=decision.created_at,
        task_id=request.task_id,
        authority_case=request.authority_case or "unknown",
        decision=decision.action,
        selected_route_id=selected_route_id
        or (request.route_id if decision.launch_allowed else None),
        degraded_mode=degraded_mode,
        degraded_authority_ref=degraded_authority_ref,
        demand_vector_ref=_demand_vector_ref(request),
        candidate_snapshot_ref=CandidateSnapshotRef(hash=snapshot_hash),
        operator_constraints=_operator_constraint_receipt(request),
        candidates=candidates,
        stale_metadata=flattened_stale,
        confidence=_confidence_receipt(candidates, decision),
        review_requirement=ReviewRequirementReceipt.model_validate(
            request.review_requirement or {}
        ),
        downstream_review_point=_downstream_review_point(request, decision),
    )


def _single_candidate_receipt(
    request: DispatchRequest, decision: RouteDecision
) -> DimensionalCandidateReceipt:
    scores = _score_candidate(request)
    vetoes = tuple(
        DimensionalVeto(
            code=reason,
            field="dispatch_policy",
            evidence_ref=decision.decision_id,
            message=reason,
        )
        for reason in decision.reason_codes
        if decision.action is not DispatchAction.LAUNCH
    )
    return DimensionalCandidateReceipt(
        route_id=request.route_id,
        platform=request.platform,
        lane_id=request.lane,
        status=CandidateStatus.SELECTED if decision.launch_allowed else CandidateStatus.VETOED,
        freshness_state=_candidate_freshness_state(request),
        vetoes=vetoes,
        dimensional_scores=scores,
        aggregate_score=_aggregate_score(scores) if decision.launch_allowed else None,
        dominance_relation=DominanceRelation.DOMINATES
        if decision.launch_allowed
        else DominanceRelation.NOT_EVALUATED,
        skipped_reason=None if decision.launch_allowed else decision.message,
    )


def _demand_vector_ref(request: DispatchRequest) -> DemandVectorRef:
    demand = request.demand_vector
    if demand is None:
        return DemandVectorRef(
            artifact_path=request.task_id,
            hash=stable_payload_hash(
                {
                    "task_id": request.task_id,
                    "route_id": request.route_id,
                    "route_metadata_status": request.route_metadata_status,
                }
            ),
            freshness_state=FreshnessState.MISSING.value,
        )
    return DemandVectorRef(
        artifact_path=demand.work_item.note_path or demand.work_item.task_id,
        hash=demand.work_item.frontmatter_hash,
        freshness_state=FreshnessState.FRESH.value,
    )


def _operator_constraint_receipt(request: DispatchRequest) -> OperatorConstraintReceipt:
    applied: list[str] = []
    vetoes: list[str] = []
    constraints = request.route_constraints
    for field in ("preferred_platforms", "allowed_platforms", "prohibited_platforms"):
        values = constraints.get(field)
        if values:
            applied.append(f"{field}:{values}")
    if request.supply_vector is not None:
        vetoes.extend(request.supply_vector.operator_constraints.vetoes)
        applied.extend(request.supply_vector.operator_constraints.preferences)
    return OperatorConstraintReceipt(applied=tuple(applied), vetoes=tuple(vetoes))


def _confidence_receipt(
    candidates: tuple[DimensionalCandidateReceipt, ...], decision: RouteDecision
) -> ConfidenceReceipt:
    selected = next(
        (candidate for candidate in candidates if candidate.status is CandidateStatus.SELECTED),
        None,
    )
    if selected and selected.dimensional_scores:
        confidence = int(
            min(5, max(0, round(min(score.confidence for score in selected.dimensional_scores))))
        )
        return ConfidenceReceipt(
            route_confidence=confidence, reason="selected_route_score_confidence"
        )
    if decision.launch_allowed:
        return ConfidenceReceipt(route_confidence=2, reason="legacy_policy_launch_without_scores")
    return ConfidenceReceipt(route_confidence=0, reason="route_not_selected")


def _receipt_stale_metadata(
    candidate: DimensionalCandidateReceipt,
) -> tuple[StaleMetadataReceipt, ...]:
    return tuple(
        StaleMetadataReceipt(
            source_id=veto.evidence_ref or candidate.route_id,
            field=veto.field,
            effect="veto",
        )
        for veto in candidate.vetoes
        if veto.code in {"stale_supply_field", "capability_data_stale_or_unknown"}
    )


def _downstream_review_point(request: DispatchRequest, decision: RouteDecision) -> str | None:
    if decision.action is DispatchAction.SUPPORT_ONLY:
        acceptor = request.review_requirement.get("authoritative_acceptor_profile")
        return (
            f"authoritative_acceptor:{acceptor}" if acceptor else "authoritative_acceptor_required"
        )
    return None


def _candidate_freshness_state(request: DispatchRequest) -> str:
    capability = request.capability
    if capability is not None and (
        not capability.freshness_ok or capability.surface_delta_blockers
    ):
        return FreshnessState.STALE.value
    if request.supply_vector is None:
        return FreshnessState.MISSING.value
    return FreshnessState.FRESH.value


def _is_stale(observed_at: datetime, stale_after: str, now: datetime) -> bool:
    return now - _coerce_utc(observed_at) > _parse_duration_spec(stale_after)


def _parse_duration_spec(spec: str) -> timedelta:
    count = int(spec[:-1])
    unit = spec[-1]
    if unit == "s":
        return timedelta(seconds=count)
    if unit == "m":
        return timedelta(minutes=count)
    if unit == "h":
        return timedelta(hours=count)
    if unit == "d":
        return timedelta(days=count)
    raise ValueError(f"invalid duration spec {spec!r}")


def _capability_state(
    registry: PlatformCapabilityRegistry | None,
    route_id: str,
    registry_error: str | None,
    *,
    now: datetime | None,
    surface_delta_refs_by_route: Mapping[str, Sequence[str]] | None = None,
    surface_delta_blockers_by_route: Mapping[str, Sequence[str]] | None = None,
) -> RouteCapabilityState | None:
    if registry is None:
        return None

    route = registry.route_map().get(normalize_route_id(route_id))
    if route is None:
        return RouteCapabilityState(
            route_id=normalize_route_id(route_id),
            supported=False,
            freshness_errors=(f"unsupported route: {normalize_route_id(route_id)}",),
        )
    freshness = check_registry_freshness(registry, route_ids=[route_id], now=now).routes[0]
    normalized_route_id = normalize_route_id(route_id)
    return _route_capability_state(
        route,
        freshness.ok,
        freshness.errors,
        surface_delta_refs=_surface_delta_values_for_route(
            surface_delta_refs_by_route,
            normalized_route_id,
        ),
        surface_delta_blockers=_surface_delta_values_for_route(
            surface_delta_blockers_by_route,
            normalized_route_id,
        ),
    )


def _route_capability_state(
    route: PlatformCapabilityRoute,
    freshness_ok: bool,
    freshness_errors: tuple[str, ...],
    *,
    surface_delta_refs: tuple[str, ...] = (),
    surface_delta_blockers: tuple[str, ...] = (),
) -> RouteCapabilityState:
    return RouteCapabilityState(
        route_id=route.route_id,
        supported=True,
        route_state=route.route_state.value,
        blocked_reasons=tuple(route.blocked_reasons),
        capacity_pool=route.capacity_pool.value,
        authority_ceiling=route.authority_ceiling.value,
        approval_posture=route.approval_posture.value,
        capability_tier=route.capability_tier.value,
        worker_tier=route.worker_tier.value,
        sanctioned_wrapper=route.sanctioned_wrapper,
        paid_provider=route.paid_provider,
        paid_profile=route.paid_profile,
        privacy_posture=route.privacy_posture.value,
        eligible_quality_floors=tuple(
            quality_floor.value for quality_floor in route.quality_envelope.eligible_quality_floors
        ),
        explicit_equivalence_records=tuple(route.quality_envelope.explicit_equivalence_records),
        excluded_task_classes=tuple(route.quality_envelope.excluded_task_classes),
        mutability=route.mutability.model_dump(mode="json"),
        freshness_ok=freshness_ok,
        freshness_errors=freshness_errors,
        surface_delta_refs=surface_delta_refs,
        surface_delta_blockers=surface_delta_blockers,
        telemetry_quota_source=route.telemetry.quota_source.value,
        telemetry_resource_source=route.telemetry.resource_source.value,
    )


def _quota_state(
    quota_ledger: QuotaSpendLedger | None,
    quota_error: str | None,
    *,
    capability: RouteCapabilityState | None,
    metadata: RouteMetadataAssessment,
    task_id: str,
    authority_case: str | None,
    now: datetime | None,
) -> QuotaSpendState | None:
    if quota_ledger is None:
        if quota_error:
            return QuotaSpendState(available=False, load_error=quota_error)
        return None

    checked_at = now_utc() if now is None else _coerce_utc(now)
    dashboard = build_dashboard(quota_ledger, now=checked_at)
    eligibility_state: str | None = None
    eligibility_reasons: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    route_subscription_state: str | None = None
    route_quota_evidence_refs: tuple[str, ...] = ()
    if capability is not None and (
        capability.capacity_pool == "subscription_quota"
        or _requires_route_specific_subscription_quota(capability.route_id)
    ):
        state, refs = subscription_quota_state_for_route(
            quota_ledger,
            capability.route_id,
            now=checked_at,
        )
        missing_ref = f"quota-snapshot:{normalize_route_id(capability.route_id)}:missing"
        if refs != (missing_ref,) or _requires_route_specific_subscription_quota(
            capability.route_id
        ):
            route_subscription_state = state.value
            route_quota_evidence_refs = refs
    if capability is not None and capability.capacity_pool in PAID_CAPACITY_POOLS:
        request = PaidRouteRequest(
            route_id=capability.route_id,
            provider=_paid_provider_for(capability),
            profile=capability.paid_profile or _profile_from_route_id(capability.route_id),
            task_class=_task_class_for(metadata),
            quality_floor=metadata.metadata.quality_floor.value
            if metadata.metadata is not None
            else "unknown",
            estimated_cost_usd=Decimal("1.00"),
            capacity_pool=capability.capacity_pool,
        )
        eligibility = evaluate_paid_route_eligibility(quota_ledger, request, now=checked_at)
        eligibility_state = eligibility.state
        eligibility_reasons = tuple(eligibility.blocking_reasons)
        evidence_refs = tuple(eligibility.evidence_refs)

    return QuotaSpendState(
        available=True,
        budget_ledger_stale=dashboard.budget_ledger_stale,
        subscription_quota_state=dashboard.subscription_quota_state.value,
        route_subscription_quota_state=route_subscription_state,
        paid_api_budget_state=dashboard.paid_api_budget_state.value,
        local_resource_state=dashboard.local_resource_state.value,
        paid_api_route_eligible=dashboard.paid_api_route_eligible,
        paid_api_blocking_reasons=tuple(dashboard.paid_api_blocking_reasons),
        paid_route_eligibility_state=eligibility_state,
        paid_route_eligibility_reasons=eligibility_reasons,
        route_quota_evidence_refs=route_quota_evidence_refs,
        evidence_refs=evidence_refs,
    )


def _decision(
    request: DispatchRequest,
    action: DispatchAction,
    reasons: tuple[str, ...],
    created_at: datetime,
    *,
    quality_floor_satisfied: bool,
    authority_allowed: bool,
    dimensional_candidates: tuple[DimensionalCandidateReceipt, ...] | None = None,
    selected_route_id: str | None = None,
    degraded_mode: bool = False,
    degraded_authority_ref: str | None = None,
    compatibility_mode: Literal["none", "rollback_full_profile"] = "none",
    degraded_state: str | None = None,
) -> RouteDecision:
    compatibility_degraded = compatibility_mode != "none" or degraded_state is not None
    route_policy_green = action is DispatchAction.LAUNCH and not compatibility_degraded
    cloud_burst_receipt = _cloud_burst_receipt_fields(request, reasons)
    decision = RouteDecision(
        decision_id=_decision_id(request, action, reasons, created_at),
        created_at=created_at,
        task_id=request.task_id,
        lane=request.lane,
        route_id=request.route_id,
        platform=request.platform,
        mode=request.mode,
        profile=request.profile,
        action=action,
        policy_outcome=action.value,
        launch_allowed=action is DispatchAction.LAUNCH,
        prompt_allowed=action is DispatchAction.LAUNCH,
        route_policy_green=route_policy_green,
        clog_state=_clog_state(action, compatibility_degraded=compatibility_degraded),
        compatibility_mode=compatibility_mode,
        degraded_state=degraded_state,
        registry_freshness_green=False
        if compatibility_degraded
        else _registry_freshness_green(request),
        quota_freshness_green=False if compatibility_degraded else _quota_freshness_green(request),
        resource_freshness_green=False
        if compatibility_degraded
        else _resource_freshness_green(request),
        route_selection_authority=False,
        quality_floor_satisfied=quality_floor_satisfied,
        authority_allowed=authority_allowed,
        # resolve the descriptor leaf for EVERY launch path (dimensional, single-route,
        # compatibility-rollback) — centralized here so no launch site can silently drop it.
        selected_descriptor_leaf=(
            _resolve_descriptor_leaf(request) if action is DispatchAction.LAUNCH else None
        ),
        **cloud_burst_receipt,
        reason_codes=tuple(reason for reason in reasons if reason),
        message="; ".join(reason for reason in reasons if reason) or action.value,
        quota_evidence_refs=_quota_evidence_refs(request.quota),
        resource_state_refs=request.resource_state_refs,
    )
    decision._dimensional_receipt = _build_dimensional_route_receipt(
        decision,
        request,
        dimensional_candidates=dimensional_candidates,
        selected_route_id=selected_route_id,
        degraded_mode=degraded_mode,
        degraded_authority_ref=degraded_authority_ref,
    )
    return decision


def _clog_state(action: DispatchAction, *, compatibility_degraded: bool) -> ClogRouteState:
    if compatibility_degraded:
        return ClogRouteState.COMPATIBILITY_DEGRADED
    if action is DispatchAction.LAUNCH:
        return ClogRouteState.POLICY_GREEN
    if action is DispatchAction.SUPPORT_ONLY:
        return ClogRouteState.SUPPORT_ONLY
    if action is DispatchAction.REFUSE:
        return ClogRouteState.REFUSED
    return ClogRouteState.HELD


def _registry_freshness_green(request: DispatchRequest) -> bool:
    capability = request.capability
    return bool(
        capability is not None
        and capability.supported
        and capability.freshness_ok
        and not capability.surface_delta_blockers
    )


def _quota_freshness_green(request: DispatchRequest) -> bool:
    capability = request.capability
    if capability is not None and capability.surface_delta_blockers:
        return False
    if _requires_route_specific_subscription_quota(request.route_id):
        if (
            capability is None
            or not capability.supported
            or capability.capacity_pool != "subscription_quota"
            or not capability.freshness_ok
        ):
            return False
        quota = request.quota
        if quota is None or not quota.available:
            return False
        if quota.budget_ledger_stale is not False:
            return False
        return quota.route_subscription_quota_state == "fresh"
    if (
        capability is not None
        and capability.capacity_pool == "subscription_quota"
        and capability.freshness_ok
    ):
        return not any("quota" in error for error in capability.freshness_errors)
    quota = request.quota
    if quota is None or not quota.available:
        return False
    return quota.budget_ledger_stale is False


def _resource_freshness_green(request: DispatchRequest) -> bool:
    capability = request.capability
    quota = request.quota
    if capability is None or not capability.freshness_ok or capability.surface_delta_blockers:
        return False
    if any("resource" in error for error in capability.freshness_errors):
        return False
    return bool(quota is not None and quota.local_resource_state == "green")


def _quality_or_authority_failure_decision(
    request: DispatchRequest,
    capability: RouteCapabilityState,
    checked_at: datetime,
    *,
    quality_floor_satisfied: bool,
    authority_allowed: bool,
    base_reason: str,
) -> RouteDecision:
    if _review_eligible(request) and capability.authority_ceiling in SUPPORT_CEILINGS:
        return _decision(
            request,
            DispatchAction.SUPPORT_ONLY,
            (base_reason, "support_artifact_requires_independent_review"),
            checked_at,
            quality_floor_satisfied=quality_floor_satisfied,
            authority_allowed=authority_allowed,
        )
    return _decision(
        request,
        DispatchAction.REFUSE,
        (base_reason, "support_artifact_review_missing"),
        checked_at,
        quality_floor_satisfied=quality_floor_satisfied,
        authority_allowed=authority_allowed,
    )


def _decision_id(
    request: DispatchRequest,
    action: DispatchAction,
    reasons: tuple[str, ...],
    created_at: datetime,
) -> str:
    stamp = created_at.isoformat().replace("+00:00", "Z").replace("-", "").replace(":", "")
    digest = hashlib.sha256(
        json.dumps(
            {
                "task_id": request.task_id,
                "lane": request.lane,
                "route_id": request.route_id,
                "action": action.value,
                "reasons": reasons,
                "created_at": stamp,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"rd-{stamp}-{_slug(request.task_id)}-{digest}"


def _route_id(platform: str, mode: str, profile: str) -> str:
    return ".".join([platform.strip(), mode.strip().replace("-", "_"), profile.strip()])


def _cloud_burst_policy_gate(request: DispatchRequest) -> tuple[DispatchAction, tuple[str, ...]]:
    cloud = request.cloud_burst
    eligible = _cloud_burst_eligible(request)
    if eligible and _is_local_dev_route(request):
        return (
            DispatchAction.REFUSE,
            (
                "cloud_burst_spike_excludes_local_fleet",
                f"cloud_burst_target:{next(iter(sorted(CLOUD_BURST_ROUTE_IDS)))}",
                f"local_execution_target:{LOCAL_DEV_TARGET}",
                *_cloud_spike_reason_codes(request),
            ),
        )

    if not _is_cloud_burst_route(request):
        return DispatchAction.LAUNCH, ()

    if not eligible:
        return (
            DispatchAction.REFUSE,
            (
                "cloud_burst_not_eligible_appendix_default",
                f"local_execution_target:{LOCAL_DEV_TARGET}",
            ),
        )

    violations: list[str] = []
    if _privacy_sensitive(request) or not _cloud_bool(cloud, "no_secret_egress"):
        violations.append("cloud_burst_secret_egress_guard_failed")
    if not _cloud_bool(cloud, "public_repo_only"):
        violations.append("cloud_burst_public_repo_guard_failed")
    if not _cloud_bool(cloud, "read_mostly"):
        violations.append("cloud_burst_read_mostly_guard_failed")

    budget_ref = _optional_string(cloud.get("provider_budget_ref"))
    if budget_ref is None:
        violations.append("cloud_burst_budget_ref_missing")
    elif request.quota is not None and request.quota.evidence_refs:
        if budget_ref not in request.quota.evidence_refs:
            violations.append("cloud_burst_budget_ref_not_backed_by_ledger")

    if violations:
        return (
            DispatchAction.REFUSE,
            (
                *violations,
                *_cloud_spike_reason_codes(request),
            ),
        )
    return DispatchAction.LAUNCH, ()


def _launch_reason_codes(
    request: DispatchRequest,
    *,
    checked_at: datetime,
) -> tuple[str, ...]:
    runtime_authority_ref = _runtime_actuation_receipt_reference(request, checked_at=checked_at)
    if _is_cloud_burst_route(request):
        return (
            "policy_launch",
            "cloud_burst_guard_passed",
            *_cloud_spike_reason_codes(request),
            *((runtime_authority_ref,) if runtime_authority_ref else ()),
        )
    if not _cloud_burst_eligible(request) and _is_local_dev_route(request):
        return (
            "policy_launch",
            "cloud_burst_not_eligible_appendix_default",
            f"local_execution_target:{LOCAL_DEV_TARGET}",
            *((runtime_authority_ref,) if runtime_authority_ref else ()),
        )
    return ("policy_launch", *((runtime_authority_ref,) if runtime_authority_ref else ()))


def _is_cloud_burst_route(request: DispatchRequest) -> bool:
    return request.route_id in CLOUD_BURST_ROUTE_IDS


def _is_local_dev_route(request: DispatchRequest) -> bool:
    return request.platform in LOCAL_DEV_PLATFORMS


def _cloud_burst_eligible(request: DispatchRequest) -> bool:
    return _cloud_bool(request.cloud_burst, "eligible")


def _cloud_spike_reason_codes(request: DispatchRequest) -> tuple[str, ...]:
    reasons = request.cloud_burst.get("spike_reasons")
    if not isinstance(reasons, (list, tuple)):
        return ()
    return tuple(f"cloud_burst_spike:{reason}" for reason in reasons if str(reason).strip())


def _cloud_bool(cloud_burst: Mapping[str, object], field: str) -> bool:
    value = cloud_burst.get(field)
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _cloud_burst_receipt_fields(
    request: DispatchRequest,
    reasons: tuple[str, ...],
) -> dict[str, object]:
    eligible = _cloud_burst_eligible(request)
    raw_spike_reasons = request.cloud_burst.get("spike_reasons", ())
    if not isinstance(raw_spike_reasons, (list, tuple)):
        raw_spike_reasons = ()
    spike_reasons = tuple(str(reason) for reason in raw_spike_reasons if str(reason).strip())
    if _is_cloud_burst_route(request):
        if not eligible:
            state = "ineligible"
        elif any(_cloud_burst_guard_failure_reason(reason) for reason in reasons):
            state = "blocked"
        else:
            state = "eligible"
    elif _is_local_dev_route(request):
        state = "excluded_local" if eligible else "appendix_default"
    else:
        state = "not_applicable"

    guard_reasons = tuple(reason for reason in reasons if _cloud_burst_guard_failure_reason(reason))
    return {
        "cloud_burst_eligible": eligible,
        "cloud_burst_guard_state": state,
        "cloud_burst_spike_reasons": spike_reasons,
        "cloud_burst_guard_reasons": guard_reasons,
        "local_execution_target": LOCAL_DEV_TARGET
        if state in {"appendix_default", "excluded_local", "ineligible"}
        else None,
    }


def _cloud_burst_guard_failure_reason(reason: str) -> bool:
    return (
        reason.startswith("cloud_burst_")
        and reason != "cloud_burst_guard_passed"
        and not reason.startswith("cloud_burst_spike:")
        and not reason.startswith("cloud_burst_target:")
    )


def _route_constraint_reasons(request: DispatchRequest) -> tuple[str, ...]:
    constraints = request.route_constraints
    reasons: list[str] = []
    prohibited = _string_set(constraints.get("prohibited_platforms"))
    allowed = _string_set(constraints.get("allowed_platforms"))
    required_mode = _optional_string(constraints.get("required_mode"))
    required_profile = _optional_string(constraints.get("required_profile"))
    if request.platform in prohibited:
        reasons.append("route_platform_prohibited")
    if allowed and request.platform not in allowed:
        reasons.append("route_platform_not_allowed")
    if required_mode and request.mode != required_mode:
        reasons.append("route_mode_mismatch")
    if required_profile and request.profile != required_profile:
        reasons.append("route_profile_mismatch")
    return tuple(reasons)


def _operator_coupled_evidence_refs(task_fields: Mapping[str, object]) -> tuple[str, ...]:
    refs: list[str] = []
    if _truthy(task_fields.get("operator_coupled")):
        refs.append("operator_coupled:frontmatter")
    if _optional_string(task_fields.get("dispatch_mode")) == "interactive_only":
        refs.append("operator_coupled:dispatch_mode")
    for value in _operator_coupled_path_values(task_fields.get("__operator_coupled_path_matches")):
        refs.append(f"operator_coupled:path:{value}")
    return tuple(dict.fromkeys(refs))


def _operator_coupled_path_values(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    return (text,) if text else ()


def _privacy_sensitive(request: DispatchRequest) -> bool:
    return bool(request.risk_flags.get("privacy_or_secret_sensitive"))


def _mutation_requested(request: DispatchRequest) -> bool:
    surface = request.mutation_surface
    return bool(surface and surface not in NON_MUTATING_SURFACES)


def _mutation_refusal_reason(
    request: DispatchRequest,
    capability: RouteCapabilityState,
    *,
    checked_at: datetime,
) -> str | None:
    surface = request.mutation_surface
    if surface is None or surface in NON_MUTATING_SURFACES:
        return None
    if not capability.mutability.get(surface, False):
        if capability.authority_ceiling == "read_only":
            return "read_only_mutation_route"
        if surface == "runtime":
            return _runtime_actuation_refusal_reason(request, checked_at=checked_at)
        return f"route_not_mutable_for_{surface}"
    return None


def _runtime_actuation_refusal_reason(
    request: DispatchRequest,
    *,
    checked_at: datetime,
) -> str | None:
    receipts = tuple(
        receipt
        for receipt in request.route_authority_receipts
        if receipt.receipt_type == "runtime_actuation"
    )
    if not receipts:
        return "runtime_actuation_receipt_absent"

    route_matches = tuple(
        receipt
        for receipt in receipts
        if normalize_route_id(receipt.route_id) == normalize_route_id(request.route_id)
    )
    if not route_matches:
        return "runtime_actuation_route_mismatch"

    task_matches = tuple(
        receipt for receipt in route_matches if request.task_id in receipt.task_ids
    )
    if not task_matches:
        return "runtime_actuation_task_mismatch"

    if not any(request.mutation_surface in receipt.mutation_surfaces for receipt in task_matches):
        return "runtime_actuation_surface_mismatch"
    if not any(
        _route_authority_receipt_is_fresh(receipt, now=checked_at)
        for receipt in task_matches
        if request.mutation_surface in receipt.mutation_surfaces
    ):
        return "runtime_actuation_receipt_stale"
    return None


def _runtime_actuation_receipt_reference(
    request: DispatchRequest,
    *,
    checked_at: datetime,
) -> str | None:
    if request.mutation_surface != "runtime":
        return None
    for receipt in request.route_authority_receipts:
        if (
            receipt.receipt_type == "runtime_actuation"
            and normalize_route_id(receipt.route_id) == normalize_route_id(request.route_id)
            and request.task_id in receipt.task_ids
            and request.mutation_surface in receipt.mutation_surfaces
            and _route_authority_receipt_is_fresh(receipt, now=checked_at)
        ):
            return route_authority_receipt_reference(receipt)
    return None


def _paid_route_refusal_reasons(
    request: DispatchRequest, capability: RouteCapabilityState
) -> tuple[str, ...]:
    requires_paid_gate = (
        capability.capacity_pool in PAID_CAPACITY_POOLS
        or request.mutation_surface == "provider_spend"
    )
    if not requires_paid_gate:
        return ()
    quota = request.quota
    if quota is None or not quota.available:
        return ("paid_route_ledger_unavailable",)
    if quota.budget_ledger_stale:
        return ("paid_route_ledger_stale",)
    if (
        quota.paid_route_eligibility_state
        and quota.paid_route_eligibility_state != "eligible_active_budget"
    ):
        return (
            "paid_route_without_active_budget",
            quota.paid_route_eligibility_state,
            *quota.paid_route_eligibility_reasons,
        )
    if quota.paid_api_budget_state not in {"active", None}:
        return (
            "paid_route_without_active_budget",
            f"paid_api_budget_state:{quota.paid_api_budget_state}",
        )
    if quota.paid_api_route_eligible is False:
        return ("paid_route_without_active_budget", *quota.paid_api_blocking_reasons)
    return ()


def _subscription_quota_hold_reasons(
    request: DispatchRequest,
    capability: RouteCapabilityState,
) -> tuple[str, ...]:
    requires_route_specific_quota = _requires_route_specific_subscription_quota(request.route_id)
    if not requires_route_specific_quota:
        return ()
    if capability.capacity_pool != "subscription_quota":
        return (
            "subscription_route_capacity_pool_mismatch",
            f"capacity_pool:{capability.capacity_pool or 'missing'}",
            f"route_id:{normalize_route_id(request.route_id)}",
        )
    quota = request.quota
    if quota is None or not quota.available:
        return ("subscription_route_quota_unavailable",)
    if quota.budget_ledger_stale is True:
        return ("subscription_quota_ledger_stale",)
    if quota.budget_ledger_stale is not False:
        return ("subscription_quota_ledger_unknown",)
    route_state = quota.route_subscription_quota_state
    if route_state is None:
        if requires_route_specific_quota:
            route_state = "unknown"
        else:
            return ()
    if route_state == "fresh":
        return ()
    evidence = quota.route_quota_evidence_refs or (
        f"quota-snapshot:{normalize_route_id(request.route_id)}:missing",
    )
    return (
        "subscription_route_quota_not_fresh",
        f"route_subscription_quota_state:{route_state}",
        *evidence,
    )


def _requires_route_specific_subscription_quota(route_id: str) -> bool:
    return normalize_route_id(route_id) in ROUTE_SPECIFIC_SUBSCRIPTION_QUOTA_REQUIRED


def _unsupported_route_subscription_quota_reasons(
    request: DispatchRequest,
) -> tuple[str, ...]:
    if not _requires_route_specific_subscription_quota(request.route_id):
        return ()
    quota = request.quota
    if quota is None or not quota.available:
        return ("subscription_route_quota_unavailable", "subscription_route_capability_missing")
    route_state = quota.route_subscription_quota_state or "unknown"
    if route_state == "fresh":
        return ("subscription_route_capability_missing",)
    evidence = quota.route_quota_evidence_refs or (
        f"quota-snapshot:{normalize_route_id(request.route_id)}:missing",
    )
    return (
        "subscription_route_quota_not_fresh",
        f"route_subscription_quota_state:{route_state}",
        *evidence,
        "subscription_route_capability_missing",
    )


def _freshness_hold_reasons(capability: RouteCapabilityState) -> tuple[str, ...]:
    if capability.freshness_ok and not capability.surface_delta_blockers:
        return ()
    reasons = []
    errors = capability.freshness_errors
    if capability.surface_delta_blockers:
        reasons.append("capability_surface_delta_pending")
    if any("resource" in error for error in errors):
        reasons.append("resource_telemetry_stale_or_unknown")
    if any("quota" in error for error in errors):
        reasons.append("quota_telemetry_stale_or_unknown")
    if any("capability" in error for error in errors):
        reasons.append("capability_data_stale_or_unknown")
    if any("provider_docs" in error for error in errors):
        reasons.append("provider_docs_stale_or_unknown")
    if not reasons:
        reasons.append("capability_freshness_failed")
    reasons.extend(capability.surface_delta_blockers)
    reasons.extend(errors)
    return tuple(reasons)


def _authority_allowed(request: DispatchRequest, capability: RouteCapabilityState) -> bool:
    if request.authority_level == "authoritative":
        return capability.authority_ceiling in AUTHORITATIVE_CEILINGS
    if request.authority_level in {"support_non_authoritative", "evidence_receipt", "relay_only"}:
        return capability.authority_ceiling in SUPPORT_CEILINGS
    return False


def _review_eligible(request: DispatchRequest) -> bool:
    return bool(
        request.review_requirement.get("support_artifact_allowed")
        and request.review_requirement.get("independent_review_required")
        and request.review_requirement.get("authoritative_acceptor_profile")
    )


def _resource_state_refs(
    capability: RouteCapabilityState | None,
    quota: QuotaSpendState | None,
) -> tuple[str, ...]:
    refs: list[str] = []
    if capability is not None:
        refs.extend(error for error in capability.freshness_errors if "resource" in error)
        if capability.telemetry_resource_source:
            refs.append(f"capability.resource_source:{capability.telemetry_resource_source}")
    if quota is not None and quota.local_resource_state:
        refs.append(f"quota.local_resource_state:{quota.local_resource_state}")
    return tuple(refs)


def _quota_evidence_refs(quota: QuotaSpendState | None) -> tuple[str, ...]:
    if quota is None:
        return ()
    return tuple(dict.fromkeys([*quota.route_quota_evidence_refs, *quota.evidence_refs]))


def _task_class_for(metadata: RouteMetadataAssessment) -> str:
    if metadata.metadata is None:
        return "unknown"
    if metadata.metadata.authority_level.value == "authoritative":
        return "authority-case-implementation"
    return metadata.metadata.authority_level.value


def _paid_provider_for(capability: RouteCapabilityState) -> str:
    if capability.paid_provider:
        return capability.paid_provider
    parts = capability.route_id.split(".")
    return parts[0] if parts else "unknown"


def _profile_from_route_id(route_id: str) -> str:
    parts = route_id.split(".")
    return parts[2] if len(parts) >= 3 else "unknown"


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0)


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "none", "null", "~"}:
        return None
    return text


def _string_set(value: object) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set, frozenset)):
        return {str(item).strip() for item in value if str(item).strip()}
    return {str(value).strip()}


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def _slug(value: str) -> str:
    chars = [ch if ch.isalnum() or ch in {"_", ".", "-"} else "-" for ch in value]
    slug = "".join(chars).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "item"


_PYDANTIC_DYNAMIC_ENTRYPOINTS = (
    evaluate_dispatch_policy,
    build_dispatch_request,
    route_decision_receipt_payload,
)


__all__ = [
    "CandidateStatus",
    "ClogRouteState",
    "ConfidenceReceipt",
    "DemandVectorRef",
    "DimensionalCandidateReceipt",
    "DimensionalRouteReceipt",
    "DimensionalScore",
    "DimensionalVeto",
    "DispatchAction",
    "DispatchPolicySources",
    "DispatchRequest",
    "DominanceRelation",
    "QuotaSpendState",
    "RouteAuthorityReceipt",
    "RouteCapabilityState",
    "RouteDecision",
    "StaleMetadataReceipt",
    "apply_route_authority_receipts",
    "build_dispatch_request",
    "build_route_authority_receipt",
    "evaluate_dispatch_policy",
    "load_dispatch_policy_sources",
    "route_authority_receipt_payload_hash",
    "route_authority_receipt_reference",
    "route_decision_receipt_payload",
    "write_route_authority_receipt",
    "write_route_decision_receipt",
]
