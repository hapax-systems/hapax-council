"""Canonical weakness and harness-lever taxonomy for capability descriptors.

The labels mirror the governed harness-leverage artifact:
``capability-harness-leverage-weakness-mitigation-2026-06-30.md``.
"""

from __future__ import annotations

from enum import StrEnum


class WeaknessId(StrEnum):
    MISSING_LOCAL_INVARIANTS = "W1"
    TOKEN_THINKING_BUDGET_PATHOLOGIES = "W2"
    CONTEXT_WINDOW_RETRIEVAL_LIMITS = "W3"
    TOOL_CALL_FRAGILITY = "W4"
    OUTPUT_SHAPE_DRIFT = "W5"
    STATE_FSM_MISMATCH = "W6"
    AUTHORITY_AMBIGUITY = "W7"
    STALE_CAPABILITY_EVIDENCE = "W8"
    COST_QUOTA_PRESSURE = "W9"
    CORRELATED_FAILURES = "W10"
    OVER_UNDERCONFIDENCE = "W11"
    LATENCY = "W12"
    PUBLIC_PRIVACY_MONEY_RISK = "W13"
    ORCHESTRATION_CHILD_PATH_OPACITY = "W14"
    PROMPT_INJECTION_INGRESS = "W15"
    REFUSAL_OVER_REFUSAL_SAFETY_MISFIRE = "W16"
    HALLUCINATION_GROUNDING_FAILURE = "W17"
    NONDETERMINISM_REPLAY_DIVERGENCE = "W18"


class LeverId(StrEnum):
    INJECTED_INVARIANTS = "L1"
    COMPRESSED_SDLC_FSM_CANON = "L2"
    TASK_SURFACE_SHAPING = "L3"
    ESCALATION_POLICY = "L4"
    TOOL_ADAPTERS = "L5"
    OUTPUT_SCHEMAS = "L6"
    VERIFIER_GATES = "L7"
    ALLOW_DENY_AUTHORITY_NARROWING = "L8"
    QUARANTINE_SHADOW_MODE = "L9"
    RECEIPTS = "L10"
    RESOURCE_METERS = "L11"
    CONTEXT_EXTRACTION = "L12"
    POSTERIOR_UPDATES = "L13"
    REINS_PROJECTION = "L14"
    AUTOMATED_FRESHNESS_REMEDIATION = "L15"
    INDEPENDENCE_DIVERSITY_ENFORCEMENT = "L16"


WEAKNESS_LABELS: dict[WeaknessId, str] = {
    WeaknessId.MISSING_LOCAL_INVARIANTS: "Missing local invariants",
    WeaknessId.TOKEN_THINKING_BUDGET_PATHOLOGIES: "Token / thinking-budget pathologies",
    WeaknessId.CONTEXT_WINDOW_RETRIEVAL_LIMITS: "Context-window and retrieval limits",
    WeaknessId.TOOL_CALL_FRAGILITY: "Tool-call fragility",
    WeaknessId.OUTPUT_SHAPE_DRIFT: "Output-shape drift",
    WeaknessId.STATE_FSM_MISMATCH: "State / FSM mismatch",
    WeaknessId.AUTHORITY_AMBIGUITY: "Authority ambiguity",
    WeaknessId.STALE_CAPABILITY_EVIDENCE: "Stale capability evidence",
    WeaknessId.COST_QUOTA_PRESSURE: "Cost / quota pressure",
    WeaknessId.CORRELATED_FAILURES: "Correlated failures",
    WeaknessId.OVER_UNDERCONFIDENCE: "Overconfidence / underconfidence",
    WeaknessId.LATENCY: "Latency",
    WeaknessId.PUBLIC_PRIVACY_MONEY_RISK: "Public / privacy / money risk",
    WeaknessId.ORCHESTRATION_CHILD_PATH_OPACITY: "Orchestration child-path opacity",
    WeaknessId.PROMPT_INJECTION_INGRESS: "Prompt-injection / adversarial input",
    WeaknessId.REFUSAL_OVER_REFUSAL_SAFETY_MISFIRE: "Refusal / over-refusal / safety-misfire",
    WeaknessId.HALLUCINATION_GROUNDING_FAILURE: "Hallucination / grounding failure",
    WeaknessId.NONDETERMINISM_REPLAY_DIVERGENCE: "Non-determinism / replay divergence",
}


LEVER_LABELS: dict[LeverId, str] = {
    LeverId.INJECTED_INVARIANTS: "Injected invariants",
    LeverId.COMPRESSED_SDLC_FSM_CANON: "Compressed SDLC/FSM canon",
    LeverId.TASK_SURFACE_SHAPING: "Task-surface shaping / bounded generation",
    LeverId.ESCALATION_POLICY: "Escalation policy",
    LeverId.TOOL_ADAPTERS: "Tool adapters",
    LeverId.OUTPUT_SCHEMAS: "Output schemas",
    LeverId.VERIFIER_GATES: "Verifier gates",
    LeverId.ALLOW_DENY_AUTHORITY_NARROWING: "Allow/deny policy + authority narrowing",
    LeverId.QUARANTINE_SHADOW_MODE: "Quarantine / shadow mode",
    LeverId.RECEIPTS: "Receipts",
    LeverId.RESOURCE_METERS: "Resource meters",
    LeverId.CONTEXT_EXTRACTION: "Context extraction",
    LeverId.POSTERIOR_UPDATES: "Posterior updates",
    LeverId.REINS_PROJECTION: "Reins projection",
    LeverId.AUTOMATED_FRESHNESS_REMEDIATION: "Automated freshness remediation",
    LeverId.INDEPENDENCE_DIVERSITY_ENFORCEMENT: "Independence / diversity enforcement",
}


