from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.frontmatter import parse_frontmatter
from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
    PlatformCapabilityRegistryError,
    RouteState,
    load_platform_capability_registry,
    normalize_route_id,
)
from shared.quota_spend_ledger import (
    DEFAULT_QUOTA_SPEND_LEDGER_LIVE,
    QUOTA_SPEND_LEDGER_LIVE_ENV,
    CapacityPool,
    LocalResourceState,
    PaidRouteRequest,
    QuotaSpendLedger,
    QuotaSpendLedgerError,
    SubscriptionQuotaState,
    evaluate_paid_route_eligibility,
    load_quota_spend_ledger,
    load_quota_spend_ledger_resolved,
    subscription_quota_state_for_route,
)

PLATFORM_CAPABILITY_REGISTRY_ENV = "HAPAX_PLATFORM_CAPABILITY_REGISTRY"

_capability_admission_events: ContextVar[list[CapabilityAdmissionReceipt] | None] = ContextVar(
    "cctv_capability_admission_events", default=None
)


class CapabilityAdmissionError(RuntimeError):
    """Raised before a governed resource is invoked without an admitting receipt."""


class _AdmissionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CapabilityAdmissionReceipt(_AdmissionModel):
    receipt_schema: Literal[1] = 1
    receipt_id: str
    receipt_ref: str
    capability_id: str
    route_id: str
    provider: str
    capacity_pool: str
    profile: str = "unknown"
    task_class: str = "unknown"
    quality_floor: str = "unknown"
    estimated_cost_usd: str = "0"
    evaluated_at: datetime | None = None
    authority_task_id: str | None = None
    authority_case: str | None = None
    authority_item: str | None = None
    authority_parent_spec: str | None = None
    authority_source_ref: str | None = None
    admission_action: Literal["admitted", "refused"]
    admitted: bool
    reason_codes: tuple[str, ...] = Field(default=())
    quota_evidence_refs: tuple[str, ...] = Field(default=())
    spend_evidence_refs: tuple[str, ...] = Field(default=())
    resource_evidence_refs: tuple[str, ...] = Field(default=())
    receipt_refs: tuple[str, ...] = Field(default=())
    ledger_id: str | None = None
    ledger_captured_at: datetime | None = None

    def short_reason(self) -> str:
        return ",".join(self.reason_codes) if self.reason_codes else self.admission_action


@dataclass(frozen=True)
class CapabilityDescriptor:
    capability_id: str
    route_id: str
    provider: str
    capacity_pool: CapacityPool
    profile: str
    task_class: str = "research"
    quality_floor: str = "frontier_required"
    estimated_cost_usd: Decimal = Decimal("0.01")
    platform_route_id: str | None = None


@dataclass(frozen=True)
class CapabilityAuthorityContext:
    task_id: str | None = None
    authority_case: str | None = None
    authority_item: str | None = None
    parent_spec: str | None = None
    source_ref: str | None = None


