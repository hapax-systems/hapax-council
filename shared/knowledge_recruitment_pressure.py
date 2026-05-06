"""Global knowledge-gap recruitment contract.

This module turns "I do not know enough to do this well" into an explicit
recruitment pressure. It is intentionally domain-neutral: segment prep,
runtime hosting, layout choice, maintenance planning, and future work domains
can all emit the same shape.

The contract does not grant truth or action authority. Recruited sources become
evaluated priors/receipts; existing grounding, privacy, runtime, and readback
gates still decide what can be claimed or done.
"""

from __future__ import annotations

import hashlib
import json
import time
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.grounding_provider_router import (
    PROVIDER_REGISTRY,
    REQUIRED_EVIDENCE_FIELDS,
    claim_requires_grounding,
    route_candidates_for_claim,
)
from shared.impingement import Impingement, ImpingementType

KNOWLEDGE_RECRUITMENT_VERSION = 1
KNOWLEDGE_RECRUITMENT_CLAIM_TYPE = "knowledge_recruitment_guidance_request"
LOCAL_EVALUATOR_PROVIDER_ID = "local_supplied_evidence_command_r"
RECRUITMENT_CONFIDENCE_THRESHOLD = 0.72

AUTHORITY_BOUNDARIES = (
    "guidance_is_evaluated_prior_only",
    "sources_do_not_become_runtime_authority",
    "no_script_or_static_default_authority",
    "public_claims_require_grounding_receipts",
    "actions_require_existing_runtime_readback_gates",
)


