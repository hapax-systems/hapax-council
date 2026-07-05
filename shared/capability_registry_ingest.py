"""Capability registry ingestion — adapt the existing capability vocabularies into descriptors.

The producer layer: ingest the 7 parallel capability registries into the unified ``CapabilityHarnessDescriptor``
schema so the inventory projects the *actual* live capabilities + ``discover()`` emits the real delta. This
module's adapter: ``config/platform-capability-registry.json`` (the LLM/dispatch supply plane — 13 routes).
Follow-on adapters (separate slices): the world-capability-registry, the publication-bus surface_registry,
grounding-providers, the MODELS dict, the mcp-connector-manifest, the capability-classification-inventory.

Each route is mapped to a descriptor with shape/domain/authority/freshness inferred from its platform,
route_id, route_state, and execution descriptor — never hand-authored, so the inventory reflects the live
registry, not a stale copy.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from shared.capability_harness_descriptor import (
    AuthorityCeiling,
    CapabilityAction,
    CapabilityDomain,
    CapabilityHarnessDescriptor,
    CapabilityShape,
    CostSource,
    FreshnessState,
    QuotaSource,
    validate_descriptor,
)

__all__ = ["ingest_platform_capability_registry", "ingest_routes"]


_AGENT_PLATFORMS = frozenset({"antigrav", "claude", "codex", "vibe"})


def _shape_for_route(route_id: str, platform: str, profile: str) -> CapabilityShape:
    """Infer the capability shape from the route's platform/profile."""
    if platform == "local_tool":
        return CapabilityShape.LOCAL_TOOL
    if platform == "glmcp":
        return CapabilityShape.REVIEW_SEAT
    if platform == "api" and "gateway" in profile:
        return CapabilityShape.PROVIDER_GATEWAY
    if platform == "api":
        return CapabilityShape.HOSTED_MODEL
    if platform in _AGENT_PLATFORMS:
        return CapabilityShape.EXISTING_AGENT_HARNESS
    return CapabilityShape.HOSTED_MODEL


def _domain_for_shape(shape: CapabilityShape) -> CapabilityDomain:
    """The capability domain for a shape."""
    if shape == CapabilityShape.REVIEW_SEAT:
        return CapabilityDomain.REVIEW
    if shape == CapabilityShape.LOCAL_TOOL:
        return CapabilityDomain.LOCAL_COMPUTE
    if shape in {CapabilityShape.PROVIDER_GATEWAY, CapabilityShape.CAPABILITY_AGGREGATOR}:
        return CapabilityDomain.RESOURCE
    return CapabilityDomain.LLM_WORKER


def _actions_for_shape(shape: CapabilityShape) -> list[CapabilityAction]:
    """The default action set for a shape."""
    if shape == CapabilityShape.REVIEW_SEAT:
        return [CapabilityAction.REVIEW]
    if shape == CapabilityShape.LOCAL_TOOL:
        return [CapabilityAction.OBSERVE]
    if shape == CapabilityShape.PROVIDER_GATEWAY:
        return [CapabilityAction.ORCHESTRATE]
    if shape == CapabilityShape.PUBLIC_EGRESS:
        return [CapabilityAction.PUBLISH]
    return [CapabilityAction.IMPLEMENT, CapabilityAction.REASON]


def _authority_ceiling(route: dict[str, object]) -> AuthorityCeiling:
    """Map the route's authority ceiling + mutability to the descriptor's."""
    ceiling = str(route.get("authority_ceiling", "")).lower()
    mutability = route.get("mutability") or {}
    source_writable = bool(isinstance(mutability, dict) and mutability.get("source"))
    public_writable = bool(isinstance(mutability, dict) and mutability.get("public"))
    if public_writable:
        return AuthorityCeiling.PUBLIC_PUBLISH
    if source_writable or ceiling == "authoritative":
        return AuthorityCeiling.REPO_MUTATION
    return AuthorityCeiling.READ_ONLY


def _enum_from(
    value: object, enum_type: type[CostSource] | type[QuotaSource]
) -> CostSource | QuotaSource:
    try:
        return enum_type(str(value or "").lower())
    except ValueError:
        return enum_type.NONE


def _mutation_surfaces(
    route: dict[str, object], authority: AuthorityCeiling, shape: CapabilityShape
) -> list[str]:
    mutability = route.get("mutability") or {}
    surfaces: list[str] = []
    if isinstance(mutability, dict):
        surfaces = sorted(str(surface) for surface, enabled in mutability.items() if enabled)
    if not surfaces and authority == AuthorityCeiling.REPO_MUTATION:
        surfaces = ["source"]
    if shape == CapabilityShape.LOCAL_TOOL and not surfaces:
        surfaces = ["local_tool"]
    return surfaces


