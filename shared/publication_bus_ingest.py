"""Publication-bus surface_registry ingestion adapter (producer layer slice 9 — the 7th vocabulary).

Ingests the 106-entry publication-bus SURFACE_REGISTRY (the public_egress + money_rail plane) into
descriptors. Takes the registry as a parameter (duck-typed: reads automation_status, dispatch_entry,
scope_note via getattr) so it's testable without importing the heavy publication_bus module. A wrapper
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


def _is_money_rail(surface_id: str) -> bool:
    return "receiver" in surface_id or "payment" in surface_id or "donation" in surface_id


def _shape_for_surface(surface_id: str) -> CapabilityShape:
    if _is_money_rail(surface_id):
        return CapabilityShape.MONEY_RAIL
    return CapabilityShape.PUBLIC_EGRESS


def _freshness_for_status(status: str) -> FreshnessState:
    status_lower = status.lower()
    if status in {"FULL_AUTO"} or "auto" in status_lower:
        return FreshnessState.FRESH
    if status in {"REFUSED"} or "refused" in status_lower:
        return FreshnessState.STALE
    return FreshnessState.DARK


def _descriptor_from_surface(surface_id: str, spec: object) -> CapabilityHarnessDescriptor:
    shape = _shape_for_surface(surface_id)
    automation = str(getattr(spec, "automation_status", "") or "")
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
        actions=[CapabilityAction.RECEIVE]
        if shape == CapabilityShape.MONEY_RAIL
        else [CapabilityAction.PUBLISH],
        execution_harness_id=dispatch or None,
        mutation_surfaces=[surface_id] if shape == CapabilityShape.PUBLIC_EGRESS else [],
        authority_ceiling=(
            AuthorityCeiling.RECEIVE_ONLY_MONEY
            if shape == CapabilityShape.MONEY_RAIL
            else AuthorityCeiling.PUBLIC_PUBLISH
        ),
        public_egress_authority_required=shape == CapabilityShape.PUBLIC_EGRESS,
        resource_pools=[surface_id] if surface_id else [],
        freshness_state=_freshness_for_status(automation),
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
