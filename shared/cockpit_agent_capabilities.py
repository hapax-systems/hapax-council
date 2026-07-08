"""Cockpit agent command capability inventory and admission.

The Logos cockpit launches agent CLIs directly. This module keeps that surface
machine-visible and fails closed for LLM-backed invocations before the subprocess
can reach a provider.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from shared.platform_capability_receipts import (
    DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR,
    PLATFORM_CAPABILITY_RECEIPT_DIR_ENV,
)
from shared.platform_capability_registry import (
    PLATFORM_CAPABILITY_REGISTRY,
    PlatformCapabilityRegistryError,
    RouteState,
    check_registry_freshness,
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
)

COCKPIT_QUOTA_SPEND_LEDGER_ENV = "HAPAX_COCKPIT_QUOTA_SPEND_LEDGER"
COCKPIT_PLATFORM_CAPABILITY_REGISTRY_ENV = "HAPAX_COCKPIT_PLATFORM_CAPABILITY_REGISTRY"
COCKPIT_ADMISSION_NOW_ENV = "HAPAX_COCKPIT_CAPABILITY_ADMISSION_NOW"


class CockpitCommandClass(StrEnum):
    DETERMINISTIC_EVIDENCE = "deterministic_evidence"
    LLM_BACKED_MODEL_USE = "llm_backed_model_use"
    RUNTIME_MUTATION = "runtime_mutation"
    PUBLIC_EGRESS = "public_egress"
    MIXED_ORCHESTRATING = "mixed_orchestrating"


class CockpitAdmissionError(RuntimeError):
    """Raised before a cockpit command can invoke a model without admission."""


@dataclass(frozen=True)
class CockpitSupplyLeaf:
    capability_id: str
    route_id: str
    platform_route_id: str
    provider: str
    model_alias: str | None
    model_route: str | None
    capacity_pool: str
    profile: str
    task_class: str = "agent-dispatch"
    quality_floor: str = "frontier_required"
    estimated_cost_usd: str = "0.01"
    context_window: str = "standard"
    tool_refs: tuple[str, ...] = ()
    authority_surfaces: tuple[str, ...] = ("provider_spend",)
    resource_pools: tuple[str, ...] = ("api_paid_spend",)
    quota_source: str = "ledger"
    cost_source: str = "ledger"
    spend_authority_required: bool = True
    public_egress_authority_required: bool = False


@dataclass(frozen=True)
class CockpitAgentCapability:
    agent_id: str
    display_name: str
    classifications: tuple[CockpitCommandClass, ...]
    evidence_only_waiver: str | None = None
    supply_leaves: tuple[CockpitSupplyLeaf, ...] = ()
    receipt_classes: tuple[str, ...] = ()
    runtime_mutation_flags: tuple[str, ...] = ()
    public_egress_flags: tuple[str, ...] = ()
    llm_flag_overlays: dict[str, tuple[CockpitSupplyLeaf, ...]] | None = None

    @property
    def requires_llm_admission(self) -> bool:
        return bool(self.supply_leaves)

    @property
    def spend_authority_required(self) -> bool:
        return any(leaf.spend_authority_required for leaf in self.supply_leaves)

    @property
    def public_egress_authority_required(self) -> bool:
        return any(leaf.public_egress_authority_required for leaf in self.supply_leaves)


@dataclass(frozen=True)
class CockpitAdmissionReceipt:
    receipt_id: str
    receipt_ref: str
    capability_id: str
    route_id: str
    platform_route_id: str
    provider: str
    model_alias: str | None
    model_route: str | None
    capacity_pool: str
    admission_action: str
    admitted: bool
    reason_codes: tuple[str, ...]
    quota_evidence_refs: tuple[str, ...] = ()
    spend_evidence_refs: tuple[str, ...] = ()
    resource_evidence_refs: tuple[str, ...] = ()
    receipt_refs: tuple[str, ...] = ()

    def short_reason(self) -> str:
        return ",".join(self.reason_codes) if self.reason_codes else self.admission_action


@dataclass(frozen=True)
class CockpitInvocationAdmission:
    agent_id: str
    display_name: str
    requires_admission: bool
    admitted: bool
    reason_codes: tuple[str, ...]
    receipts: tuple[CockpitAdmissionReceipt, ...] = ()
    evidence_only_waiver: str | None = None


@dataclass(frozen=True)
class _FlagArg:
    key: str
    value: str | None = None


_ALIAS_TO_MODEL_ROUTE = {
    "fast": "gemini-flash",
    "balanced": "claude-sonnet",
    "claude-opus": "claude-opus",
    "opus": "claude-opus",
    "web-scout": "web-scout",
    "web-deep": "web-deep",
    "local-fast": "local-fast",
    "appendix-fast": "appendix-fast",
    "coding": "coding",
}

_MODEL_ROUTE_TO_PROVIDER = {
    "gemini-flash": "google",
    "claude-sonnet": "anthropic",
    "claude-opus": "anthropic",
    "web-scout": "perplexity",
    "web-deep": "perplexity",
    "local-fast": "tabbyapi",
    "appendix-fast": "tabbyapi",
    "coding": "local",
}

_LOCAL_MODEL_ROUTES = frozenset({"local-fast", "appendix-fast", "coding"})


def _agent_id(name: str) -> str:
    return name.strip().replace("-", "_")


def _display_name(agent_id: str) -> str:
    return agent_id.replace("_", "-")


def _model_leaf(
    agent_id: str,
    alias: str,
    *,
    leaf_name: str | None = None,
    context_window: str = "standard",
    tool_refs: tuple[str, ...] = (),
    public_egress: bool = False,
) -> CockpitSupplyLeaf:
    model_route = _ALIAS_TO_MODEL_ROUTE.get(alias, alias)
    provider = _MODEL_ROUTE_TO_PROVIDER.get(model_route, "unknown")
    local = model_route in _LOCAL_MODEL_ROUTES
    capacity_pool = CapacityPool.LOCAL_COMPUTE.value if local else CapacityPool.API_PAID_SPEND.value
    return CockpitSupplyLeaf(
        capability_id=f"cockpit.agent.{agent_id}.{leaf_name or alias}",
        route_id=model_route,
        platform_route_id="local_tool.local.worker" if local else "api.headless.provider_gateway",
        provider=provider,
        model_alias=alias,
        model_route=model_route,
        capacity_pool=capacity_pool,
        profile="local" if local else "frontier-fast",
        estimated_cost_usd="0.00" if local else "0.01",
        context_window=context_window,
        tool_refs=tool_refs,
        authority_surfaces=("local_compute",) if local else ("provider_spend",),
        resource_pools=("local_compute",) if local else ("api_paid_spend",),
        quota_source="local_probe" if local else "ledger",
        cost_source="none" if local else "ledger",
        spend_authority_required=not local,
        public_egress_authority_required=public_egress,
    )


def _capability(
    agent_id: str,
    *classes: CockpitCommandClass,
    waiver: str | None = None,
    leaves: tuple[CockpitSupplyLeaf, ...] = (),
    llm_flags: dict[str, tuple[CockpitSupplyLeaf, ...]] | None = None,
    runtime_flags: tuple[str, ...] = (),
    public_flags: tuple[str, ...] = (),
) -> CockpitAgentCapability:
    receipt_classes: tuple[str, ...] = ()
    if leaves or llm_flags:
        receipt_classes = (
            "cockpit-capability-admission",
            "platform-capability-registry",
            "quota-spend-ledger",
            "route-resource-receipt",
        )
    return CockpitAgentCapability(
        agent_id=agent_id,
        display_name=_display_name(agent_id),
        classifications=classes,
        evidence_only_waiver=waiver,
        supply_leaves=leaves,
        receipt_classes=receipt_classes,
        runtime_mutation_flags=runtime_flags,
        public_egress_flags=public_flags,
        llm_flag_overlays=llm_flags or {},
    )


_FAST_SUMMARY_LEAF_BY_AGENT = {
    agent: (_model_leaf(agent, "fast", leaf_name="fast_synthesis"),)
    for agent in ("activity_analyzer", "knowledge_maint")
}

COCKPIT_AGENT_CAPABILITIES: dict[str, CockpitAgentCapability] = {
    "activity_analyzer": _capability(
        "activity_analyzer",
        CockpitCommandClass.DETERMINISTIC_EVIDENCE,
        CockpitCommandClass.MIXED_ORCHESTRATING,
        waiver="default invocation reads telemetry only; --synthesize adds an LLM supply leaf",
        llm_flags={"--synthesize": _FAST_SUMMARY_LEAF_BY_AGENT["activity_analyzer"]},
    ),
    "briefing": _capability(
        "briefing",
        CockpitCommandClass.LLM_BACKED_MODEL_USE,
        leaves=(_model_leaf("briefing", "fast", leaf_name="briefing_synthesis"),),
        runtime_flags=("--save",),
        public_flags=("--notify",),
    ),
    "broadcast_audio_health": _capability(
        "broadcast_audio_health",
        CockpitCommandClass.DETERMINISTIC_EVIDENCE,
        waiver="aggregates local audio safety evidence; no model/provider call",
    ),
    "code_review": _capability(
        "code_review",
        CockpitCommandClass.LLM_BACKED_MODEL_USE,
        leaves=(_model_leaf("code_review", "balanced", leaf_name="review_model"),),
    ),
    "demo": _capability(
        "demo",
        CockpitCommandClass.LLM_BACKED_MODEL_USE,
        CockpitCommandClass.MIXED_ORCHESTRATING,
        leaves=(
            _model_leaf("demo", "balanced", leaf_name="content_model"),
            _model_leaf("demo", "claude-opus", leaf_name="opus_script_model"),
        ),
        public_flags=("--format=app",),
    ),
    "digest": _capability(
        "digest",
        CockpitCommandClass.LLM_BACKED_MODEL_USE,
        leaves=(_model_leaf("digest", "fast", leaf_name="digest_synthesis"),),
        runtime_flags=("--save",),
        public_flags=("--notify",),
    ),
    "drift_detector": _capability(
        "drift_detector",
        CockpitCommandClass.LLM_BACKED_MODEL_USE,
        CockpitCommandClass.MIXED_ORCHESTRATING,
        leaves=(_model_leaf("drift_detector", "fast", leaf_name="drift_analysis"),),
        runtime_flags=("--apply",),
    ),
    "health_monitor": _capability(
        "health_monitor",
        CockpitCommandClass.DETERMINISTIC_EVIDENCE,
        waiver="default invocation observes stack health; --fix is a runtime mutation surface",
        runtime_flags=("--fix",),
    ),
    "introspect": _capability(
        "introspect",
        CockpitCommandClass.DETERMINISTIC_EVIDENCE,
        waiver="generates local infrastructure evidence without model/provider calls",
        runtime_flags=("--save",),
    ),
    "knowledge_maint": _capability(
        "knowledge_maint",
        CockpitCommandClass.DETERMINISTIC_EVIDENCE,
        CockpitCommandClass.MIXED_ORCHESTRATING,
        waiver="dry-run maintenance is deterministic; --summarize adds an LLM supply leaf",
        llm_flags={"--summarize": _FAST_SUMMARY_LEAF_BY_AGENT["knowledge_maint"]},
        runtime_flags=("--apply", "--save"),
        public_flags=("--notify",),
    ),
    "profiler": _capability(
        "profiler",
        CockpitCommandClass.LLM_BACKED_MODEL_USE,
        CockpitCommandClass.RUNTIME_MUTATION,
        CockpitCommandClass.MIXED_ORCHESTRATING,
        leaves=(
            _model_leaf("profiler", "balanced", leaf_name="profile_extraction"),
            _model_leaf("profiler", "fast", leaf_name="profile_classification"),
        ),
        runtime_flags=("--auto", "--curate", "--digest", "--full", "--index-profile", "--ingest"),
    ),
    "research": _capability(
        "research",
        CockpitCommandClass.LLM_BACKED_MODEL_USE,
        CockpitCommandClass.PUBLIC_EGRESS,
        CockpitCommandClass.MIXED_ORCHESTRATING,
        leaves=(
            _model_leaf(
                "research",
                "balanced",
                leaf_name="rag_synthesis",
                tool_refs=("qdrant_lookup",),
            ),
            _model_leaf(
                "research",
                "web-scout",
                leaf_name="web_search",
                tool_refs=("perplexity_sonar",),
                public_egress=True,
            ),
            _model_leaf(
                "research",
                "web-deep",
                leaf_name="deep_web_research",
                context_window="large",
                tool_refs=("perplexity_deep_research",),
                public_egress=True,
            ),
        ),
        public_flags=("--interactive",),
    ),
    "scout": _capability(
        "scout",
        CockpitCommandClass.LLM_BACKED_MODEL_USE,
        CockpitCommandClass.PUBLIC_EGRESS,
        CockpitCommandClass.MIXED_ORCHESTRATING,
        leaves=(
            _model_leaf(
                "scout",
                "fast",
                leaf_name="fitness_evaluation",
                tool_refs=("tavily_search",),
                public_egress=True,
            ),
        ),
        runtime_flags=("--save",),
        public_flags=("--notify",),
    ),
    "studio_compositor": _capability(
        "studio_compositor",
        CockpitCommandClass.RUNTIME_MUTATION,
        CockpitCommandClass.PUBLIC_EGRESS,
        waiver="runtime/video actuator; not LLM-backed, so this slice only inventories it",
    ),
}


def cockpit_capability_for(
    agent_id_or_name: str,
    *,
    manifest_model: str | None = None,
) -> CockpitAgentCapability:
    """Return static capability metadata for a manifest-backed cockpit agent."""
    agent_id = _agent_id(agent_id_or_name)
    capability = COCKPIT_AGENT_CAPABILITIES.get(agent_id)
    if capability is None:
        next_action = (
            "next_action=add the cockpit agent to COCKPIT_AGENT_CAPABILITIES "
            "with explicit supply leaves before enabling LLM-backed execution"
        )
        raise KeyError(f"untracked cockpit agent capability: {agent_id_or_name}; {next_action}")
    if manifest_model is not None and not capability.supply_leaves:
        next_action = (
            "next_action=add explicit base supply leaves for this manifest model to "
            "COCKPIT_AGENT_CAPABILITIES before enabling LLM-backed execution"
        )
        raise KeyError(
            f"manifest declares LLM model for unmetered cockpit capability: "
            f"{agent_id_or_name}; {next_action}"
        )
    return capability


def cockpit_capability_for_invocation(
    agent_id_or_name: str,
    *,
    manifest_model: str | None = None,
    flags: tuple[str, ...] | list[str] = (),
) -> CockpitAgentCapability:
    """Return capability metadata after applying flag-sensitive LLM overlays."""
    capability = cockpit_capability_for(agent_id_or_name, manifest_model=manifest_model)
    leaves = list(capability.supply_leaves)
    classes = set(capability.classifications)
    overlay = capability.llm_flag_overlays or {}
    for flag in _flag_args(flags):
        if capability.agent_id == "code_review" and flag.key == "--model":
            leaves = [_model_leaf("code_review", flag.value or "balanced")]
        elif flag.key in overlay:
            leaves.extend(overlay[flag.key])
    if leaves:
        classes.add(CockpitCommandClass.LLM_BACKED_MODEL_USE)
    if leaves and CockpitCommandClass.DETERMINISTIC_EVIDENCE in classes:
        classes.add(CockpitCommandClass.MIXED_ORCHESTRATING)
    return replace(
        capability,
        classifications=tuple(sorted(classes, key=lambda item: item.value)),
        supply_leaves=tuple(dict.fromkeys(leaves)),
        receipt_classes=(
            "cockpit-capability-admission",
            "platform-capability-registry",
            "quota-spend-ledger",
            "route-resource-receipt",
        )
        if leaves
        else capability.receipt_classes,
    )


def admit_cockpit_agent_invocation(
    agent_id_or_name: str,
    *,
    manifest_model: str | None = None,
    flags: tuple[str, ...] | list[str] = (),
    now: datetime | None = None,
) -> CockpitInvocationAdmission:
    """Evaluate route/resource/quota admission for one cockpit invocation."""
    checked_at = _admission_now(now)
    capability = cockpit_capability_for_invocation(
        agent_id_or_name,
        manifest_model=manifest_model,
        flags=flags,
    )
    non_read_only_reasons = _non_read_only_invocation_reasons(
        capability,
        flags,
    )
    if non_read_only_reasons:
        return CockpitInvocationAdmission(
            agent_id=capability.agent_id,
            display_name=capability.display_name,
            requires_admission=True,
            admitted=False,
            reason_codes=non_read_only_reasons,
            evidence_only_waiver=capability.evidence_only_waiver,
        )
    if not capability.requires_llm_admission:
        return CockpitInvocationAdmission(
            agent_id=capability.agent_id,
            display_name=capability.display_name,
            requires_admission=False,
            admitted=True,
            reason_codes=("deterministic_evidence_waiver",),
            evidence_only_waiver=capability.evidence_only_waiver,
        )

    receipts = tuple(_admit_leaf(leaf, now=checked_at) for leaf in capability.supply_leaves)
    admitted = all(receipt.admitted for receipt in receipts)
    reasons = tuple(
        dict.fromkeys(reason for receipt in receipts for reason in receipt.reason_codes)
    )
    return CockpitInvocationAdmission(
        agent_id=capability.agent_id,
        display_name=capability.display_name,
        requires_admission=True,
        admitted=admitted,
        reason_codes=reasons,
        receipts=receipts,
        evidence_only_waiver=capability.evidence_only_waiver,
    )


def require_cockpit_agent_admission(
    agent_id_or_name: str,
    *,
    manifest_model: str | None = None,
    flags: tuple[str, ...] | list[str] = (),
    now: datetime | None = None,
) -> CockpitInvocationAdmission:
    admission = admit_cockpit_agent_invocation(
        agent_id_or_name,
        manifest_model=manifest_model,
        flags=flags,
        now=now,
    )
    if admission.admitted:
        return admission
    receipt_bits = [
        f"{receipt.capability_id}:{receipt.short_reason()}" for receipt in admission.receipts
    ]
    raise CockpitAdmissionError(
        "cockpit_agent_capability_admission_refused "
        f"agent={admission.display_name} reason_codes={','.join(admission.reason_codes)} "
        f"receipts={';'.join(receipt_bits)} "
        "next_action=refresh platform capability receipts and quota/spend ledger before "
        "retrying guarded cockpit execution"
    )


def _admit_leaf(leaf: CockpitSupplyLeaf, *, now: datetime) -> CockpitAdmissionReceipt:
    try:
        ledger = _load_ledger()
    except Exception as exc:
        return _build_receipt(
            leaf,
            action="refused",
            reason_codes=(f"quota_spend_ledger_unavailable:{type(exc).__name__}",),
        )
    try:
        if leaf.capacity_pool == CapacityPool.API_PAID_SPEND.value:
            return _admit_paid_leaf(leaf, ledger, now=now)
        if leaf.capacity_pool == CapacityPool.LOCAL_COMPUTE.value:
            return _admit_local_leaf(leaf, ledger, now=now)
        return _build_receipt(
            leaf,
            action="refused",
            reason_codes=(f"unsupported_capacity_pool:{leaf.capacity_pool}",),
        )
    except Exception as exc:
        return _build_receipt(
            leaf,
            action="refused",
            reason_codes=(f"cockpit_admission_unavailable:{type(exc).__name__}",),
        )


def _non_read_only_invocation_reasons(
    capability: CockpitAgentCapability,
    flags: tuple[str, ...] | list[str],
) -> tuple[str, ...]:
    reasons: list[str] = []
    flags_by_key = _flag_args(flags)
    if CockpitCommandClass.RUNTIME_MUTATION in capability.classifications:
        reasons.append("runtime_mutation_surface_requires_route_receipt")
    if CockpitCommandClass.PUBLIC_EGRESS in capability.classifications:
        reasons.append("public_egress_surface_requires_route_receipt")
    for configured_flag in capability.runtime_mutation_flags:
        if any(_flag_matches(configured_flag, flag) for flag in flags_by_key):
            reasons.append(f"runtime_mutation_flag:{configured_flag}")
    for configured_flag in capability.public_egress_flags:
        if any(_flag_matches(configured_flag, flag) for flag in flags_by_key):
            reasons.append(f"public_egress_flag:{configured_flag}")
    if not reasons:
        return ()
    return tuple(dict.fromkeys(("non_read_only_invocation_requires_route_receipt", *reasons)))


def _admit_paid_leaf(
    leaf: CockpitSupplyLeaf,
    ledger: QuotaSpendLedger,
    *,
    now: datetime,
) -> CockpitAdmissionReceipt:
    eligibility = evaluate_paid_route_eligibility(
        ledger,
        PaidRouteRequest(
            route_id=leaf.route_id,
            task_id=leaf.capability_id,
            provider=leaf.provider,
            profile=leaf.profile,
            task_class=leaf.task_class,
            quality_floor=leaf.quality_floor,
            estimated_cost_usd=Decimal(leaf.estimated_cost_usd),
            capacity_pool=CapacityPool.API_PAID_SPEND,
        ),
        now=now,
    )
    platform_reasons, platform_refs = _platform_route_block_reasons(
        leaf.platform_route_id,
        now=now,
    )
    if eligibility.eligible and not platform_reasons:
        return _build_receipt(
            leaf,
            action="admitted",
            reason_codes=(eligibility.state,),
            spend_evidence_refs=eligibility.evidence_refs,
            resource_evidence_refs=platform_refs,
        )
    return _build_receipt(
        leaf,
        action="refused",
        reason_codes=(
            tuple(_reason_code(reason) for reason in eligibility.blocking_reasons)
            or (eligibility.state,)
        )
        + platform_reasons,
        spend_evidence_refs=eligibility.evidence_refs,
        resource_evidence_refs=platform_refs,
    )


def _admit_local_leaf(
    leaf: CockpitSupplyLeaf,
    ledger: QuotaSpendLedger,
    *,
    now: datetime,
) -> CockpitAdmissionReceipt:
    route_aliases = _local_leaf_route_aliases(leaf)
    snapshots = tuple(
        snapshot
        for snapshot in ledger.quota_snapshots
        if snapshot.capacity_pool is CapacityPool.LOCAL_COMPUTE
        and snapshot.route_id in route_aliases
    )
    quota_refs = tuple(ref for snapshot in snapshots for ref in snapshot.evidence_refs)
    fresh_snapshot = any(
        snapshot.subscription_quota_state is SubscriptionQuotaState.FRESH
        and (snapshot.fresh_until is None or snapshot.fresh_until > now)
        for snapshot in snapshots
    )
    reasons: list[str] = []
    if not snapshots:
        reasons.append("local_resource_snapshot_missing")
    elif not fresh_snapshot:
        reasons.append("local_resource_snapshot_not_fresh")
    if ledger.local_resource_state is not LocalResourceState.GREEN:
        reasons.append(f"local_resource_state:{ledger.local_resource_state.value}")
    platform_reasons, platform_refs = _platform_route_block_reasons(
        leaf.platform_route_id,
        now=now,
    )
    reasons.extend(platform_reasons)
    return _build_receipt(
        leaf,
        action="refused" if reasons else "admitted",
        reason_codes=tuple(reasons) or ("local_resource_green",),
        quota_evidence_refs=quota_refs,
        resource_evidence_refs=tuple(
            dict.fromkeys(
                (f"quota.local_resource_state:{ledger.local_resource_state.value}", *platform_refs)
            )
        ),
    )


def _local_leaf_route_aliases(leaf: CockpitSupplyLeaf) -> frozenset[str]:
    return frozenset(
        alias
        for alias in (
            leaf.route_id,
            leaf.platform_route_id,
            leaf.model_route,
            "local-fast",
            "appendix-fast",
            "litellm.local.command-r-35b",
        )
        if alias
    )


def _platform_route_block_reasons(
    route_id: str,
    *,
    now: datetime,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    registry_path = Path(
        os.environ.get(
            COCKPIT_PLATFORM_CAPABILITY_REGISTRY_ENV,
            os.environ.get("HAPAX_PLATFORM_CAPABILITY_REGISTRY", str(PLATFORM_CAPABILITY_REGISTRY)),
        )
    ).expanduser()
    receipt_dir = _platform_receipt_dir()
    try:
        registry = load_platform_capability_registry(
            registry_path, receipt_dir=receipt_dir, now=now
        )
    except PlatformCapabilityRegistryError as exc:
        return ((f"platform_capability_registry_unavailable:{type(exc).__name__}",), ())

    route = registry.route_map().get(normalize_route_id(route_id))
    if route is None:
        return ((f"platform_route_missing:{route_id}",), ())

    refs = (
        f"platform-capability-registry:{route.route_id}",
        *route.freshness.evidence.all_evidence_refs(),
    )
    reasons: list[str] = []
    if route.route_state is RouteState.BLOCKED:
        reasons.extend(route.blocked_reasons or ["platform_route_state_blocked"])
    reasons.extend(route.freshness.evidence.all_blocked_reasons())
    freshness = check_registry_freshness(registry, route_ids=(route.route_id,), now=now)
    if freshness.routes:
        route_freshness = freshness.routes[0]
        refs = (*refs, *route_freshness.evidence_refs)
        reasons.extend(_platform_route_freshness_reason(error) for error in route_freshness.errors)
    return tuple(dict.fromkeys(reasons)), tuple(dict.fromkeys(refs))


def _platform_receipt_dir() -> Path | None:
    configured = os.environ.get(PLATFORM_CAPABILITY_RECEIPT_DIR_ENV)
    if configured and configured.strip() not in {"0", "none", "None", "false", "False"}:
        return Path(configured).expanduser()
    if configured and configured.strip() in {"0", "none", "None", "false", "False"}:
        return None
    return DEFAULT_PLATFORM_CAPABILITY_RECEIPT_DIR


def _platform_route_freshness_reason(error: str) -> str:
    detail = error.split(": ", 1)[1] if ": " in error else error
    if detail.startswith("blocked: "):
        return _reason_code(detail.removeprefix("blocked: "))
    if " stale;" in detail:
        return f"platform_route_{_reason_code(detail.split(' stale;', 1)[0])}_stale"
    if " checked_at is in the future" in detail:
        return f"platform_route_{_reason_code(detail.split(' checked_at', 1)[0])}_future"
    if " freshness is unknown" in detail:
        return f"platform_route_{_reason_code(detail.split(' freshness', 1)[0])}_unknown"
    if " evidence refs missing" in detail:
        return f"platform_route_{_reason_code(detail.split(' evidence', 1)[0])}_evidence_missing"
    if detail.startswith("privacy posture is "):
        return "platform_route_privacy_posture_unknown"
    if detail.startswith("quota telemetry source is "):
        return "platform_route_quota_telemetry_unknown"
    if detail.startswith("resource telemetry source is "):
        return "platform_route_resource_telemetry_unknown"
    return f"platform_route_freshness_failed:{_reason_code(detail)}"


def _build_receipt(
    leaf: CockpitSupplyLeaf,
    *,
    action: str,
    reason_codes: tuple[str, ...],
    quota_evidence_refs: tuple[str, ...] = (),
    spend_evidence_refs: tuple[str, ...] = (),
    resource_evidence_refs: tuple[str, ...] = (),
) -> CockpitAdmissionReceipt:
    payload = {
        "capability_id": leaf.capability_id,
        "route_id": leaf.route_id,
        "platform_route_id": leaf.platform_route_id,
        "provider": leaf.provider,
        "model_alias": leaf.model_alias,
        "model_route": leaf.model_route,
        "capacity_pool": leaf.capacity_pool,
        "admission_action": action,
        "reason_codes": list(reason_codes),
        "quota_evidence_refs": list(quota_evidence_refs),
        "spend_evidence_refs": list(spend_evidence_refs),
        "resource_evidence_refs": list(resource_evidence_refs),
    }
    receipt_id = (
        "cockpit-"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
    )
    receipt_ref = f"cockpit-capability-admission:{receipt_id}"
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
    return CockpitAdmissionReceipt(
        receipt_id=receipt_id,
        receipt_ref=receipt_ref,
        capability_id=leaf.capability_id,
        route_id=leaf.route_id,
        platform_route_id=leaf.platform_route_id,
        provider=leaf.provider,
        model_alias=leaf.model_alias,
        model_route=leaf.model_route,
        capacity_pool=leaf.capacity_pool,
        admission_action=action,
        admitted=action == "admitted",
        reason_codes=reason_codes,
        quota_evidence_refs=quota_evidence_refs,
        spend_evidence_refs=spend_evidence_refs,
        resource_evidence_refs=resource_evidence_refs,
        receipt_refs=receipt_refs,
    )


def _load_ledger() -> QuotaSpendLedger:
    explicit = os.environ.get(COCKPIT_QUOTA_SPEND_LEDGER_ENV) or os.environ.get(
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
            "next_action=refresh quota telemetry or set HAPAX_COCKPIT_QUOTA_SPEND_LEDGER"
        )
    resolved = load_quota_spend_ledger_resolved(live_path=live_path)
    if resolved.source != "live":
        raise QuotaSpendLedgerError(
            "live quota/spend ledger unavailable; refusing fixture fallback for cockpit "
            "capability admission"
        )
    return resolved.ledger


def _admission_now(now: datetime | None) -> datetime:
    if now is not None:
        return now.astimezone(UTC)
    raw = os.environ.get(COCKPIT_ADMISSION_NOW_ENV) or os.environ.get("HAPAX_CAPACITY_ROUTING_NOW")
    if raw:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(UTC)
    return datetime.now(UTC).replace(microsecond=0)


def _flag_args(flags: tuple[str, ...] | list[str]) -> tuple[_FlagArg, ...]:
    args: list[_FlagArg] = []
    tokens = list(flags)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            index += 1
            continue

        key = _flag_key(token)
        value = _flag_value(token)
        if value is None and index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
            value = tokens[index + 1].strip() or None
            index += 1
        args.append(_FlagArg(key=key, value=value))
        index += 1
    return tuple(args)


def _flag_key(flag: str) -> str:
    return flag.split("=", 1)[0]


def _flag_value(flag: str) -> str | None:
    if "=" not in flag:
        return None
    value = flag.split("=", 1)[1].strip()
    return value or None


def _flag_matches(configured: str, observed: _FlagArg) -> bool:
    if observed.key != _flag_key(configured):
        return False
    configured_value = _flag_value(configured)
    return configured_value is None or observed.value == configured_value


def _reason_code(value: str) -> str:
    text = value.strip().lower().replace("/", "_")
    return "_".join(part for part in text.replace("-", "_").split() if part) or "unknown"


__all__ = [
    "COCKPIT_AGENT_CAPABILITIES",
    "COCKPIT_ADMISSION_NOW_ENV",
    "COCKPIT_PLATFORM_CAPABILITY_REGISTRY_ENV",
    "COCKPIT_QUOTA_SPEND_LEDGER_ENV",
    "CockpitAdmissionError",
    "CockpitAgentCapability",
    "CockpitCommandClass",
    "CockpitInvocationAdmission",
    "CockpitSupplyLeaf",
    "admit_cockpit_agent_invocation",
    "cockpit_capability_for",
    "cockpit_capability_for_invocation",
    "require_cockpit_agent_admission",
]
