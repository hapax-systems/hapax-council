"""World-capability-registry ingestion adapter (producer layer slice 4).

Ingests config/world-capability-registry.json (17 records — the world-expression/observation/state plane:
audio broadcast, camera/compositor, archive, browser MCP, MIDI, mobile biometrics, public aperture) into
CapabilityHarnessDescriptors. Maps realm/domain/daemon/authority/direction to the unified descriptor schema.
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

__all__ = ["ingest_world_capability_routes", "ingest_world_capability_registry"]


def _shape_for_record(rec: dict[str, object]) -> CapabilityShape:
    """Infer the shape from the realm + domain."""
    realm = str(rec.get("realm") or "")
    domain = str(rec.get("domain") or "")
    if realm == "world_expression":
        if domain == "audio":
            return CapabilityShape.BACKGROUND_SERVICE
        if domain == "music_midi":
            return CapabilityShape.LOCAL_TOOL
        return CapabilityShape.PUBLIC_EGRESS
    if realm in {"world_state", "world_observation"}:
        return CapabilityShape.BACKGROUND_SERVICE
    return CapabilityShape.BACKGROUND_SERVICE


def _domain_for_world_domain(world_domain: str) -> CapabilityDomain:
    mapping = {
        "audio": CapabilityDomain.DEVICE,
        "camera": CapabilityDomain.DEVICE,
        "mobile_watch": CapabilityDomain.DEVICE,
        "archive": CapabilityDomain.PUBLICATION,
        "public_aperture": CapabilityDomain.PUBLICATION,
        "browser_mcp": CapabilityDomain.RESOURCE,
        "file_obsidian": CapabilityDomain.RESOURCE,
        "music_midi": CapabilityDomain.DEVICE,
    }
    return mapping.get(world_domain, CapabilityDomain.RESOURCE)


def _actions_for_direction(direction: str) -> list[CapabilityAction]:
    mapping = {
        "communicate": [CapabilityAction.PUBLISH],
        "observe": [CapabilityAction.OBSERVE],
        "mutate": [CapabilityAction.MUTATE],
        "query": [CapabilityAction.QUERY],
        "receive": [CapabilityAction.RECEIVE],
    }
    return mapping.get(direction, [CapabilityAction.OBSERVE])


def _authority_ceiling(rec: dict[str, object]) -> AuthorityCeiling:
    ceiling = str(rec.get("authority_ceiling") or "").lower()
    public_claim = rec.get("public_claim_policy") or {}
    if ceiling in {"public_publish", "public_publish_allowed"}:
        return AuthorityCeiling.PUBLIC_PUBLISH
    if isinstance(public_claim, str) and public_claim in {"publish_allowed", "public_publish"}:
        return AuthorityCeiling.PUBLIC_PUBLISH
    if "mutate" in ceiling or "repo" in ceiling:
        return AuthorityCeiling.REPO_MUTATION
    return AuthorityCeiling.READ_ONLY


def _public_gate_required(rec: dict[str, object], shape: CapabilityShape) -> bool:
    ceiling = str(rec.get("authority_ceiling") or "").lower()
    public_claim = rec.get("public_claim_policy") or {}
    policy_requires_public = False
    if isinstance(public_claim, dict):
        policy_requires_public = bool(public_claim.get("requires_egress_public_claim"))
    elif isinstance(public_claim, str):
        policy_requires_public = public_claim.lower() == "public_gate_required"
    return (
        shape == CapabilityShape.PUBLIC_EGRESS
        or ceiling == "public_gate_required"
        or policy_requires_public
    )


def _freshness_state(rec: dict[str, object]) -> FreshnessState:
    availability = str(rec.get("availability_state") or rec.get("health_signal") or "").lower()
    if availability in {"live", "healthy", "available"}:
        return FreshnessState.FRESH
    if availability in {"blocked", "failed", "stale"}:
        return FreshnessState.STALE
    if availability in {"hold", "paced"}:
        return FreshnessState.HOLD
    return FreshnessState.DARK


def _descriptor_from_record(rec: dict[str, object]) -> CapabilityHarnessDescriptor:
    capability_id = str(rec.get("capability_id") or "")
    world_domain = str(rec.get("domain") or "")
    shape = _shape_for_record(rec)
    daemon = str(rec.get("daemon") or "")
    direction = str(rec.get("direction") or "observe")
    authority = _authority_ceiling(rec)
    mutation_surfaces: list[str] = []
    if shape in {CapabilityShape.LOCAL_TOOL, CapabilityShape.PUBLIC_EGRESS}:
        mutation_surfaces = [world_domain or capability_id]
    return CapabilityHarnessDescriptor(
        capability_id=capability_id,
        display_name=str(rec.get("capability_name") or capability_id),
        shape=shape,
        domain=_domain_for_world_domain(world_domain),
        actions=_actions_for_direction(direction),
        execution_harness_id=daemon or capability_id or None,
        authority_ceiling=authority,
        mutation_surfaces=mutation_surfaces,
        public_egress_authority_required=_public_gate_required(rec, shape),
        resource_pools=[daemon] if daemon else [],
        freshness_state=_freshness_state(rec),
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
        owner_docs=[f"realm={rec.get('realm', '')} world_domain={world_domain}"]
        if rec.get("realm")
        else [],
    )


def ingest_world_capability_routes(
    records: Sequence[dict[str, object]],
) -> list[CapabilityHarnessDescriptor]:
    """Map world-capability-registry records to descriptors."""
    return [_descriptor_from_record(rec) for rec in records if isinstance(rec, dict)]


def ingest_world_capability_registry(path: str | Path) -> list[CapabilityHarnessDescriptor]:
    """Ingest config/world-capability-registry.json into descriptors."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ingest_world_capability_routes(payload.get("records") or [])
