"""Grounding-providers registry ingestion adapter (producer layer slice 5).

Ingests config/grounding-providers.json (the grounding provider plane: local Command-R via TabbyAPI, cloud
providers) into CapabilityHarnessDescriptors. Maps provider_id/provider_family/model_id to the
provider_gateway / hosted_model / raw_model shapes.
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
)

__all__ = ["ingest_grounding_provider_routes", "ingest_grounding_providers"]


def _shape_for_provider(rec: dict[str, object]) -> CapabilityShape:
    """Infer the shape from cloud_route + provider_family."""
    cloud = bool(rec.get("cloud_route", False))
    if not cloud and "tabbyapi" in str(rec.get("provider_family", "")).lower():
        return CapabilityShape.RAW_MODEL
    if cloud:
        return CapabilityShape.HOSTED_MODEL
    return CapabilityShape.PROVIDER_GATEWAY


def _descriptor_from_record(rec: dict[str, object]) -> CapabilityHarnessDescriptor:
    provider_id = str(rec.get("provider_id") or rec.get("adapter_id") or "")
    model_id = str(rec.get("model_id") or "")
    family = str(rec.get("provider_family") or "")
    shape = _shape_for_provider(rec)
    cloud = bool(rec.get("cloud_route", False))
    requires_evidence = bool(rec.get("requires_supplied_evidence", False))
    return CapabilityHarnessDescriptor(
        capability_id=provider_id,
        display_name=f"{family} ({model_id})" if model_id else provider_id,
        shape=shape,
        domain=CapabilityDomain.LOCAL_COMPUTE
        if shape == CapabilityShape.RAW_MODEL
        else CapabilityDomain.LLM_WORKER,
        actions=[CapabilityAction.REASON, CapabilityAction.GROUND]
        if requires_evidence
        else [CapabilityAction.REASON],
        provider=family or None,
        backend="tabbyapi" if "tabbyapi" in family.lower() else None,
        model=model_id or None,
        authority_ceiling=AuthorityCeiling.READ_ONLY,
        spend_authority_required=cloud,
        resource_pools=[provider_id] if provider_id else [],
        cost_source=CostSource.PROVIDER if cloud else CostSource.NONE,
        quota_source=QuotaSource.PROVIDER if cloud else QuotaSource.NONE,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
        owner_docs=[
            f"provider_kind={rec.get('provider_kind', '')} tool_id={rec.get('tool_id', '')}"
        ],
    )


def ingest_grounding_provider_routes(
    records: Sequence[dict[str, object]],
) -> list[CapabilityHarnessDescriptor]:
    """Map grounding-provider records to descriptors."""
    return [_descriptor_from_record(rec) for rec in records if isinstance(rec, dict)]


def ingest_grounding_providers(path: str | Path) -> list[CapabilityHarnessDescriptor]:
    """Ingest config/grounding-providers.json into descriptors."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ingest_grounding_provider_routes(payload.get("providers") or [])
