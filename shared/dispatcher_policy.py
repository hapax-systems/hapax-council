"""Fail-closed dispatcher policy for capacity routing.

The evaluator in this module is intentionally pure: it does not launch lanes,
shell out, read credentials, or mutate task state. Runtime integration is
limited to building a typed request from local state and writing append-only
route decision receipts.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
    PlatformCapabilityRegistry,
    PlatformCapabilityRegistryError,
    PlatformCapabilityRoute,
    check_registry_freshness,
    load_platform_capability_registry,
    normalize_route_id,
)
from shared.quota_spend_ledger import (
    QUOTA_SPEND_LEDGER_FIXTURES,
    PaidRouteRequest,
    QuotaSpendLedger,
    QuotaSpendLedgerError,
    build_dashboard,
    evaluate_paid_route_eligibility,
    load_quota_spend_ledger,
)
from shared.route_metadata_schema import RouteMetadataAssessment, assess_route_metadata

ROUTE_DECISION_SCHEMA_VERSION = 1
ROUTE_DECISION_LEDGER = "route-decisions.jsonl"
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


class DispatchAction(StrEnum):
    LAUNCH = "launch"
    HOLD = "hold"
    SUPPORT_ONLY = "support_only"
    REFUSE = "refuse"


class _PolicyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RouteCapabilityState(_PolicyModel):
    route_id: str
    supported: bool
    route_state: str | None = None
    blocked_reasons: tuple[str, ...] = Field(default=())
    capacity_pool: str | None = None
    authority_ceiling: str | None = None
    privacy_posture: str | None = None
    eligible_quality_floors: tuple[str, ...] = Field(default=())
    explicit_equivalence_records: tuple[str, ...] = Field(default=())
    excluded_task_classes: tuple[str, ...] = Field(default=())
    mutability: dict[str, bool] = Field(default_factory=dict)
    freshness_ok: bool = False
    freshness_errors: tuple[str, ...] = Field(default=())
    telemetry_quota_source: str | None = None
    telemetry_resource_source: str | None = None


class QuotaSpendState(_PolicyModel):
    available: bool
    load_error: str | None = None
    budget_ledger_stale: bool | None = None
    paid_api_budget_state: str | None = None
    local_resource_state: str | None = None
    paid_api_route_eligible: bool | None = None
    paid_api_blocking_reasons: tuple[str, ...] = Field(default=())
    paid_route_eligibility_state: str | None = None
    paid_route_eligibility_reasons: tuple[str, ...] = Field(default=())
    evidence_refs: tuple[str, ...] = Field(default=())


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
    risk_flags: dict[str, bool] = Field(default_factory=dict)
    context_shape: dict[str, object] = Field(default_factory=dict)
    route_constraints: dict[str, object] = Field(default_factory=dict)
    review_requirement: dict[str, object] = Field(default_factory=dict)
    capability: RouteCapabilityState | None = None
    quota: QuotaSpendState | None = None
    resource_state_refs: tuple[str, ...] = Field(default=())
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
    quality_floor_satisfied: bool
    authority_allowed: bool
    reason_codes: tuple[str, ...] = Field(default=())
    message: str
    resource_state_refs: tuple[str, ...] = Field(default=())


class DispatchPolicySources(_PolicyModel):
    registry: PlatformCapabilityRegistry | None = None
    registry_error: str | None = None
    quota_ledger: QuotaSpendLedger | None = None
    quota_error: str | None = None


def now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def load_dispatch_policy_sources(
    *,
    registry_path: Path | None = None,
    quota_ledger_path: Path | None = None,
) -> DispatchPolicySources:
    """Load inert policy sources, turning failures into request evidence."""

    registry: PlatformCapabilityRegistry | None = None
    registry_error: str | None = None
    quota_ledger: QuotaSpendLedger | None = None
    quota_error: str | None = None

    try:
        registry = load_platform_capability_registry(registry_path or PLATFORM_CAPABILITY_REGISTRY)
    except (IndexError, PlatformCapabilityRegistryError, OSError, ValueError) as exc:
        registry_error = str(exc)

    try:
        quota_ledger = load_quota_spend_ledger(quota_ledger_path or QUOTA_SPEND_LEDGER_FIXTURES)
    except (IndexError, QuotaSpendLedgerError, OSError, ValueError) as exc:
        quota_error = str(exc)

    return DispatchPolicySources(
        registry=registry,
        registry_error=registry_error,
        quota_ledger=quota_ledger,
        quota_error=quota_error,
    )


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
    rollback_mode: bool = False,
    legacy_route_supported: bool = False,
    legacy_route_mutable: bool = False,
    now: datetime | None = None,
) -> DispatchRequest:
    """Build the typed request consumed by the pure policy evaluator."""

    route_id = _route_id(platform, mode, profile)
    metadata = assess_route_metadata(task_fields)
    capability = _capability_state(registry, route_id, registry_error, now=now)
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
        risk_flags=route_metadata.risk_flags.model_dump(mode="json") if route_metadata else {},
        context_shape=route_metadata.context_shape.model_dump(mode="json")
        if route_metadata
        else {},
        route_constraints=route_metadata.route_constraints.model_dump(mode="json")
        if route_metadata
        else {},
        review_requirement=route_metadata.review_requirement.model_dump(mode="json")
        if route_metadata
        else {},
        capability=capability,
        quota=quota,
        resource_state_refs=_resource_state_refs(capability, quota),
        rollback_mode=rollback_mode,
        legacy_route_supported=legacy_route_supported,
        legacy_route_mutable=legacy_route_mutable,
    )


def evaluate_dispatch_policy(
    request: DispatchRequest,
    *,
    now: datetime | None = None,
) -> RouteDecision:
    """Return a fail-closed route decision without side effects."""

    checked_at = now_utc() if now is None else _coerce_utc(now)
    if request.rollback_mode:
        if not request.legacy_route_supported:
            return _decision(
                request,
                DispatchAction.REFUSE,
                ("rollback_unsupported_route_refused",),
                checked_at,
                quality_floor_satisfied=False,
                authority_allowed=False,
            )
        if request.profile != "full":
            return _decision(
                request,
                DispatchAction.HOLD,
                ("rollback_non_full_profile_hold",),
                checked_at,
                quality_floor_satisfied=False,
                authority_allowed=False,
            )
        if _mutation_requested(request) and not request.legacy_route_mutable:
            return _decision(
                request,
                DispatchAction.REFUSE,
                ("rollback_read_only_mutation_refused",),
                checked_at,
                quality_floor_satisfied=False,
                authority_allowed=False,
            )
        return _decision(
            request,
            DispatchAction.LAUNCH,
            ("rollback_full_profile_launch",),
            checked_at,
            quality_floor_satisfied=True,
            authority_allowed=True,
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

    capability = request.capability
    if capability is None:
        return _decision(
            request,
            DispatchAction.HOLD,
            ("capability_registry_unavailable",),
            checked_at,
            quality_floor_satisfied=False,
            authority_allowed=False,
        )
    if not capability.supported:
        return _decision(
            request,
            DispatchAction.REFUSE,
            ("unsupported_route",),
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

    mutation_reason = _mutation_refusal_reason(request, capability)
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
        ("policy_launch",),
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
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(decision.model_dump(mode="json"), sort_keys=True) + "\n")
    return path


def route_decision_receipt_payload(decision: RouteDecision) -> dict[str, Any]:
    return {
        "route_decision_id": decision.decision_id,
        "route_policy_action": decision.action.value,
        "route_policy_outcome": decision.policy_outcome,
        "route_policy_reason_codes": list(decision.reason_codes),
        "route_policy_launch_allowed": decision.launch_allowed,
        "route_policy_quality_floor_satisfied": decision.quality_floor_satisfied,
        "route_policy_authority_allowed": decision.authority_allowed,
    }


def _capability_state(
    registry: PlatformCapabilityRegistry | None,
    route_id: str,
    registry_error: str | None,
    *,
    now: datetime | None,
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
    return _route_capability_state(route, freshness.ok, freshness.errors)


def _route_capability_state(
    route: PlatformCapabilityRoute,
    freshness_ok: bool,
    freshness_errors: tuple[str, ...],
) -> RouteCapabilityState:
    return RouteCapabilityState(
        route_id=route.route_id,
        supported=True,
        route_state=route.route_state.value,
        blocked_reasons=tuple(route.blocked_reasons),
        capacity_pool=route.capacity_pool.value,
        authority_ceiling=route.authority_ceiling.value,
        privacy_posture=route.privacy_posture.value,
        eligible_quality_floors=tuple(
            quality_floor.value for quality_floor in route.quality_envelope.eligible_quality_floors
        ),
        explicit_equivalence_records=tuple(route.quality_envelope.explicit_equivalence_records),
        excluded_task_classes=tuple(route.quality_envelope.excluded_task_classes),
        mutability=route.mutability.model_dump(mode="json"),
        freshness_ok=freshness_ok,
        freshness_errors=freshness_errors,
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
    if capability is not None and capability.capacity_pool in PAID_CAPACITY_POOLS:
        request = PaidRouteRequest(
            route_id=capability.route_id,
            provider=_paid_provider_for(capability),
            profile=capability.profile
            if hasattr(capability, "profile")
            else _profile_from_route_id(capability.route_id),
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
        paid_api_budget_state=dashboard.paid_api_budget_state.value,
        local_resource_state=dashboard.local_resource_state.value,
        paid_api_route_eligible=dashboard.paid_api_route_eligible,
        paid_api_blocking_reasons=tuple(dashboard.paid_api_blocking_reasons),
        paid_route_eligibility_state=eligibility_state,
        paid_route_eligibility_reasons=eligibility_reasons,
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
) -> RouteDecision:
    return RouteDecision(
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
        quality_floor_satisfied=quality_floor_satisfied,
        authority_allowed=authority_allowed,
        reason_codes=tuple(reason for reason in reasons if reason),
        message="; ".join(reason for reason in reasons if reason) or action.value,
        resource_state_refs=request.resource_state_refs,
    )


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


def _privacy_sensitive(request: DispatchRequest) -> bool:
    return bool(request.risk_flags.get("privacy_or_secret_sensitive"))


def _mutation_requested(request: DispatchRequest) -> bool:
    surface = request.mutation_surface
    return bool(surface and surface not in NON_MUTATING_SURFACES)


def _mutation_refusal_reason(
    request: DispatchRequest, capability: RouteCapabilityState
) -> str | None:
    surface = request.mutation_surface
    if surface is None or surface in NON_MUTATING_SURFACES:
        return None
    if not capability.mutability.get(surface, False):
        if capability.authority_ceiling == "read_only":
            return "read_only_mutation_route"
        return f"route_not_mutable_for_{surface}"
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


def _freshness_hold_reasons(capability: RouteCapabilityState) -> tuple[str, ...]:
    if capability.freshness_ok:
        return ()
    reasons = []
    errors = capability.freshness_errors
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


def _task_class_for(metadata: RouteMetadataAssessment) -> str:
    if metadata.metadata is None:
        return "unknown"
    if metadata.metadata.authority_level.value == "authoritative":
        return "authority-case-implementation"
    return metadata.metadata.authority_level.value


def _paid_provider_for(capability: RouteCapabilityState) -> str:
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
    "DispatchAction",
    "DispatchPolicySources",
    "DispatchRequest",
    "QuotaSpendState",
    "RouteCapabilityState",
    "RouteDecision",
    "build_dispatch_request",
    "evaluate_dispatch_policy",
    "load_dispatch_policy_sources",
    "route_decision_receipt_payload",
    "write_route_decision_receipt",
]
