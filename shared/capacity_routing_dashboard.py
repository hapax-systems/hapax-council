"""Observe-only dashboard state for quality-preserving capacity routing.

The read model in this module combines local routing evidence that already
exists elsewhere in the repo. It does not select routes, dispatch work, spend
budget, refresh quota, repair fixtures, or call providers.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
    PlatformCapabilityRegistryError,
    check_registry_freshness,
    load_platform_capability_registry,
)
from shared.quota_spend_ledger import (
    QUOTA_SPEND_LEDGER_FIXTURES,
    QuotaSpendDashboard,
    QuotaSpendLedger,
    QuotaSpendLedgerError,
    load_quota_spend_ledger,
)
from shared.quota_spend_ledger import (
    build_dashboard as build_quota_spend_dashboard,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_METADATA_STALE_AFTER_S = 900
_ROUTE_METADATA_KEYS = ("explicit", "derived", "hold", "malformed")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RouteMetadataSummary(StrictModel):
    explicit: int = Field(default=0, ge=0)
    derived: int = Field(default=0, ge=0)
    hold: int = Field(default=0, ge=0)
    malformed: int = Field(default=0, ge=0)


class CapacityRoutingNonGreenState(StrictModel):
    source: Literal["route_metadata", "platform_registry", "quota_spend_ledger"]
    state: str = Field(min_length=1)
    severity: Literal["warning", "blocked", "unknown"]
    summary: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default=())


class CapacityRoutingRouteState(StrictModel):
    route_id: str = Field(min_length=1)
    supported: bool
    summary: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(default=())


class CapacityRoutingDashboard(StrictModel):
    schema_version: Literal[1] = 1
    generated_at: datetime
    observe_only: Literal[True] = True
    route_selection_authority: Literal[False] = False
    dispatch_authority: Literal[False] = False
    spend_authority: Literal[False] = False
    repair_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    route_metadata_summary: RouteMetadataSummary
    route_metadata_generated_at: datetime | None = None
    registry_freshness_ok: bool
    registry_route_count: int = Field(ge=0)
    registry_non_green_route_count: int = Field(ge=0)
    registry_non_green_routes: tuple[CapacityRoutingRouteState, ...] = Field(default=())
    quality_preserving_routes_available: str
    blocked_quality_floor_reason: str | None = None
    subscription_quota_state: str
    paid_api_budget_state: str
    bootstrap_dependency_state: str
    local_resource_state: str
    current_capacity_pool: str | None = None
    provider_dependency_count: int = Field(ge=0)
    support_artifacts_waiting_for_review: int = Field(ge=0)
    budget_ledger_stale: bool
    next_budget_review_at: datetime | None = None
    paid_api_route_eligible: bool
    transition_budget_refs: tuple[str, ...] = Field(default=())
    unreconciled_spend_refs: tuple[str, ...] = Field(default=())
    provider_dependency_refs: tuple[str, ...] = Field(default=())
    support_artifact_refs: tuple[str, ...] = Field(default=())
    renewal_review_refs: tuple[str, ...] = Field(default=())
    non_green_states: tuple[CapacityRoutingNonGreenState, ...] = Field(default=())
    warning_count: int = Field(ge=0)


def build_capacity_routing_dashboard(
    *,
    route_metadata_summary: Mapping[str, object] | None = None,
    route_metadata_items: Sequence[Mapping[str, object]] = (),
    route_metadata_generated_at: datetime | None = None,
    route_metadata_stale_after_s: int = ROUTE_METADATA_STALE_AFTER_S,
    registry_path: Path = PLATFORM_CAPABILITY_REGISTRY,
    quota_spend_ledger_path: Path = QUOTA_SPEND_LEDGER_FIXTURES,
    now: datetime | None = None,
) -> CapacityRoutingDashboard:
    """Build the private observe-only routing dashboard, failing closed."""

    generated_at = _coerce_now(now)
    non_green: list[CapacityRoutingNonGreenState] = []
    summary = _coerce_route_metadata_summary(route_metadata_summary)
    _append_route_metadata_warnings(
        non_green=non_green,
        summary=summary,
        source_available=route_metadata_summary is not None,
        route_metadata_items=route_metadata_items,
        route_metadata_generated_at=route_metadata_generated_at,
        route_metadata_stale_after_s=route_metadata_stale_after_s,
        now=generated_at,
    )

    registry_ok, registry_route_count, registry_routes = _registry_dashboard_state(
        registry_path=registry_path,
        now=generated_at,
        non_green=non_green,
    )

    quota_state = _quota_dashboard_state(
        ledger_path=quota_spend_ledger_path,
        now=generated_at,
        non_green=non_green,
    )

    return CapacityRoutingDashboard(
        generated_at=generated_at,
        route_metadata_summary=summary,
        route_metadata_generated_at=route_metadata_generated_at,
        registry_freshness_ok=registry_ok,
        registry_route_count=registry_route_count,
        registry_non_green_route_count=len(registry_routes),
        registry_non_green_routes=tuple(registry_routes),
        warning_count=len(non_green),
        non_green_states=tuple(non_green),
        **quota_state,
    )


def route_metadata_items_from_planning_queue(
    planning_queue: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    items: list[dict[str, object]] = []
    for row in planning_queue:
        metadata = row.get("route_metadata")
        if not isinstance(metadata, Mapping):
            continue
        status = str(metadata.get("status", "")).strip()
        if status not in {"hold", "malformed"}:
            continue
        task_id = str(row.get("task_id", "")).strip()
        evidence_refs = _string_tuple(metadata.get("evidence_refs"))
        if not evidence_refs and task_id:
            evidence_refs = (f"cc-task:{task_id}:route_metadata",)
        items.append(
            {
                "task_id": task_id,
                "status": status,
                "evidence_refs": evidence_refs,
                "reasons": _string_tuple(metadata.get("hold_reasons"))
                or _string_tuple(metadata.get("validation_errors")),
            }
        )
    return tuple(items)


def parse_utc(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_optional_utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return parse_utc(value)
    except ValueError:
        return None


def _append_route_metadata_warnings(
    *,
    non_green: list[CapacityRoutingNonGreenState],
    summary: RouteMetadataSummary,
    source_available: bool,
    route_metadata_items: Sequence[Mapping[str, object]],
    route_metadata_generated_at: datetime | None,
    route_metadata_stale_after_s: int,
    now: datetime,
) -> None:
    if not source_available:
        non_green.append(
            CapacityRoutingNonGreenState(
                source="route_metadata",
                state="route_metadata_summary_unavailable",
                severity="unknown",
                summary="route metadata summary evidence is unavailable",
                evidence_refs=("planning-feed:dispatch.route_metadata_summary",),
            )
        )
    elif route_metadata_generated_at is None:
        non_green.append(
            CapacityRoutingNonGreenState(
                source="route_metadata",
                state="route_metadata_summary_timestamp_missing",
                severity="unknown",
                summary="route metadata summary timestamp is missing or unreadable",
                evidence_refs=("planning-feed:generated_at",),
            )
        )
    elif (now - route_metadata_generated_at).total_seconds() > route_metadata_stale_after_s:
        non_green.append(
            CapacityRoutingNonGreenState(
                source="route_metadata",
                state="route_metadata_summary_stale",
                severity="warning",
                summary="route metadata summary is stale",
                evidence_refs=("planning-feed:generated_at",),
            )
        )

    for status in ("hold", "malformed"):
        count = getattr(summary, status)
        if count <= 0:
            continue
        non_green.append(
            CapacityRoutingNonGreenState(
                source="route_metadata",
                state=f"route_metadata_{status}",
                severity="blocked",
                summary=f"{count} offered task(s) have {status} route metadata",
                evidence_refs=_route_metadata_evidence_refs(route_metadata_items, status),
            )
        )


def _registry_dashboard_state(
    *,
    registry_path: Path,
    now: datetime,
    non_green: list[CapacityRoutingNonGreenState],
) -> tuple[bool, int, list[CapacityRoutingRouteState]]:
    try:
        registry = load_platform_capability_registry(registry_path)
        result = check_registry_freshness(registry, now=now)
    except PlatformCapabilityRegistryError as exc:
        non_green.append(
            CapacityRoutingNonGreenState(
                source="platform_registry",
                state="platform_registry_unavailable",
                severity="unknown",
                summary=f"platform capability registry cannot be trusted: {exc}",
                evidence_refs=(_path_ref(registry_path),),
            )
        )
        return False, 0, []

    route_states: list[CapacityRoutingRouteState] = []
    for route in result.routes:
        if route.ok:
            continue
        refs = _registry_evidence_refs(registry_path, route.route_id, route.errors)
        summary = "; ".join(route.errors) or "route state is non-green"
        route_states.append(
            CapacityRoutingRouteState(
                route_id=route.route_id,
                supported=route.supported,
                summary=summary,
                evidence_refs=refs,
            )
        )
        non_green.append(
            CapacityRoutingNonGreenState(
                source="platform_registry",
                state=f"platform_route:{route.route_id}",
                severity="blocked" if route.supported else "unknown",
                summary=summary,
                evidence_refs=refs,
            )
        )

    return result.ok, result.route_count, route_states


def _quota_dashboard_state(
    *,
    ledger_path: Path,
    now: datetime,
    non_green: list[CapacityRoutingNonGreenState],
) -> dict[str, object]:
    try:
        ledger = load_quota_spend_ledger(ledger_path)
        dashboard = build_quota_spend_dashboard(ledger, now=now)
    except QuotaSpendLedgerError as exc:
        non_green.append(
            CapacityRoutingNonGreenState(
                source="quota_spend_ledger",
                state="quota_spend_ledger_unavailable",
                severity="unknown",
                summary=f"quota/spend ledger cannot be trusted: {exc}",
                evidence_refs=(_path_ref(ledger_path),),
            )
        )
        return {
            "quality_preserving_routes_available": "unknown",
            "blocked_quality_floor_reason": "quota/spend ledger unavailable",
            "subscription_quota_state": "unknown",
            "paid_api_budget_state": "unknown",
            "bootstrap_dependency_state": "none",
            "local_resource_state": "unknown",
            "current_capacity_pool": None,
            "provider_dependency_count": 0,
            "support_artifacts_waiting_for_review": 0,
            "budget_ledger_stale": True,
            "next_budget_review_at": None,
            "paid_api_route_eligible": False,
            "transition_budget_refs": (),
            "unreconciled_spend_refs": (),
            "provider_dependency_refs": (),
            "support_artifact_refs": (),
            "renewal_review_refs": (),
        }

    _append_quota_warnings(
        non_green=non_green, ledger=ledger, dashboard=dashboard, path=ledger_path
    )
    return {
        "quality_preserving_routes_available": dashboard.quality_preserving_routes_available.value,
        "blocked_quality_floor_reason": dashboard.blocked_quality_floor_reason,
        "subscription_quota_state": dashboard.subscription_quota_state.value,
        "paid_api_budget_state": dashboard.paid_api_budget_state.value,
        "bootstrap_dependency_state": dashboard.bootstrap_dependency_state.value,
        "local_resource_state": dashboard.local_resource_state.value,
        "current_capacity_pool": (
            dashboard.current_capacity_pool.value if dashboard.current_capacity_pool else None
        ),
        "provider_dependency_count": dashboard.provider_dependency_count,
        "support_artifacts_waiting_for_review": dashboard.support_artifacts_waiting_for_review,
        "budget_ledger_stale": dashboard.budget_ledger_stale,
        "next_budget_review_at": dashboard.next_budget_review_at,
        "paid_api_route_eligible": dashboard.paid_api_route_eligible,
        "transition_budget_refs": dashboard.transition_budget_refs,
        "unreconciled_spend_refs": dashboard.unreconciled_spend_refs,
        "provider_dependency_refs": dashboard.provider_dependency_refs,
        "support_artifact_refs": dashboard.support_artifact_refs,
        "renewal_review_refs": dashboard.renewal_review_refs,
    }


def _append_quota_warnings(
    *,
    non_green: list[CapacityRoutingNonGreenState],
    ledger: QuotaSpendLedger,
    dashboard: QuotaSpendDashboard,
    path: Path,
) -> None:
    if dashboard.quality_preserving_routes_available.value != "true":
        non_green.append(
            CapacityRoutingNonGreenState(
                source="quota_spend_ledger",
                state=(
                    "quality_preserving_routes_available:"
                    f"{dashboard.quality_preserving_routes_available.value}"
                ),
                severity="unknown",
                summary="quality-preserving route availability is not green",
                evidence_refs=tuple(ledger.evidence_refs) or (_path_ref(path),),
            )
        )

    for state in dashboard.non_green_states:
        non_green.append(
            CapacityRoutingNonGreenState(
                source="quota_spend_ledger",
                state=state,
                severity="blocked" if "expired" in state or "overdue" in state else "warning",
                summary=_quota_summary(state),
                evidence_refs=_quota_evidence_refs(state, ledger, dashboard, path),
            )
        )

    if dashboard.provider_dependency_count:
        non_green.append(
            CapacityRoutingNonGreenState(
                source="quota_spend_ledger",
                state="provider_dependencies_active",
                severity="warning",
                summary=(
                    f"{dashboard.provider_dependency_count} provider dependency record(s) "
                    "remain active"
                ),
                evidence_refs=dashboard.provider_dependency_refs,
            )
        )

    if dashboard.support_artifacts_waiting_for_review:
        non_green.append(
            CapacityRoutingNonGreenState(
                source="quota_spend_ledger",
                state="support_artifacts_waiting_for_review",
                severity="warning",
                summary=(
                    f"{dashboard.support_artifacts_waiting_for_review} support artifact(s) "
                    "are waiting for review and are not authoritative"
                ),
                evidence_refs=dashboard.support_artifact_refs,
            )
        )


def _coerce_route_metadata_summary(
    value: Mapping[str, object] | None,
) -> RouteMetadataSummary:
    if value is None:
        return RouteMetadataSummary()
    return RouteMetadataSummary(
        **{key: _coerce_nonnegative_int(value.get(key, 0)) for key in _ROUTE_METADATA_KEYS}
    )


def _route_metadata_evidence_refs(
    route_metadata_items: Sequence[Mapping[str, object]],
    status: str,
) -> tuple[str, ...]:
    refs: list[str] = []
    for item in route_metadata_items:
        if str(item.get("status", "")).strip() != status:
            continue
        item_refs = _string_tuple(item.get("evidence_refs"))
        task_id = str(item.get("task_id", "")).strip()
        if item_refs:
            refs.extend(item_refs)
        elif task_id:
            refs.append(f"cc-task:{task_id}:route_metadata")
    return _dedupe(refs) or (f"planning-feed:route_metadata_summary.{status}",)


def _registry_evidence_refs(
    registry_path: Path,
    route_id: str,
    errors: Sequence[str],
) -> tuple[str, ...]:
    base = f"{_path_ref(registry_path)}:{route_id}"
    refs = [base]
    refs.extend(f"{base}:{_slugify(error)}" for error in errors)
    return _dedupe(refs)


def _quota_evidence_refs(
    state: str,
    ledger: QuotaSpendLedger,
    dashboard: QuotaSpendDashboard,
    path: Path,
) -> tuple[str, ...]:
    if state == "budget_ledger_stale":
        return (f"{_path_ref(path)}:captured_at",)
    if state.startswith("paid_api_budget_state"):
        return dashboard.transition_budget_refs or tuple(ledger.evidence_refs)
    if state.startswith("bootstrap_dependency_state"):
        return dashboard.provider_dependency_refs or dashboard.transition_budget_refs
    if state.startswith("subscription_quota_state"):
        return tuple(snapshot.snapshot_id for snapshot in ledger.quota_snapshots) or tuple(
            ledger.evidence_refs
        )
    if state.startswith("local_resource_state"):
        return (f"{_path_ref(path)}:local_resource_state",)
    if state == "spend_reconciliation_overdue":
        return dashboard.unreconciled_spend_refs
    return tuple(ledger.evidence_refs) or (_path_ref(path),)


def _quota_summary(state: str) -> str:
    summaries = {
        "budget_ledger_stale": "budget ledger is stale",
        "spend_reconciliation_overdue": "spend reconciliation is overdue",
    }
    if state in summaries:
        return summaries[state]
    if ":" in state:
        key, _, value = state.partition(":")
        return f"{key.replace('_', ' ')} is {value}"
    return state.replace("_", " ")


def _string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, Sequence):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _coerce_nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _coerce_now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(tz=UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _path_ref(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _slugify(value: str) -> str:
    lowered = value.lower().strip()
    return re.sub(r"[^a-z0-9_.:-]+", "-", lowered).strip("-")[:120] or "non-green"


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return tuple(out)


__all__ = [
    "CapacityRoutingDashboard",
    "CapacityRoutingNonGreenState",
    "CapacityRoutingRouteState",
    "RouteMetadataSummary",
    "build_capacity_routing_dashboard",
    "parse_optional_utc",
    "parse_utc",
    "route_metadata_items_from_planning_queue",
]
