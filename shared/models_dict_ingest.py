"""MODELS dict ingestion adapter (producer layer slice 8).

Ingests the MODELS dict from shared/config.py (~20 LiteLLM aliases — deepseek, glm, gemini, mistral,
opus, etc.) into CapabilityHarnessDescriptors as hosted_model shapes. These are cloud LLM routes that
are live in LiteLLM but absent from the platform-capability-registry (the silent-unregistered gap).
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


def ingest_models_dict(models: dict[str, object]) -> list[CapabilityHarnessDescriptor]:
    """Map a MODELS dict (alias -> liteLLM route string or config dict) to descriptors.

    Each entry becomes a hosted_model descriptor with spend_authority_required (cloud) and DARK freshness
    (these are the live-but-unregistered routes the capability-inventory consultation flagged).
    """
    descriptors: list[CapabilityHarnessDescriptor] = []
    for alias, value in models.items():
        if isinstance(value, str):
            route_str = value
        elif isinstance(value, dict):
            route_str = str(value.get("route") or value.get("model") or alias)
        else:
            continue
        descriptors.append(
            CapabilityHarnessDescriptor(
                capability_id=f"litellm.{alias}",
                display_name=f"LiteLLM: {alias}",
                shape=CapabilityShape.HOSTED_MODEL,
                domain=CapabilityDomain.LLM_WORKER,
                actions=[CapabilityAction.REASON, CapabilityAction.IMPLEMENT],
                provider="litellm",
                backend="litellm-proxy",
                model=route_str,
                authority_ceiling=AuthorityCeiling.REPO_MUTATION,
                spend_authority_required=True,
                resource_pools=[alias],
                cost_source=CostSource.PROVIDER,
                quota_source=QuotaSource.PROVIDER,
                freshness_state=FreshnessState.DARK,
                freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
                owner_docs=[
                    f"LiteLLM alias '{alias}' -> '{route_str}'. Live in LiteLLM config but "
                    "absent from platform-capability-registry (the silent-unregistered gap)."
                ],
            )
        )
    return descriptors