# Keep these descriptors aligned with the routes invoked by members.model_route_for_alias().
# Recheck with:
# uv run pytest tests/agents/test_deliberative_council/test_tools.py::TestBuildMember::test_descriptor_route_matches_invoked_litellm_route -q
MODEL_CAPABILITIES: dict[str, CapabilityDescriptor] = {
    "opus": CapabilityDescriptor(
        capability_id="cctv.model.opus",
        route_id="claude-opus",
        provider="anthropic",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="frontier-full",
        platform_route_id="api.headless.provider_gateway",
    ),
    "balanced": CapabilityDescriptor(
        capability_id="cctv.model.balanced",
        route_id="claude-sonnet",
        provider="anthropic",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="frontier-fast",
        platform_route_id="api.headless.provider_gateway",
    ),
    "gemini-3-pro": CapabilityDescriptor(
        capability_id="cctv.model.gemini-3-pro",
        route_id="gemini-pro",
        provider="google",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="frontier-fast",
        platform_route_id="api.headless.provider_gateway",
    ),
    "web-research": CapabilityDescriptor(
        capability_id="cctv.model.web-research",
        route_id="web-research",
        provider="perplexity",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="web-research",
        platform_route_id="api.headless.provider_gateway",
    ),
    "mistral-large": CapabilityDescriptor(
        capability_id="cctv.model.mistral-large",
        route_id="mistral-large",
        provider="mistral",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="frontier-fast",
        platform_route_id="api.headless.provider_gateway",
    ),
    "deepseek": CapabilityDescriptor(
        capability_id="cctv.model.deepseek",
        route_id="deepseek",
        provider="deepseek",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="coding",
        platform_route_id="api.headless.provider_gateway",
    ),
    "glm": CapabilityDescriptor(
        capability_id="cctv.model.glm",
        route_id="glm",
        provider="z_ai",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="coding",
        platform_route_id="api.headless.provider_gateway",
    ),
    "local-fast": CapabilityDescriptor(
        capability_id="cctv.model.local-fast",
        route_id="local-fast",
        provider="tabbyapi",
        capacity_pool=CapacityPool.LOCAL_COMPUTE,
        profile="local",
        quality_floor="capable_sufficient",
    ),
    "appendix-fast": CapabilityDescriptor(
        capability_id="cctv.model.appendix-fast",
        route_id="appendix-fast",
        provider="tabbyapi",
        capacity_pool=CapacityPool.LOCAL_COMPUTE,
        profile="local",
        quality_floor="capable_sufficient",
    ),
}

TOOL_CAPABILITIES: dict[str, CapabilityDescriptor] = {
    "web_verify": CapabilityDescriptor(
        capability_id="cctv.tool.web_verify",
        route_id="web-research",
        provider="perplexity",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="web-research",
        estimated_cost_usd=Decimal("0.01"),
        platform_route_id="api.headless.provider_gateway",
    ),
    "qdrant_lookup": CapabilityDescriptor(
        capability_id="cctv.tool.qdrant_lookup",
        route_id="local_tool.local.worker",
        provider="local",
        capacity_pool=CapacityPool.LOCAL_COMPUTE,
        profile="local",
        quality_floor="capable_sufficient",
        estimated_cost_usd=Decimal("0.00"),
    ),
}

LOCAL_ROUTE_SNAPSHOT_ALIASES: dict[str, frozenset[str]] = {
    "local-fast": frozenset({"local-fast", "litellm.local.command-r-35b"}),
    "local_tool.local.worker": frozenset(
        {"local_tool.local.worker", "local-fast", "litellm.local.command-r-35b"}
    ),
}


def admit_model_alias(
    model_alias: str,
    *,
    invoked_route_id: str | None = None,
    now: datetime | None = None,
) -> CapabilityAdmissionReceipt:
    from agents.deliberative_council.members import normalize_model_alias

    alias = normalize_model_alias(model_alias)
    descriptor = MODEL_CAPABILITIES.get(alias)
    if descriptor is None:
        return _receipt_for_missing_descriptor(f"cctv.model.{alias}", alias)
    if invoked_route_id and invoked_route_id != descriptor.route_id:
        descriptor = CapabilityDescriptor(
            capability_id=descriptor.capability_id,
            route_id=invoked_route_id,
            provider=descriptor.provider,
            capacity_pool=descriptor.capacity_pool,
            profile=descriptor.profile,
            task_class=descriptor.task_class,
            quality_floor=descriptor.quality_floor,
            estimated_cost_usd=descriptor.estimated_cost_usd,
            platform_route_id=descriptor.platform_route_id,
        )
    return admit_capability(descriptor, now=now)


def admit_tool(tool_name: str, *, now: datetime | None = None) -> CapabilityAdmissionReceipt:
    descriptor = TOOL_CAPABILITIES.get(tool_name)
    if descriptor is None:
        return _receipt_for_missing_descriptor(f"cctv.tool.{tool_name}", tool_name)
    return admit_capability(descriptor, now=now)


