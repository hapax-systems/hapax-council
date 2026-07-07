"""Capability-classification-inventory ingestion adapter (producer layer slice 7).

Ingests config/capability-classification-inventory.json into descriptors.
Filters to recruitable=true (selectable supply leaves; non-recruitable rows are observations/affordances,
not dispatchable capabilities). Shape inferred from direction/effect_type.
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
    FreshnessState,
)

__all__ = ["ingest_classification_routes", "ingest_classification_inventory"]

_DIR_TO_SHAPE: dict[str, CapabilityShape] = {
    "communicate": CapabilityShape.PUBLIC_EGRESS,
    "publish": CapabilityShape.PUBLIC_EGRESS,
    "express": CapabilityShape.LOCAL_TOOL,
    "observe": CapabilityShape.BACKGROUND_SERVICE,
    "mutate": CapabilityShape.LOCAL_TOOL,
    "query": CapabilityShape.LOCAL_TOOL,
    "recall": CapabilityShape.LOCAL_TOOL,
    "route": CapabilityShape.LOCAL_TOOL,
    "act": CapabilityShape.LOCAL_TOOL,
    "receive": CapabilityShape.MONEY_RAIL,
}


def _shape_for_direction(direction: str) -> CapabilityShape:
    normalized = direction.lower()
    try:
        return _DIR_TO_SHAPE[normalized]
    except KeyError as exc:
        raise ValueError(
            f"unknown classification direction {direction!r}; repair "
            "config/capability-classification-inventory.json or add an adapter mapping "
            "before regenerating the capability inventory baseline"
        ) from exc


def _actions_for_direction(direction: str) -> list[CapabilityAction]:
    mapping = {
        "communicate": [CapabilityAction.PUBLISH],
        "publish": [CapabilityAction.PUBLISH],
        "express": [CapabilityAction.ACTUATE],
        "observe": [CapabilityAction.OBSERVE],
        "mutate": [CapabilityAction.MUTATE],
        "query": [CapabilityAction.QUERY],
        "recall": [CapabilityAction.QUERY],
        "route": [CapabilityAction.MUTATE],
        "act": [CapabilityAction.ACTUATE],
        "receive": [CapabilityAction.RECEIVE],
    }
    normalized = direction.lower()
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(
            f"unknown classification direction {direction!r}; repair "
            "config/capability-classification-inventory.json or add an adapter mapping "
            "before regenerating the capability inventory baseline"
        ) from exc


def _authority_ceiling(shape: CapabilityShape, ceiling: str) -> AuthorityCeiling:
    """Map classification authority strings without treating gate-required as granted authority."""
    normalized = ceiling.lower()
    if shape == CapabilityShape.MONEY_RAIL:
        return AuthorityCeiling.RECEIVE_ONLY_MONEY
    if normalized in {"public_publish", "public_publish_allowed", "publish_allowed"}:
        return AuthorityCeiling.PUBLIC_PUBLISH
    if "mutate" in normalized or "repo" in normalized:
        return AuthorityCeiling.REPO_MUTATION
    return AuthorityCeiling.READ_ONLY


def _public_gate_required(row: dict[str, object], shape: CapabilityShape) -> bool:
    policy = str(row.get("public_claim_policy") or "").lower()
    ceiling = str(row.get("authority_ceiling") or "").lower()
    return (
        shape == CapabilityShape.PUBLIC_EGRESS
        or policy == "public_gate_required"
        or ceiling == "public_gate_required"
    )


def _descriptor_from_row(row: dict[str, object]) -> CapabilityHarnessDescriptor | None:
    """Map a classification row to a descriptor, or None if not recruitable."""
    if not row.get("recruitable", False):
        return None
    row_id = str(row.get("row_id") or row.get("classification_id") or "")
    direction = str(row.get("direction") or "observe")
    shape = _shape_for_direction(direction)
    ceiling_str = str(row.get("authority_ceiling") or "").lower()
    authority = _authority_ceiling(shape, ceiling_str)
    availability = str(row.get("availability_state") or "").lower()
    freshness = (
        FreshnessState.FRESH
        if availability in {"live", "healthy", "available"}
        else FreshnessState.STALE
        if availability in {"blocked", "failed", "stale"}
        else FreshnessState.DARK
    )
    display = str(row.get("display_name") or row.get("semantic_description") or row_id)
    mutation_surfaces: list[str] = []
    if shape in {CapabilityShape.LOCAL_TOOL, CapabilityShape.PUBLIC_EGRESS}:
        mutation_surfaces = [str(row.get("surface") or row.get("domain") or row_id)]
    return CapabilityHarnessDescriptor(
        capability_id=row_id,
        display_name=display[:100],
        shape=shape,
        domain=CapabilityDomain.RESOURCE,
        actions=_actions_for_direction(direction),
        execution_harness_id=str(row.get("execution_harness_id") or row_id) or None,
        authority_ceiling=authority,
        mutation_surfaces=mutation_surfaces,
        public_egress_authority_required=_public_gate_required(row, shape),
        resource_pools=[row_id] if shape == CapabilityShape.MONEY_RAIL and row_id else [],
        freshness_state=freshness,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
        owner_docs=[f"classification kind={row.get('kind', [])} direction={direction}"],
    )


def ingest_classification_routes(
    rows: Sequence[dict[str, object]],
) -> list[CapabilityHarnessDescriptor]:
    """Map classification inventory rows to descriptors (recruitable only)."""
    out: list[CapabilityHarnessDescriptor] = []
    for row in rows:
        if isinstance(row, dict):
            desc = _descriptor_from_row(row)
            if desc is not None:
                out.append(desc)
    return out


def ingest_classification_inventory(path: str | Path) -> list[CapabilityHarnessDescriptor]:
    """Ingest config/capability-classification-inventory.json into descriptors."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ingest_classification_routes(payload.get("rows") or [])