class KnowledgeStakes(StrEnum):
    """How costly it is to improvise from thin internal know-how."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FreshnessNeed(StrEnum):
    """Freshness posture for recruited guidance."""

    NONE = "none"
    STABLE_BACKGROUND = "stable_background"
    CURRENT = "current"
    OPEN_WORLD = "open_world"


class KnowledgeGapSignal(BaseModel):
    """A domain-neutral signal that internal know-how is insufficient."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = KNOWLEDGE_RECRUITMENT_VERSION
    gap_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    task_summary: str = Field(min_length=1, max_length=500)
    uncertainty_summary: str = Field(min_length=1, max_length=500)
    internal_confidence: float = Field(ge=0.0, le=1.0)
    stakes: KnowledgeStakes = KnowledgeStakes.MEDIUM
    freshness_need: FreshnessNeed = FreshnessNeed.STABLE_BACKGROUND
    public_claim_intended: bool = False
    private_payload_refs: tuple[str, ...] = ()
    existing_evidence_refs: tuple[str, ...] = ()

    @field_validator(
        "private_payload_refs",
        "existing_evidence_refs",
        mode="after",
    )
    @classmethod
    def _refs_non_empty(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for ref in value:
            if not ref.strip():
                raise ValueError("evidence refs must be non-empty strings")
        return value


class KnowledgeRecruitmentDecision(BaseModel):
    """Deterministic recruitment plan for a knowledge gap."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = KNOWLEDGE_RECRUITMENT_VERSION
    decision_id: str
    gap_id: str
    domain: str
    claim_type: str
    should_recruit: bool
    trigger_reasons: tuple[str, ...]
    source_acquisition_required: bool
    source_acquiring_provider_ids: tuple[str, ...]
    source_conditioned_provider_ids: tuple[str, ...]
    local_evaluator_provider_id: str | None
    egress_preflight_provider_ids: tuple[str, ...]
    required_receipt_fields: tuple[str, ...]
    authority_boundaries: tuple[str, ...]
    blockers: tuple[str, ...] = ()
    decision_hash: str


def build_knowledge_recruitment_decision(
    signal: KnowledgeGapSignal,
    *,
    provider_registry_path=PROVIDER_REGISTRY,
) -> KnowledgeRecruitmentDecision:
    """Build a fail-closed recruitment decision for a global knowledge gap."""

    trigger_reasons = _trigger_reasons(signal)
    should_recruit = bool(trigger_reasons)
    supplied_evidence = bool(signal.existing_evidence_refs or signal.private_payload_refs)
    candidates = route_candidates_for_claim(
        KNOWLEDGE_RECRUITMENT_CLAIM_TYPE,
        supplied_evidence=supplied_evidence,
        path=provider_registry_path,
    )
    source_acquiring = tuple(
        provider.provider_id for provider in candidates if provider.can_satisfy_open_world_claims
    )
    source_conditioned = tuple(
        provider.provider_id for provider in candidates if provider.requires_supplied_evidence
    )
    local_evaluator = (
        LOCAL_EVALUATOR_PROVIDER_ID if LOCAL_EVALUATOR_PROVIDER_ID in source_conditioned else None
    )
    source_acquisition_required = should_recruit and not supplied_evidence
    egress_preflight = tuple(
        provider.provider_id for provider in candidates if provider.egress_preflight_required
    )
    blockers: list[str] = []
    if not claim_requires_grounding(KNOWLEDGE_RECRUITMENT_CLAIM_TYPE):
        blockers.append("knowledge_recruitment_claim_type_not_grounded")
    if source_acquisition_required and not source_acquiring:
        blockers.append("source_acquisition_route_missing")
    if supplied_evidence and local_evaluator is None:
        blockers.append("local_evaluator_route_missing")

    raw = {
        "gap": signal.model_dump(mode="json"),
        "trigger_reasons": trigger_reasons,
        "private_payload_refs": signal.private_payload_refs,
        "source_acquiring": source_acquiring,
        "source_conditioned": source_conditioned,
        "source_acquisition_required": source_acquisition_required,
        "egress_preflight": egress_preflight,
        "blockers": blockers,
    }
    decision_hash = hashlib.sha256(
        json.dumps(raw, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return KnowledgeRecruitmentDecision(
        decision_id=f"knowledge_recruitment:{signal.gap_id}",
        gap_id=signal.gap_id,
        domain=signal.domain,
        claim_type=KNOWLEDGE_RECRUITMENT_CLAIM_TYPE,
        should_recruit=should_recruit,
        trigger_reasons=tuple(trigger_reasons),
        source_acquisition_required=source_acquisition_required,
        source_acquiring_provider_ids=source_acquiring,
        source_conditioned_provider_ids=source_conditioned,
        local_evaluator_provider_id=local_evaluator,
        egress_preflight_provider_ids=egress_preflight,
        required_receipt_fields=tuple(sorted(REQUIRED_EVIDENCE_FIELDS)),
        authority_boundaries=AUTHORITY_BOUNDARIES,
        blockers=tuple(blockers),
        decision_hash=decision_hash,
    )


def build_knowledge_recruitment_impingement(
    signal: KnowledgeGapSignal,
    decision: KnowledgeRecruitmentDecision,
    *,
    now: float | None = None,
) -> Impingement:
    """Convert the decision to an impingement for the global recruitment bus."""

    timestamp = time.time() if now is None else now
    narrative = (
        f"Knowledge gap in {signal.domain}: {signal.uncertainty_summary}; "
        f"task={signal.task_summary}; recruit evaluated guidance before acting."
    )
    evidence_refs = [
        f"knowledge_gap:{signal.gap_id}",
        f"knowledge_recruitment_decision:{decision.decision_hash}",
        *signal.existing_evidence_refs,
        *signal.private_payload_refs,
    ]
    blocked = bool(decision.blockers)
    return Impingement(
        timestamp=timestamp,
        source="knowledge.recruitment",
        type=ImpingementType.SALIENCE_INTEGRATION,
        strength=_pressure_strength(signal),
        content={
            "narrative": narrative,
            "content_summary": signal.uncertainty_summary,
            "action_tendency": "withhold" if blocked else "route_attention",
            "speech_act_candidate": "knowledge_recruitment_blocked"
            if blocked
            else "knowledge_recruitment",
            "evidence_refs": evidence_refs,
            "private_payload_refs": list(signal.private_payload_refs),
            "domain": signal.domain,
            "knowledge_recruitment_claim_type": decision.claim_type,
            "source_acquisition_required": decision.source_acquisition_required,
            "blockers": list(decision.blockers),
            "authority_boundaries": list(decision.authority_boundaries),
            "inhibition_policy": "evaluate_sources_then_apply_existing_world_runtime_gates",
            "learning_policy": "recruited_guidance_is_prior_not_authority",
        },
        context={
            "trigger_reasons": list(decision.trigger_reasons),
            "provider_candidates": {
                "source_acquiring": list(decision.source_acquiring_provider_ids),
                "source_conditioned": list(decision.source_conditioned_provider_ids),
            },
            "egress_preflight_provider_ids": list(decision.egress_preflight_provider_ids),
            "egress_payload_refs": list(signal.private_payload_refs),
            "blockers": list(decision.blockers),
        },
    )


def _trigger_reasons(signal: KnowledgeGapSignal) -> list[str]:
    reasons: list[str] = []
    if signal.internal_confidence < RECRUITMENT_CONFIDENCE_THRESHOLD:
        reasons.append("internal_confidence_below_threshold")
    if signal.stakes != KnowledgeStakes.LOW:
        reasons.append(f"{signal.stakes.value}_stakes")
    if signal.freshness_need in {FreshnessNeed.CURRENT, FreshnessNeed.OPEN_WORLD}:
        reasons.append(f"{signal.freshness_need.value}_freshness_needed")
    if signal.public_claim_intended:
        reasons.append("public_claim_intended")
    return reasons


def _pressure_strength(signal: KnowledgeGapSignal) -> float:
    pressure = 1.0 - signal.internal_confidence
    if signal.stakes == KnowledgeStakes.MEDIUM:
        pressure += 0.12
    elif signal.stakes == KnowledgeStakes.HIGH:
        pressure += 0.24
    if signal.freshness_need in {FreshnessNeed.CURRENT, FreshnessNeed.OPEN_WORLD}:
        pressure += 0.16
    if signal.public_claim_intended:
        pressure += 0.12
    return max(0.0, min(1.0, round(pressure, 4)))


__all__ = [
    "AUTHORITY_BOUNDARIES",
    "FreshnessNeed",
    "KNOWLEDGE_RECRUITMENT_CLAIM_TYPE",
    "KNOWLEDGE_RECRUITMENT_VERSION",
    "KnowledgeGapSignal",
    "KnowledgeRecruitmentDecision",
    "KnowledgeStakes",
    "LOCAL_EVALUATOR_PROVIDER_ID",
    "build_knowledge_recruitment_decision",
    "build_knowledge_recruitment_impingement",
]