def admit_capability(
    descriptor: CapabilityDescriptor,
    *,
    now: datetime | None = None,
) -> CapabilityAdmissionReceipt:
    checked_at = _admission_now(now)
    try:
        ledger = _load_ledger()
    except Exception as exc:
        return _build_receipt(
            descriptor,
            action="refused",
            reason_codes=(f"quota_spend_ledger_unavailable:{type(exc).__name__}",),
            evaluated_at=checked_at,
        )

    if descriptor.capacity_pool is CapacityPool.API_PAID_SPEND:
        return _admit_paid_route(descriptor, ledger, checked_at)
    if descriptor.capacity_pool is CapacityPool.SUBSCRIPTION_QUOTA:
        return _admit_subscription_route(descriptor, ledger, checked_at)
    if descriptor.capacity_pool is CapacityPool.LOCAL_COMPUTE:
        return _admit_local_route(descriptor, ledger, checked_at)
    return _build_receipt(
        descriptor,
        action="refused",
        reason_codes=(f"unsupported_capacity_pool:{descriptor.capacity_pool.value}",),
        ledger=ledger,
        evaluated_at=checked_at,
    )


def require_member_admission(member: Any) -> CapabilityAdmissionReceipt:
    admission = member_capability_admission(member)
    if admission is None:
        raise CapabilityAdmissionError(
            "capability_admission_missing; "
            "next_action=build the member with build_member() so route/resource admission "
            "is attached before provider invocation"
        )
    if not admission.admitted:
        raise CapabilityAdmissionError(
            f"capability_admission_refused capability_id={admission.capability_id} "
            f"route_id={admission.route_id} reason_codes={admission.short_reason()} "
            f"receipt_refs={','.join(admission.receipt_refs)} "
            "next_action=refresh the quota/spend ledger or change route before retrying "
            "provider invocation"
        )
    return admission


def member_capability_admission(member: Any) -> CapabilityAdmissionReceipt | None:
    admission = getattr(member, "_cctv_capability_admission", None)
    return admission if isinstance(admission, CapabilityAdmissionReceipt) else None


def route_resource_admission_state(admissions: tuple[CapabilityAdmissionReceipt, ...]) -> str:
    if not admissions:
        return "missing"
    if all(admission.admitted for admission in admissions):
        return "admitted"
    if any(admission.admitted for admission in admissions):
        return "partial_admitted"
    return "refused"


def capability_receipt_refs(admissions: tuple[CapabilityAdmissionReceipt, ...]) -> tuple[str, ...]:
    refs: list[str] = []
    for admission in admissions:
        refs.extend(admission.receipt_refs)
    return tuple(dict.fromkeys(refs))


def unique_capability_admissions(
    admissions: tuple[CapabilityAdmissionReceipt, ...],
) -> tuple[CapabilityAdmissionReceipt, ...]:
    unique: dict[tuple[str, str, str, str], CapabilityAdmissionReceipt] = {}
    for admission in admissions:
        key = (
            admission.receipt_ref,
            admission.capability_id,
            admission.route_id,
            admission.admission_action,
        )
        unique.setdefault(key, admission)
    return tuple(unique.values())


@contextmanager
def capability_admission_event_scope(
    events: list[CapabilityAdmissionReceipt],
) -> Iterator[None]:
    token = _capability_admission_events.set(events)
    try:
        yield
    finally:
        _capability_admission_events.reset(token)


def record_capability_admission(admission: CapabilityAdmissionReceipt | None) -> None:
    if admission is None:
        return
    events = _capability_admission_events.get()
    if events is not None:
        events.append(admission)


def tool_call_log_label(tool_name: str) -> str:
    descriptor = TOOL_CAPABILITIES.get(tool_name)
    if descriptor is None:
        return tool_name
    return f"{tool_name}[capability_id={descriptor.capability_id}]"


def tool_result_prefix(admission: CapabilityAdmissionReceipt) -> str:
    refs = ",".join(admission.receipt_refs)
    reasons = ",".join(admission.reason_codes)
    return (
        f"[capability_admission capability_id={admission.capability_id} "
        f"route_id={admission.route_id} action={admission.admission_action} "
        f"receipt_refs={refs} reason_codes={reasons}] "
    )


