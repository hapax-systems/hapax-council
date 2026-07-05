"""Publication-bus surface_registry ingestion adapter (producer layer slice 9 — the 7th vocabulary).

Ingests the publication-bus SURFACE_REGISTRY (the public_egress + money_rail plane) into descriptors.
Takes the registry as a parameter (duck-typed: reads automation_status, dispatch_entry, scope_note via
getattr) so it's testable without importing the heavy publication_bus module. A wrapper
``ingest_publication_bus_from_module`` imports SURFACE_REGISTRY live.
"""

from __future__ import annotations

from collections.abc import Mapping

from shared.capability_harness_descriptor import (
    AuthorityCeiling,
    CapabilityAction,
    CapabilityDomain,
    CapabilityHarnessDescriptor,
    CapabilityShape,
    FreshnessState,
)

__all__ = ["ingest_publication_bus_surfaces", "ingest_publication_bus_from_module"]


_MONEY_RAIL_TOKENS = (
    "receiver",
    "payment",
    "donation",
    "direct-debit",
    "github-sponsors",
    "ko-fi",
    "liberapay",
    "open-collective",
    "stripe",
    "patreon",
    "buy-me-a-coffee",
    "mercury",
    "modern-treasury",
    "treasury-prime",
    "wise",
)


def _is_money_rail(surface_id: str) -> bool:
    return any(token in surface_id for token in _MONEY_RAIL_TOKENS)


def _shape_for_surface(surface_id: str) -> CapabilityShape:
    if _is_money_rail(surface_id):
        return CapabilityShape.MONEY_RAIL
    return CapabilityShape.PUBLIC_EGRESS


def _status_value(status: object) -> str:
    raw = getattr(status, "value", status)
    return str(raw or "")


def _status_key(status: object) -> str:
    return _status_value(status).casefold()


def _is_refused_status(status: object) -> bool:
    key = _status_key(status)
    return key == "refused" or key.endswith(".refused")


def _is_full_auto_status(status: object) -> bool:
    key = _status_key(status)
    return key == "full_auto" or key.endswith(".full_auto")


def _freshness_for_status(status: object) -> FreshnessState:
    if _is_refused_status(status):
        return FreshnessState.STALE
    if _is_full_auto_status(status):
        return FreshnessState.FRESH
    return FreshnessState.DARK


def _actions_for_surface(
    shape: CapabilityShape, automation_status: object
) -> list[CapabilityAction]:
    if _is_refused_status(automation_status):
        return []
    if shape == CapabilityShape.MONEY_RAIL:
        return [CapabilityAction.RECEIVE]
    return [CapabilityAction.PUBLISH]


def _authority_for_surface(shape: CapabilityShape, automation_status: object) -> AuthorityCeiling:
    if _is_refused_status(automation_status):
        return AuthorityCeiling.READ_ONLY
    if shape == CapabilityShape.MONEY_RAIL:
        return AuthorityCeiling.RECEIVE_ONLY_MONEY
    return AuthorityCeiling.PUBLIC_PUBLISH


def _descriptor_from_surface(surface_id: str, spec: object) -> CapabilityHarnessDescriptor:
    shape = _shape_for_surface(surface_id)
    automation_status = getattr(spec, "automation_status", "") or ""
    automation = _status_value(automation_status)
    dispatch = str(getattr(spec, "dispatch_entry", "") or "")
    scope = str(getattr(spec, "scope_note", "") or surface_id)
    api = str(getattr(spec, "api", "") or "")
    return CapabilityHarnessDescriptor(
        capability_id=f"publication_bus.{surface_id}",
        display_name=scope[:100],
        shape=shape,
        domain=CapabilityDomain.PAYMENT
        if shape == CapabilityShape.MONEY_RAIL
        else CapabilityDomain.PUBLICATION,
        actions=_actions_for_surface(shape, automation_status),
        execution_harness_id=dispatch or None,
        mutation_surfaces=[surface_id] if shape == CapabilityShape.PUBLIC_EGRESS else [],
        authority_ceiling=_authority_for_surface(shape, automation_status),
        public_egress_authority_required=shape == CapabilityShape.PUBLIC_EGRESS,
        resource_pools=[surface_id] if surface_id else [],
        freshness_state=_freshness_for_status(automation_status),
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
        owner_docs=[f"automation={automation} api={api}"],
    )


def ingest_publication_bus_surfaces(
    registry: Mapping[str, object],
) -> list[CapabilityHarnessDescriptor]:
    """Map a publication-bus SURFACE_REGISTRY (surface_id -> SurfaceSpec) to descriptors."""
    return [_descriptor_from_surface(sid, spec) for sid, spec in registry.items()]


def ingest_publication_bus_from_module() -> list[CapabilityHarnessDescriptor]:
    """Import SURFACE_REGISTRY live + ingest. Raises ImportError if the module is unavailable."""
    from agents.publication_bus.surface_registry import SURFACE_REGISTRY

    return ingest_publication_bus_surfaces(SURFACE_REGISTRY)
