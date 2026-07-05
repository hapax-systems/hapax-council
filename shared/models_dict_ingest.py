"""MODELS dict ingestion adapter (producer layer slice 8).

Ingests the MODELS dict from shared/config.py (~20 LiteLLM aliases — deepseek, glm, gemini, mistral,
opus, local-fast, etc.) into CapabilityHarnessDescriptors. Cloud aliases become hosted_model shapes;
local/appendix aliases become raw_model shapes so cost/spend boundaries stay honest.
"""

from __future__ import annotations

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

__all__ = ["ingest_models_dict"]


def _is_local_route(alias: str, route_str: str) -> bool:
    return alias.startswith(("local-", "appendix-")) or route_str.startswith(
        ("local-", "appendix-")
    )


def _descriptor_for_alias(alias: str, route_str: str) -> CapabilityHarnessDescriptor:
    is_local = _is_local_route(alias, route_str)
    return CapabilityHarnessDescriptor(
        capability_id=f"litellm.{alias}",
        display_name=f"LiteLLM: {alias}",
        shape=CapabilityShape.RAW_MODEL if is_local else CapabilityShape.HOSTED_MODEL,
        domain=CapabilityDomain.LOCAL_COMPUTE if is_local else CapabilityDomain.LLM_WORKER,
        actions=[CapabilityAction.REASON, CapabilityAction.IMPLEMENT],
        provider="local" if is_local else "litellm",
        backend="litellm-local" if is_local else "litellm-proxy",
        model=route_str,
        authority_ceiling=AuthorityCeiling.REPO_MUTATION,
        spend_authority_required=not is_local,
        resource_pools=[alias],
        cost_source=CostSource.NONE if is_local else CostSource.PROVIDER,
        quota_source=QuotaSource.NONE if is_local else QuotaSource.PROVIDER,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
        owner_docs=[
            f"LiteLLM alias '{alias}' -> '{route_str}'. Live in LiteLLM config but "
            "absent from platform-capability-registry (the silent-unregistered gap)."
        ],
    )


def ingest_models_dict(models: dict[str, object]) -> list[CapabilityHarnessDescriptor]:
    """Map a MODELS dict (alias -> liteLLM route string or config dict) to descriptors.

    Cloud entries become hosted_model descriptors with spend_authority_required; local/appendix entries
    become raw_model descriptors with local cost/quota. All use DARK freshness because these are the
    live-but-unregistered routes the capability-inventory consultation flagged.
    """
    descriptors: list[CapabilityHarnessDescriptor] = []
    for alias, value in models.items():
        if isinstance(value, str):
            route_str = value
        elif isinstance(value, dict):
            route_str = str(value.get("route") or value.get("model") or alias)
        else:
            continue
        descriptors.append(_descriptor_for_alias(alias, route_str))
    return descriptors