def _admit_paid_route(
    descriptor: CapabilityDescriptor,
    ledger: QuotaSpendLedger,
    now: datetime,
) -> CapabilityAdmissionReceipt:
    request = PaidRouteRequest(
        route_id=descriptor.route_id,
        provider=descriptor.provider,
        profile=descriptor.profile,
        task_class=descriptor.task_class,
        quality_floor=descriptor.quality_floor,
        estimated_cost_usd=descriptor.estimated_cost_usd,
        capacity_pool=descriptor.capacity_pool,
    )
    eligibility = evaluate_paid_route_eligibility(ledger, request, now=now)
    platform_route_id = descriptor.platform_route_id or descriptor.route_id
    platform_reasons, platform_refs = _platform_route_block_reasons(
        platform_route_id,
        now=now,
        required=True,
    )
    if eligibility.eligible and not platform_reasons:
        return _build_receipt(
            descriptor,
            action="admitted",
            reason_codes=(eligibility.state,),
            spend_evidence_refs=eligibility.evidence_refs,
            resource_evidence_refs=platform_refs,
            ledger=ledger,
            evaluated_at=now,
        )
    return _build_receipt(
        descriptor,
        action="refused",
        reason_codes=(
            tuple(_reason_code(reason) for reason in eligibility.blocking_reasons)
            or (eligibility.state,)
        )
        + platform_reasons,
        spend_evidence_refs=eligibility.evidence_refs,
        resource_evidence_refs=platform_refs,
        ledger=ledger,
        evaluated_at=now,
    )


def _admit_subscription_route(
    descriptor: CapabilityDescriptor,
    ledger: QuotaSpendLedger,
    now: datetime,
) -> CapabilityAdmissionReceipt:
    state, evidence_refs = subscription_quota_state_for_route(ledger, descriptor.route_id, now=now)
    admitted = state is SubscriptionQuotaState.FRESH
    return _build_receipt(
        descriptor,
        action="admitted" if admitted else "refused",
        reason_codes=(f"subscription_quota_state:{state.value}",),
        quota_evidence_refs=evidence_refs,
        ledger=ledger,
        evaluated_at=now,
    )


def _admit_local_route(
    descriptor: CapabilityDescriptor,
    ledger: QuotaSpendLedger,
    now: datetime,
) -> CapabilityAdmissionReceipt:
    admitted_snapshot_routes = LOCAL_ROUTE_SNAPSHOT_ALIASES.get(
        descriptor.route_id, frozenset({descriptor.route_id})
    )
    snapshots = tuple(
        snapshot
        for snapshot in ledger.quota_snapshots
        if snapshot.capacity_pool is CapacityPool.LOCAL_COMPUTE
        and snapshot.route_id in admitted_snapshot_routes
    )
    quota_refs = tuple(ref for snapshot in snapshots for ref in snapshot.evidence_refs)
    fresh_snapshot = any(
        snapshot.subscription_quota_state is SubscriptionQuotaState.FRESH
        and (snapshot.fresh_until is None or snapshot.fresh_until > now)
        for snapshot in snapshots
    )
    resource_green = ledger.local_resource_state is LocalResourceState.GREEN
    reasons: list[str] = []
    if not snapshots:
        reasons.append("local_resource_snapshot_missing")
    elif not fresh_snapshot:
        reasons.append("local_resource_snapshot_not_fresh")
    if not resource_green:
        reasons.append(f"local_resource_state:{ledger.local_resource_state.value}")
    platform_reasons, platform_refs = _platform_route_block_reasons(descriptor.route_id, now=now)
    reasons.extend(platform_reasons)
    admitted = not reasons
    return _build_receipt(
        descriptor,
        action="admitted" if admitted else "refused",
        reason_codes=tuple(reasons) or ("local_resource_green",),
        quota_evidence_refs=quota_refs,
        resource_evidence_refs=tuple(
            dict.fromkeys(
                (
                    f"quota.local_resource_state:{ledger.local_resource_state.value}",
                    *platform_refs,
                )
            )
        ),
        ledger=ledger,
        evaluated_at=now,
    )