def _freshness_state(route_state: object) -> FreshnessState:
    """Map the route_state to the descriptor's freshness_state."""
    state = str(route_state or "").lower()
    if state in {"live", "available", "fresh"}:
        return FreshnessState.FRESH
    if state in {"blocked", "stale"}:
        return FreshnessState.STALE
    if state in {"hold", "paced"}:
        return FreshnessState.HOLD
    return FreshnessState.DARK


def _descriptor_from_route(route: dict[str, object]) -> CapabilityHarnessDescriptor:
    """Map one platform-capability-registry route to a descriptor."""
    route_id = str(route.get("route_id") or "")
    platform = str(route.get("platform") or "")
    profile = str(route.get("profile") or "")
    shape = _shape_for_route(route_id, platform, profile)
    exec_desc = route.get("execution_descriptor") or {}
    if not isinstance(exec_desc, dict):
        exec_desc = {}
    model = str(exec_desc.get("model_id") or route.get("model_or_engine") or "")
    effort = str(exec_desc.get("effort") or "none")
    capacity_pool = str(route.get("capacity_pool") or "")
    resource_pools = [capacity_pool] if capacity_pool else []
    provider = str(route.get("provider") or route.get("paid_provider") or platform or "")
    backend = str(
        exec_desc.get("backend")
        or exec_desc.get("gateway")
        or exec_desc.get("adapter")
        or route.get("paid_profile")
        or model
        or profile
        or platform
        or ""
    )
    execution_harness_id = str(route.get("launcher") or platform or route_id or "")
    authority = _authority_ceiling(route)
    mutation_surfaces = _mutation_surfaces(route, authority, shape)
    telemetry = route.get("telemetry") or {}
    if not isinstance(telemetry, dict):
        telemetry = {}
    quota_source = _enum_from(telemetry.get("quota_source"), QuotaSource)
    cost_source = _enum_from(telemetry.get("cost_source"), CostSource)
    descriptor_provider = None
    if shape in {CapabilityShape.HOSTED_MODEL, CapabilityShape.PROVIDER_GATEWAY}:
        descriptor_provider = provider or None
    descriptor_backend = None
    if shape == CapabilityShape.PROVIDER_GATEWAY:
        descriptor_backend = backend or None
    return CapabilityHarnessDescriptor(
        capability_id=route_id,
        display_name=str(route.get("summary") or route_id),
        shape=shape,
        domain=_domain_for_shape(shape),
        actions=_actions_for_shape(shape),
        platform_id=platform or None,
        route_id=route_id or None,
        execution_harness_id=execution_harness_id or None,
        provider=descriptor_provider,
        backend=descriptor_backend,
        model=model or None,
        effort=effort if effort != "none" else None,
        authority_ceiling=authority,
        mutation_surfaces=mutation_surfaces,
        resource_pools=resource_pools,
        spend_authority_required=capacity_pool
        in {"subscription_quota", "paid_spend", "api_paid_spend"}
        or "provider_spend" in mutation_surfaces,
        quota_source=quota_source,
        cost_source=cost_source,
        freshness_state=_freshness_state(route.get("route_state")),
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    )


def ingest_routes(routes: Sequence[dict[str, object]]) -> list[CapabilityHarnessDescriptor]:
    """Map a sequence of platform-capability-registry routes to descriptors (one per route).

    Separated from the file reader so tests can exercise the mapping with a fixture dict.
    """
    descriptors = [_descriptor_from_route(route) for route in routes if isinstance(route, dict)]
    invalid = {
        descriptor.capability_id: validate_descriptor(descriptor)
        for descriptor in descriptors
        if validate_descriptor(descriptor)
    }
    if invalid:
        details = "; ".join(f"{cid}: {', '.join(gaps)}" for cid, gaps in invalid.items())
        raise ValueError(f"platform-capability-registry descriptors failed validation: {details}")
    return descriptors


def ingest_platform_capability_registry(path: str | Path) -> list[CapabilityHarnessDescriptor]:
    """Ingest a platform-capability-registry.json into descriptors (one per route).

    Returns one ``CapabilityHarnessDescriptor`` per route, shape/domain/authority/freshness inferred from the
    route's platform/profile/state. Read-only: it parses the JSON + maps; it mutates nothing.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ingest_routes(payload.get("routes") or [])
