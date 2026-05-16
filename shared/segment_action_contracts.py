"""First-class action contracts for segment prep.

Canonical tier-list and interview action kinds. Replaces regex phrase
matching with structured action contracts that compile to bounded
runtime obligations with stable IDs, payload refs, and readback
requirements.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TierListActionKind(StrEnum):
    TIER_VISUAL_DISPLAY = "tier_visual_display"
    TIER_COMPARISON = "tier_comparison"
    TIER_RERANKING = "tier_reranking"
    SOURCE_BOUND_JUSTIFICATION = "source_bound_justification"


class InterviewActionKind(StrEnum):
    CONSENT_CHECK = "consent_check"
    QUESTION_ASK = "question_ask"
    ANSWER_RECEIPT = "answer_receipt"
    NO_ANSWER_RECEIPT = "no_answer_receipt"
    REFUSAL_OFF_RECORD = "refusal_off_record"
    ANSWER_SCOPE_READBACK = "answer_scope_readback"
    FOLLOWUP_SELECTION = "followup_selection"


class ActionContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    object_ref: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    readback_id: str = ""
    readback_requirement: str = ""
    fallback: str = Field(min_length=1)
    runtime_obligation_id: str = ""


class TierListActionContract(ActionContract):
    kind: str = Field(min_length=1)
    tier_criteria_ref: str = ""
    tier_labels: tuple[str, ...] = ()


class InterviewActionContract(ActionContract):
    kind: str = Field(min_length=1)
    consent_receipt_ref: str = ""
    answer_authority_ref: str = ""
    release_scope_ref: str = ""
    question_ladder_position: int = -1


def validate_tier_list_actions(actions: list[ActionContract]) -> dict[str, list[str]]:
    violations: list[str] = []
    tier_kinds = set(TierListActionKind)
    found_kinds = {a.kind for a in actions if a.kind in tier_kinds}
    if not found_kinds:
        violations.append(
            "no tier-list action kinds found — expected at least one of " + str(tier_kinds)
        )
    for action in actions:
        if action.kind in tier_kinds and not action.evidence_refs:
            violations.append(f"tier-list action {action.action_id!r} lacks evidence_refs")
    return {"ok": not violations, "violations": violations}


def validate_interview_actions(actions: list[ActionContract]) -> dict[str, list[str]]:
    violations: list[str] = []
    interview_kinds = set(InterviewActionKind)
    found_kinds = {a.kind for a in actions if a.kind in interview_kinds}

    if InterviewActionKind.CONSENT_CHECK not in found_kinds:
        violations.append("interview actions must include consent_check")
    if InterviewActionKind.QUESTION_ASK not in found_kinds:
        violations.append("interview actions must include question_ask")

    for action in actions:
        if action.kind == InterviewActionKind.QUESTION_ASK and not action.evidence_refs:
            violations.append(
                f"question_ask action {action.action_id!r} lacks evidence_refs (questions must be source-grounded)"
            )

    return {"ok": not violations, "violations": violations}
