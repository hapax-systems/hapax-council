"""Seed capability-harness descriptors — one per shape, from the known live capabilities.

This is the taxonomy's First Implementation Sequence step 2: seed a registry from existing route/resource
surfaces so the read-model (the inventory command + ``discover()``) has real descriptors to project. The
seeds are authored from the known capabilities (per the capability-inventory consultation wf_04c2d293-021);
freshness is honest (DARK where the live measurement isn't wired yet — the descriptor surfaces that gap
rather than asserting it fresh). Each seed satisfies its shape's required facts (validate_descriptor).
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

__all__ = ["SEED_CAPABILITY_DESCRIPTORS", "seed_descriptors_by_shape"]


SEED_CAPABILITY_DESCRIPTORS: list[CapabilityHarnessDescriptor] = [
    # raw_model — Ornith (the local model; grounding-inference candidate)
    CapabilityHarnessDescriptor(
        capability_id="ornith.local.grounding",
        display_name="Ornith (local model)",
        shape=CapabilityShape.RAW_MODEL,
        domain=CapabilityDomain.LOCAL_COMPUTE,
        actions=[CapabilityAction.REASON],
        backend="local-transformers",
        model="ornith-8b",
        authority_ceiling=AuthorityCeiling.READ_ONLY,
        resource_pools=["local-gpu-1"],
        cost_source=CostSource.NONE,
        quota_source=QuotaSource.NONE,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # hosted_model — Claude Sonnet via Anthropic
    CapabilityHarnessDescriptor(
        capability_id="claude.sonnet.hosted",
        display_name="Claude Sonnet (Anthropic)",
        shape=CapabilityShape.HOSTED_MODEL,
        domain=CapabilityDomain.LLM_WORKER,
        actions=[CapabilityAction.REASON, CapabilityAction.IMPLEMENT],
        provider="anthropic",
        model="claude-sonnet-5",
        spend_authority_required=True,
        authority_ceiling=AuthorityCeiling.REPO_MUTATION,
        resource_pools=["anthropic-subscription"],
        cost_source=CostSource.PROVIDER,
        quota_source=QuotaSource.PROVIDER,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # model_effort_slice — Codex GPT-5.5 xhigh
    CapabilityHarnessDescriptor(
        capability_id="codex.gpt-5-5.xhigh.source-edit",
        display_name="Codex GPT-5.5 xhigh (source edit)",
        shape=CapabilityShape.MODEL_EFFORT_SLICE,
        domain=CapabilityDomain.LLM_WORKER,
        actions=[CapabilityAction.IMPLEMENT],
        platform_id="codex",
        route_id="codex.headless.full",
        model="gpt-5.5",
        effort="xhigh",
        authority_ceiling=AuthorityCeiling.REPO_MUTATION,
        spend_authority_required=True,
        resource_pools=["codex-quota"],
        cost_source=CostSource.PROVIDER,
        quota_source=QuotaSource.PROVIDER,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # existing_agent_harness — Claude Code opus headless slice
    CapabilityHarnessDescriptor(
        capability_id="claude.code.opus.headless",
        display_name="Claude Code Opus (headless)",
        shape=CapabilityShape.EXISTING_AGENT_HARNESS,
        domain=CapabilityDomain.LLM_WORKER,
        actions=[CapabilityAction.IMPLEMENT],
        platform_id="claude",
        route_id="claude.headless.full",
        execution_harness_id="hapax-claude-headless",
        model="claude-opus-4-8",
        authority_ceiling=AuthorityCeiling.REPO_MUTATION,
        spend_authority_required=True,
        resource_pools=["anthropic-subscription"],
        cost_source=CostSource.PROVIDER,
        quota_source=QuotaSource.PROVIDER,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # review_seat — GLMCP review
    CapabilityHarnessDescriptor(
        capability_id="glmcp.review.direct",
        display_name="GLMCP review seat",
        shape=CapabilityShape.REVIEW_SEAT,
        domain=CapabilityDomain.REVIEW,
        actions=[CapabilityAction.REVIEW],
        platform_id="glmcp",
        route_id="glmcp.review.direct",
        authority_ceiling=AuthorityCeiling.READ_ONLY,
        spend_authority_required=True,
        resource_pools=["glmcp-quota"],
        cost_source=CostSource.PROVIDER,
        quota_source=QuotaSource.PROVIDER,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # local_tool — the platform-capability-receipts writer
    CapabilityHarnessDescriptor(
        capability_id="local.platform-capability-receipts-writer",
        display_name="platform-capability-receipts writer",
        shape=CapabilityShape.LOCAL_TOOL,
        domain=CapabilityDomain.LOCAL_COMPUTE,
        actions=[CapabilityAction.OBSERVE],
        execution_harness_id="hapax-quota-telemetry-writer",
        mutation_surfaces=["~/.cache/hapax/platform-capability-receipts/"],
        authority_ceiling=AuthorityCeiling.READ_ONLY,
        cost_source=CostSource.NONE,
        quota_source=QuotaSource.NONE,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # provider_gateway — LiteLLM
    CapabilityHarnessDescriptor(
        capability_id="litellm.gateway.4000",
        display_name="LiteLLM gateway (:4000)",
        shape=CapabilityShape.PROVIDER_GATEWAY,
        domain=CapabilityDomain.LLM_WORKER,
        actions=[CapabilityAction.ORCHESTRATE],
        provider="litellm",
        backend="litellm-proxy",
        authority_ceiling=AuthorityCeiling.READ_ONLY,
        resource_pools=["litellm-router"],
        cost_source=CostSource.LEDGER,
        quota_source=QuotaSource.LEDGER,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # public_egress — the publication bus omg-weblog surface
    CapabilityHarnessDescriptor(
        capability_id="publication.omg-weblog",
        display_name="Publication bus: omg-weblog",
        shape=CapabilityShape.PUBLIC_EGRESS,
        domain=CapabilityDomain.PUBLICATION,
        actions=[CapabilityAction.PUBLISH],
        execution_harness_id="agents.omg_weblog_publisher",
        mutation_surfaces=["hapax.weblog.lol"],
        authority_ceiling=AuthorityCeiling.PUBLIC_PUBLISH,
        public_egress_authority_required=True,
        resource_pools=["omg-lol-weblog"],
        cost_source=CostSource.NONE,
        quota_source=QuotaSource.NONE,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # money_rail — Stripe receive-only
    CapabilityHarnessDescriptor(
        capability_id="stripe.receive-only-payment-link",
        display_name="Stripe receive-only payment link",
        shape=CapabilityShape.MONEY_RAIL,
        domain=CapabilityDomain.PAYMENT,
        actions=[CapabilityAction.RECEIVE],
        resource_pools=["stripe-receive"],
        authority_ceiling=AuthorityCeiling.RECEIVE_ONLY_MONEY,
        cost_source=CostSource.NONE,
        quota_source=QuotaSource.NONE,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # background_service — hapax-daimonion TTS/STT daemon
    CapabilityHarnessDescriptor(
        capability_id="hapax-daimonion.tts-stt-daemon",
        display_name="hapax-daimonion TTS/STT",
        shape=CapabilityShape.BACKGROUND_SERVICE,
        domain=CapabilityDomain.DEVICE,
        actions=[CapabilityAction.ACTUATE, CapabilityAction.OBSERVE],
        execution_harness_id="systemd/hapax-daimonion.service",
        authority_ceiling=AuthorityCeiling.PROVISION,
        resource_pools=["local-gpu-1"],
        cost_source=CostSource.NONE,
        quota_source=QuotaSource.NONE,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # orchestrator — Fugu
    CapabilityHarnessDescriptor(
        capability_id="fugu.orchestrator",
        display_name="Fugu orchestrator",
        shape=CapabilityShape.ORCHESTRATOR,
        domain=CapabilityDomain.ORCHESTRATION,
        actions=[CapabilityAction.ORCHESTRATE],
        authority_ceiling=AuthorityCeiling.READ_ONLY,
        cost_source=CostSource.NONE,
        quota_source=QuotaSource.NONE,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # capability_aggregator — the platform-capability-registry
    CapabilityHarnessDescriptor(
        capability_id="platform-capability-registry.aggregator",
        display_name="platform-capability-registry",
        shape=CapabilityShape.CAPABILITY_AGGREGATOR,
        domain=CapabilityDomain.RESOURCE,
        actions=[CapabilityAction.QUERY],
        authority_ceiling=AuthorityCeiling.READ_ONLY,
        cost_source=CostSource.NONE,
        quota_source=QuotaSource.NONE,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
    ),
    # fugu (Sakana AI Scientist) — the strongest model now that Fable is inoperable on much of the
    # codebase (the silent-downgrade; Fable is disqualified for the seat). PRIORITIZED entitlement +
    # capability-shape + harnessing exploration (operator directive 2026-07-03). Two tiers: Fugu
    # (standard) + Fugu Ultra (highest sub-tier); Fugu > Fugu Ultra at some work types (to-measure).
    CapabilityHarnessDescriptor(
        capability_id="fugu.existing-agent-harness",
        display_name="Fugu (Sakana AI Scientist)",
        shape=CapabilityShape.EXISTING_AGENT_HARNESS,
        domain=CapabilityDomain.LLM_WORKER,
        actions=[CapabilityAction.IMPLEMENT, CapabilityAction.REASON, CapabilityAction.ORCHESTRATE],
        platform_id="fugu",
        route_id="fugu.headless.full",
        execution_harness_id="hapax-fugu-harness",
        model="fugu",
        authority_ceiling=AuthorityCeiling.REPO_MUTATION,
        mutation_surfaces=["source"],
        spend_authority_required=True,
        resource_pools=["fugu-entitlement"],
        cost_source=CostSource.PROVIDER,
        quota_source=QuotaSource.PROVIDER,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
        owner_docs=[
            "PRIORITIZED (operator 2026-07-03): Fugu is the strongest model post-Fable-disqualification.",
            "Also an orchestrator (taxonomy example); modeled as existing_agent_harness per the operator framing.",
            "Fugu > Fugu Ultra at some work types — the work-type fit is to-measure.",
        ],
    ),
    CapabilityHarnessDescriptor(
        capability_id="fugu.ultra.highest-tier",
        display_name="Fugu Ultra (highest sub-tier)",
        shape=CapabilityShape.MODEL_EFFORT_SLICE,
        domain=CapabilityDomain.LLM_WORKER,
        actions=[CapabilityAction.IMPLEMENT, CapabilityAction.REASON],
        platform_id="fugu",
        route_id="fugu.headless.ultra",
        execution_harness_id="hapax-fugu-harness",
        model="fugu-ultra",
        effort="ultra",
        authority_ceiling=AuthorityCeiling.REPO_MUTATION,
        mutation_surfaces=["source"],
        spend_authority_required=True,
        resource_pools=["fugu-ultra-entitlement"],
        cost_source=CostSource.PROVIDER,
        quota_source=QuotaSource.PROVIDER,
        freshness_state=FreshnessState.DARK,
        freshness_remediation_task="cc-task-capability-harness-descriptor-20260703",
        owner_docs=[
            "PRIORITIZED (operator 2026-07-03): Fugu Ultra = the highest sub-tier entitlement (to-explore).",
            "Not appropriate for all work types (Fugu > Ultra at some); work-type fit to-measure.",
        ],
    ),
]


def seed_descriptors_by_shape() -> dict[CapabilityShape, CapabilityHarnessDescriptor]:
    """Return the seed descriptors keyed by shape (one per shape)."""
    return {d.shape: d for d in SEED_CAPABILITY_DESCRIPTORS}