def _platform_route_block_reasons(
    route_id: str,
    *,
    now: datetime,
    required: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    registry_path = Path(
        os.environ.get(PLATFORM_CAPABILITY_REGISTRY_ENV, str(PLATFORM_CAPABILITY_REGISTRY))
    ).expanduser()
    try:
        registry = load_platform_capability_registry(registry_path, now=now)
    except PlatformCapabilityRegistryError as exc:
        return (
            (f"platform_capability_registry_unavailable:{type(exc).__name__}",),
            (),
        )

    route = registry.route_map().get(normalize_route_id(route_id))
    if route is None:
        if required:
            return ((f"platform_route_missing:{route_id}",), ())
        return (), ()

    refs = (
        f"platform-capability-registry:{route.route_id}",
        *route.freshness.evidence.all_evidence_refs(),
    )
    reasons: list[str] = []
    if route.route_state is RouteState.BLOCKED:
        reasons.extend(route.blocked_reasons or ["platform_route_state_blocked"])
    reasons.extend(route.freshness.evidence.all_blocked_reasons())
    return tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(refs))


def _receipt_for_missing_descriptor(capability_id: str, name: str) -> CapabilityAdmissionReceipt:
    descriptor = CapabilityDescriptor(
        capability_id=capability_id,
        route_id=f"missing.{name}",
        provider="unknown",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="unknown",
    )
    return _build_receipt(
        descriptor,
        action="refused",
        reason_codes=("capability_descriptor_missing",),
        evaluated_at=_admission_now(None),
    )


def _clean_authority_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip("'\"")
    if text.lower() in {"", "null", "none", "~", "[]", "unassigned"}:
        return None
    return text


def _active_task_note(task_id: str) -> Path | None:
    root = Path(
        os.environ.get(
            "HAPAX_CC_TASK_ROOT",
            str(Path.home() / "Documents" / "Personal" / "20-projects" / "hapax-cc-tasks"),
        )
    ).expanduser()
    active = root / "active"
    exact = active / f"{task_id}.md"
    if exact.exists():
        return exact
    try:
        matches = sorted(active.glob(f"{task_id}-*.md"))
    except OSError:
        return None
    return matches[0] if matches else None


def _caller_authority_context() -> CapabilityAuthorityContext:
    task_id = _clean_authority_value(os.environ.get("HAPAX_METHODOLOGY_DISPATCH_TASK"))
    if task_id is None:
        return CapabilityAuthorityContext()
    note = _active_task_note(task_id)
    if note is None:
        return CapabilityAuthorityContext(
            task_id=task_id, source_ref="env:HAPAX_METHODOLOGY_DISPATCH_TASK"
        )
    frontmatter, _body = parse_frontmatter(note)
    return CapabilityAuthorityContext(
        task_id=task_id,
        authority_case=_clean_authority_value(frontmatter.get("authority_case")),
        authority_item=_clean_authority_value(frontmatter.get("authority_item"))
        or _clean_authority_value(frontmatter.get("slice_id")),
        parent_spec=_clean_authority_value(frontmatter.get("parent_spec")),
        source_ref=str(note),
    )


def _estimated_cost_ref(value: Decimal) -> str:
    return format(value, "f")


