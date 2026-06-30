from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from shared.quota_spend_ledger import (
    DEFAULT_QUOTA_SPEND_LEDGER_LIVE,
    QUOTA_SPEND_LEDGER_LIVE_ENV,
    CapacityPool,
    LocalResourceState,
    PaidRouteRequest,
    QuotaSpendLedger,
    SubscriptionQuotaState,
    evaluate_paid_route_eligibility,
    load_quota_spend_ledger,
    load_quota_spend_ledger_resolved,
    subscription_quota_state_for_route,
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


MODEL_CAPABILITIES: dict[str, CapabilityDescriptor] = {
    "opus": CapabilityDescriptor(
        capability_id="cctv.model.opus",
        route_id="litellm.anthropic.claude-opus-4",
        provider="anthropic",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="frontier-full",
    ),
    "balanced": CapabilityDescriptor(
        capability_id="cctv.model.balanced",
        route_id="litellm.anthropic.claude-sonnet-4",
        provider="anthropic",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="frontier-fast",
    ),
    "gemini-3-pro": CapabilityDescriptor(
        capability_id="cctv.model.gemini-3-pro",
        route_id="litellm.google.gemini-3-pro",
        provider="google",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="frontier-fast",
    ),
    "web-research": CapabilityDescriptor(
        capability_id="cctv.model.web-research",
        route_id="litellm.perplexity.web-research",
        provider="perplexity",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="web-research",
    ),
    "mistral-large": CapabilityDescriptor(
        capability_id="cctv.model.mistral-large",
        route_id="litellm.mistral.mistral-large",
        provider="mistral",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="frontier-fast",
    ),
    "deepseek": CapabilityDescriptor(
        capability_id="cctv.model.deepseek",
        route_id="litellm.deepseek.deepseek",
        provider="deepseek",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="coding",
    ),
    "glm": CapabilityDescriptor(
        capability_id="cctv.model.glm",
        route_id="litellm.z_ai.glm",
        provider="z_ai",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="coding",
    ),
    "local-fast": CapabilityDescriptor(
        capability_id="cctv.model.local-fast",
        route_id="litellm.local.command-r-35b",
        provider="tabbyapi",
        capacity_pool=CapacityPool.LOCAL_COMPUTE,
        profile="local",
        quality_floor="capable_sufficient",
    ),
    "appendix-fast": CapabilityDescriptor(
        capability_id="cctv.model.appendix-fast",
        route_id="litellm.local.command-r-35b",
        provider="tabbyapi",
        capacity_pool=CapacityPool.LOCAL_COMPUTE,
        profile="local",
        quality_floor="capable_sufficient",
    ),
}

TOOL_CAPABILITIES: dict[str, CapabilityDescriptor] = {
    "web_verify": CapabilityDescriptor(
        capability_id="cctv.tool.web_verify",
        route_id="litellm.perplexity.web-research",
        provider="perplexity",
        capacity_pool=CapacityPool.API_PAID_SPEND,
        profile="web-research",
        estimated_cost_usd=Decimal("0.01"),
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


def admit_model_alias(
    model_alias: str, *, now: datetime | None = None
) -> CapabilityAdmissionReceipt:
    from agents.deliberative_council.members import normalize_model_alias

    alias = normalize_model_alias(model_alias)
    descriptor = MODEL_CAPABILITIES.get(alias)
    if descriptor is None:
        return _receipt_for_missing_descriptor(f"cctv.model.{alias}", alias)
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


def admissions_for_model_aliases(
    aliases: tuple[str, ...],
    *,
    now: datetime | None = None,
) -> tuple[CapabilityAdmissionReceipt, ...]:
    return tuple(admit_model_alias(alias, now=now) for alias in aliases)


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
    if eligibility.eligible:
        return _build_receipt(
            descriptor,
            action="admitted",
            reason_codes=(eligibility.state,),
            spend_evidence_refs=eligibility.evidence_refs,
            ledger=ledger,
        )
    return _build_receipt(
        descriptor,
        action="refused",
        reason_codes=tuple(_reason_code(reason) for reason in eligibility.blocking_reasons)
        or (eligibility.state,),
        spend_evidence_refs=eligibility.evidence_refs,
        ledger=ledger,
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
    )


def _admit_local_route(
    descriptor: CapabilityDescriptor,
    ledger: QuotaSpendLedger,
    now: datetime,
) -> CapabilityAdmissionReceipt:
    snapshots = tuple(
        snapshot
        for snapshot in ledger.quota_snapshots
        if snapshot.capacity_pool is CapacityPool.LOCAL_COMPUTE
        and (
            snapshot.route_id == descriptor.route_id
            or descriptor.route_id == "local_tool.local.worker"
        )
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
    admitted = not reasons
    return _build_receipt(
        descriptor,
        action="admitted" if admitted else "refused",
        reason_codes=tuple(reasons) or ("local_resource_green",),
        quota_evidence_refs=quota_refs,
        resource_evidence_refs=(f"quota.local_resource_state:{ledger.local_resource_state.value}",),
        ledger=ledger,
    )


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
    )


def _build_receipt(
    descriptor: CapabilityDescriptor,
    *,
    action: Literal["admitted", "refused"],
    reason_codes: tuple[str, ...],
    quota_evidence_refs: tuple[str, ...] = (),
    spend_evidence_refs: tuple[str, ...] = (),
    resource_evidence_refs: tuple[str, ...] = (),
    ledger: QuotaSpendLedger | None = None,
) -> CapabilityAdmissionReceipt:
    payload = {
        "capability_id": descriptor.capability_id,
        "route_id": descriptor.route_id,
        "provider": descriptor.provider,
        "capacity_pool": descriptor.capacity_pool.value,
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
    return load_quota_spend_ledger_resolved(live_path=live_path).ledger


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
