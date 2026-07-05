"""MCP connector manifest ingestion adapter (producer layer slice 6).

Ingests config/mcp-connector-tool-manifest.json (27 tools) into CapabilityHarnessDescriptors. Maps
effect_classes to shapes: read_only_evidence -> local_tool; local_mutation -> local_tool;
external_mutation/public_egress -> public_egress; money_resource_mutation -> money_rail;
governance_mutation -> local_tool.
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

__all__ = ["ingest_mcp_connector_routes", "ingest_mcp_connector_manifest"]

_EFFECT_TO_SHAPE: dict[str, CapabilityShape] = {
    "read_only_evidence": CapabilityShape.LOCAL_TOOL,
    "local_mutation": CapabilityShape.LOCAL_TOOL,
    "external_mutation": CapabilityShape.PUBLIC_EGRESS,
    "public_egress": CapabilityShape.PUBLIC_EGRESS,
    "money_resource_mutation": CapabilityShape.MONEY_RAIL,
    "governance_mutation": CapabilityShape.LOCAL_TOOL,
}


def _shape_for_effects(effects: Sequence[str]) -> CapabilityShape:
    """Pick the most-significant shape from the effect_classes."""
    unknown = sorted(set(effects) - set(_EFFECT_TO_SHAPE))
    if unknown:
        raise ValueError(f"unknown MCP effect_classes: {', '.join(unknown)}")
    priority = [
        CapabilityShape.MONEY_RAIL,
        CapabilityShape.PUBLIC_EGRESS,
        CapabilityShape.LOCAL_TOOL,
    ]
    shapes = {_EFFECT_TO_SHAPE[e] for e in effects}
    for prio in priority:
        if prio in shapes:
            return prio
    return CapabilityShape.LOCAL_TOOL


def _actions_for_effects(effects: Sequence[str]) -> list[CapabilityAction]:
    actions: list[CapabilityAction] = []
    if "read_only_evidence" in effects:
        actions.append(CapabilityAction.QUERY)
    if "local_mutation" in effects or "governance_mutation" in effects:
        actions.append(CapabilityAction.MUTATE)
    if "external_mutation" in effects or "public_egress" in effects:
        actions.append(CapabilityAction.PUBLISH)
    if "money_resource_mutation" in effects:
        actions.append(CapabilityAction.RECEIVE)
    return actions or [CapabilityAction.QUERY]


def _authority_for_shape(shape: CapabilityShape) -> AuthorityCeiling:
    if shape == CapabilityShape.PUBLIC_EGRESS:
        return AuthorityCeiling.PUBLIC_PUBLISH
    if shape == CapabilityShape.MONEY_RAIL:
        return AuthorityCeiling.RECEIVE_ONLY_MONEY
    return AuthorityCeiling.READ_ONLY


def _descriptor_from_tool(tool: dict[str, object]) -> CapabilityHarnessDescriptor:
    canonical = str(tool.get("canonical_name") or "")
    effects = tool.get("effect_classes") or []
    if not isinstance(effects, list):
        effects = []
    effects_str = [str(e) for e in effects]
    shape = _shape_for_effects(effects_str)
    mutation_surfaces = (
        [canonical] if shape in {CapabilityShape.LOCAL_TOOL, CapabilityShape.PUBLIC_EGRESS} else []
    )
    return CapabilityHarnessDescriptor(
        capability_id=canonical,
        display_name=canonical,
        shape=shape,
        domain=CapabilityDomain.RESOURCE,
        actions=_actions_for_effects(effects_str),
        execution_harness_id=canonical or None,
        authority_ceiling=_authority_for_shape(shape),
        mutation_surfaces=mutation_surfaces,
        public_egress_authority_required=shape == CapabilityShape.PUBLIC_EGRESS,
        resource_pools=[canonical] if shape == CapabilityShape.MONEY_RAIL and canonical else [],
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
        owner_docs=[f"mcp_connector effect_classes={effects_str}"],
    )


def ingest_mcp_connector_routes(
    tools: Sequence[dict[str, object]],
) -> list[CapabilityHarnessDescriptor]:
    """Map MCP connector manifest tools to descriptors."""
    return [_descriptor_from_tool(t) for t in tools if isinstance(t, dict)]


def ingest_mcp_connector_manifest(path: str | Path) -> list[CapabilityHarnessDescriptor]:
    """Ingest config/mcp-connector-tool-manifest.json into descriptors."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ingest_mcp_connector_routes(payload.get("tools") or [])