def _build_receipt(
    descriptor: CapabilityDescriptor,
    *,
    action: Literal["admitted", "refused"],
    reason_codes: tuple[str, ...],
    quota_evidence_refs: tuple[str, ...] = (),
    spend_evidence_refs: tuple[str, ...] = (),
    resource_evidence_refs: tuple[str, ...] = (),
    ledger: QuotaSpendLedger | None = None,
    evaluated_at: datetime,
) -> CapabilityAdmissionReceipt:
    authority = _caller_authority_context()
    estimated_cost_usd = _estimated_cost_ref(descriptor.estimated_cost_usd)
    evaluated_at_ref = evaluated_at.isoformat().replace("+00:00", "Z")
    payload = {
        "capability_id": descriptor.capability_id,
        "route_id": descriptor.route_id,
        "provider": descriptor.provider,
        "capacity_pool": descriptor.capacity_pool.value,
        "profile": descriptor.profile,
        "task_class": descriptor.task_class,
        "quality_floor": descriptor.quality_floor,
        "estimated_cost_usd": estimated_cost_usd,
        "evaluated_at": evaluated_at_ref,
        "authority_task_id": authority.task_id,
        "authority_case": authority.authority_case,
        "authority_item": authority.authority_item,
        "authority_parent_spec": authority.parent_spec,
        "authority_source_ref": authority.source_ref,
        "admission_action": action,
        "reason_codes": list(reason_codes),
        "quota_evidence_refs": list(quota_evidence_refs),
        "spend_evidence_refs": list(spend_evidence_refs),
        "resource_evidence_refs": list(resource_evidence_refs),
        "ledger_id": ledger.ledger_id if ledger is not None else None,
        "ledger_captured_at": (
            ledger.captured_at.isoformat().replace("+00:00", "Z") if ledger is not None else None
        ),
    }
    receipt_id = (
        "cctv-"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
    )
    receipt_ref = f"cctv-capability-admission:{receipt_id}"
    receipt_refs = tuple(
        dict.fromkeys(
            (
                receipt_ref,
                *quota_evidence_refs,
                *spend_evidence_refs,
                *resource_evidence_refs,
            )
        )
    )
    return CapabilityAdmissionReceipt(
        receipt_id=receipt_id,
        receipt_ref=receipt_ref,
        capability_id=descriptor.capability_id,
        route_id=descriptor.route_id,
        provider=descriptor.provider,
        capacity_pool=descriptor.capacity_pool.value,
        profile=descriptor.profile,
        task_class=descriptor.task_class,
        quality_floor=descriptor.quality_floor,
        estimated_cost_usd=estimated_cost_usd,
        evaluated_at=evaluated_at,
        authority_task_id=authority.task_id,
        authority_case=authority.authority_case,
        authority_item=authority.authority_item,
        authority_parent_spec=authority.parent_spec,
        authority_source_ref=authority.source_ref,
        admission_action=action,
        admitted=action == "admitted",
        reason_codes=reason_codes,
        quota_evidence_refs=quota_evidence_refs,
        spend_evidence_refs=spend_evidence_refs,
        resource_evidence_refs=resource_evidence_refs,
        receipt_refs=receipt_refs,
        ledger_id=ledger.ledger_id if ledger is not None else None,
        ledger_captured_at=ledger.captured_at if ledger is not None else None,
    )


def _load_ledger() -> QuotaSpendLedger:
    explicit = os.environ.get("HAPAX_CCTV_QUOTA_SPEND_LEDGER") or os.environ.get(
        "HAPAX_QUOTA_SPEND_LEDGER"
    )
    if explicit:
        return load_quota_spend_ledger(Path(explicit).expanduser())
    live_path = Path(
        os.environ.get(QUOTA_SPEND_LEDGER_LIVE_ENV, str(DEFAULT_QUOTA_SPEND_LEDGER_LIVE))
    ).expanduser()
    if not live_path.exists():
        raise QuotaSpendLedgerError(
            f"live quota/spend ledger missing: {live_path}; "
            "next_action=run quota telemetry refresh or set HAPAX_CCTV_QUOTA_SPEND_LEDGER "
            "to a fresh governed ledger"
        )
    resolved = load_quota_spend_ledger_resolved(live_path=live_path)
    if resolved.source != "live":
        detail = f"; live_error={resolved.live_error}" if resolved.live_error else ""
        raise QuotaSpendLedgerError(
            f"live quota/spend ledger unavailable; refusing fixture fallback at "
            f"{resolved.path}{detail}; next_action=repair live quota telemetry before "
            "retrying governed capability admission"
        )
    return resolved.ledger


def _admission_now(now: datetime | None) -> datetime:
    if now is not None:
        return now.astimezone(UTC)
    raw = os.environ.get("HAPAX_CCTV_CAPABILITY_ADMISSION_NOW") or os.environ.get(
        "HAPAX_CAPACITY_ROUTING_NOW"
    )
    if raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    return datetime.now(UTC).replace(microsecond=0)


def _reason_code(value: str) -> str:
    text = value.strip().lower().replace("/", "_")
    return "_".join(part for part in text.replace("-", "_").split() if part) or "unknown"