WEAKNESS_TO_MITIGATING_LEVERS: dict[WeaknessId, frozenset[LeverId]] = {
    WeaknessId.MISSING_LOCAL_INVARIANTS: frozenset(
        {
            LeverId.INJECTED_INVARIANTS,
            LeverId.COMPRESSED_SDLC_FSM_CANON,
            LeverId.VERIFIER_GATES,
        }
    ),
    WeaknessId.TOKEN_THINKING_BUDGET_PATHOLOGIES: frozenset(
        {
            LeverId.TASK_SURFACE_SHAPING,
            LeverId.ESCALATION_POLICY,
            LeverId.RESOURCE_METERS,
        }
    ),
    WeaknessId.CONTEXT_WINDOW_RETRIEVAL_LIMITS: frozenset(
        {
            LeverId.INJECTED_INVARIANTS,
            LeverId.COMPRESSED_SDLC_FSM_CANON,
            LeverId.CONTEXT_EXTRACTION,
        }
    ),
    WeaknessId.TOOL_CALL_FRAGILITY: frozenset(
        {
            LeverId.TOOL_ADAPTERS,
            LeverId.VERIFIER_GATES,
            LeverId.QUARANTINE_SHADOW_MODE,
        }
    ),
    WeaknessId.OUTPUT_SHAPE_DRIFT: frozenset(
        {
            LeverId.OUTPUT_SCHEMAS,
            LeverId.VERIFIER_GATES,
            LeverId.QUARANTINE_SHADOW_MODE,
        }
    ),
    WeaknessId.STATE_FSM_MISMATCH: frozenset(
        {
            LeverId.COMPRESSED_SDLC_FSM_CANON,
            LeverId.OUTPUT_SCHEMAS,
            LeverId.VERIFIER_GATES,
        }
    ),
    WeaknessId.AUTHORITY_AMBIGUITY: frozenset(
        {
            LeverId.ALLOW_DENY_AUTHORITY_NARROWING,
            LeverId.RECEIPTS,
            LeverId.REINS_PROJECTION,
        }
    ),
    WeaknessId.STALE_CAPABILITY_EVIDENCE: frozenset(
        {
            LeverId.POSTERIOR_UPDATES,
            LeverId.AUTOMATED_FRESHNESS_REMEDIATION,
        }
    ),
    WeaknessId.COST_QUOTA_PRESSURE: frozenset(
        {
            LeverId.TASK_SURFACE_SHAPING,
            LeverId.RESOURCE_METERS,
            LeverId.REINS_PROJECTION,
        }
    ),
    WeaknessId.CORRELATED_FAILURES: frozenset(
        {
            LeverId.INDEPENDENCE_DIVERSITY_ENFORCEMENT,
            LeverId.ALLOW_DENY_AUTHORITY_NARROWING,
            LeverId.REINS_PROJECTION,
        }
    ),
    WeaknessId.OVER_UNDERCONFIDENCE: frozenset(
        {
            LeverId.VERIFIER_GATES,
            LeverId.CONTEXT_EXTRACTION,
            LeverId.POSTERIOR_UPDATES,
        }
    ),
    WeaknessId.LATENCY: frozenset(
        {
            LeverId.TASK_SURFACE_SHAPING,
            LeverId.RESOURCE_METERS,
            LeverId.REINS_PROJECTION,
        }
    ),
    WeaknessId.PUBLIC_PRIVACY_MONEY_RISK: frozenset(
        {
            LeverId.ALLOW_DENY_AUTHORITY_NARROWING,
            LeverId.RECEIPTS,
            LeverId.RESOURCE_METERS,
            LeverId.REINS_PROJECTION,
        }
    ),
    WeaknessId.ORCHESTRATION_CHILD_PATH_OPACITY: frozenset(
        {
            LeverId.TOOL_ADAPTERS,
            LeverId.ALLOW_DENY_AUTHORITY_NARROWING,
            LeverId.QUARANTINE_SHADOW_MODE,
            LeverId.REINS_PROJECTION,
        }
    ),
    WeaknessId.PROMPT_INJECTION_INGRESS: frozenset(
        {
            LeverId.ALLOW_DENY_AUTHORITY_NARROWING,
            LeverId.VERIFIER_GATES,
            LeverId.QUARANTINE_SHADOW_MODE,
        }
    ),
    WeaknessId.REFUSAL_OVER_REFUSAL_SAFETY_MISFIRE: frozenset(
        {
            LeverId.QUARANTINE_SHADOW_MODE,
            LeverId.POSTERIOR_UPDATES,
            LeverId.VERIFIER_GATES,
        }
    ),
    WeaknessId.HALLUCINATION_GROUNDING_FAILURE: frozenset(
        {
            LeverId.INJECTED_INVARIANTS,
            LeverId.COMPRESSED_SDLC_FSM_CANON,
            LeverId.VERIFIER_GATES,
        }
    ),
    WeaknessId.NONDETERMINISM_REPLAY_DIVERGENCE: frozenset(
        {
            LeverId.RECEIPTS,
            LeverId.OUTPUT_SCHEMAS,
        }
    ),
}


ALL_WEAKNESS_IDS: tuple[WeaknessId, ...] = tuple(WeaknessId)
ALL_LEVER_IDS: tuple[LeverId, ...] = tuple(LeverId)
ORNITH_RAW_MODEL_REQUIRED_LEVERS: frozenset[LeverId] = frozenset(
    {
        LeverId.INJECTED_INVARIANTS,
        LeverId.COMPRESSED_SDLC_FSM_CANON,
        LeverId.TASK_SURFACE_SHAPING,
        LeverId.TOOL_ADAPTERS,
        LeverId.OUTPUT_SCHEMAS,
        LeverId.VERIFIER_GATES,
        LeverId.POSTERIOR_UPDATES,
    }
)
