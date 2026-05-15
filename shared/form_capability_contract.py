"""Generated form-capability contract for segment prep.

Replaces closed role eligibility with a generated form declaration. Existing
roles (tier_list, top_10, rant, react, iceberg, interview, lecture) become
exemplars and priors — they no longer act as admission criteria.

Design rule from the authority-transition doctrine (2026-05-06):
    Forms are generated; authority is gated.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FORM_CAPABILITY_CONTRACT_VERSION = 1


class FormOrigin(StrEnum):
    GENERATED = "generated"
    SELECTED_EXEMPLAR = "selected_exemplar"
    OPERATOR_REQUESTED = "operator_requested"
    FIXTURE = "fixture"
    REFUSAL_NO_CANDIDATE = "refusal_no_candidate"


class PublicPrivateCeiling(StrEnum):
    PRIVATE = "private"
    DRY_RUN = "dry_run"
    PUBLIC_LIVE = "public_live"
    PUBLIC_ARCHIVE = "public_archive"
    MONETIZABLE = "monetizable"


class RefusalMode(StrEnum):
    NARROW_SCOPE = "narrow_scope"
    EMIT_NO_CANDIDATE = "emit_no_candidate"
    EMIT_REFUSAL_BRIEF = "emit_refusal_brief"
    QUARANTINE = "quarantine"
    DEFER_TO_SOURCE_RECRUITMENT = "defer_to_source_recruitment"


class ClaimShape(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_claim_verbs: tuple[str, ...] = Field(min_length=1)
    authority_ceiling: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    uncertainty_posture: str = Field(min_length=1)
    correction_path: str = Field(min_length=1)


class AuthorityHypothesis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_transition: str = Field(min_length=1)
    evidence_needed: tuple[str, ...] = Field(min_length=1)
    falsification_criterion: str = Field(min_length=1)
    current_state: str = "scratch"


class ActionPrimitive(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    object_ref: str = Field(min_length=1)
    operation: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    capability_ref: str = ""
    fallback: str = Field(min_length=1)


class LiveEventObject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    object_id: str = Field(min_length=1)
    object_kind: str = Field(min_length=1)
    visible_payload: str = Field(min_length=1)
    doable_action: str = ""
    source_binding: str = Field(min_length=1)
    readback_required: bool = True


class ReadbackRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    readback_id: str = Field(min_length=1)
    must_show: str = Field(min_length=1)
    must_not_claim: str = Field(min_length=1)
    timeout_s: float = Field(gt=0.0)
    failure_mode: str = Field(min_length=1)


class FormCapabilityContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    form_capability_contract_version: Literal[1] = FORM_CAPABILITY_CONTRACT_VERSION

    form_id: str = Field(min_length=1)
    form_label: str = Field(min_length=1)
    form_origin: FormOrigin
    exemplar_refs: tuple[str, ...] = ()
    grounding_question: str = Field(min_length=1)
    claim_shape: ClaimShape
    authority_hypothesis: AuthorityHypothesis
    source_classes: tuple[str, ...] = Field(min_length=1)
    evidence_requirements: tuple[str, ...] = Field(min_length=1)
    live_event_object: LiveEventObject | None = None
    action_primitives: tuple[ActionPrimitive, ...] = ()
    layout_need_classes: tuple[str, ...] = ()
    readback_requirements: tuple[ReadbackRequirement, ...] = ()
    public_private_ceiling: PublicPrivateCeiling
    refusal_mode: RefusalMode

    @field_validator("exemplar_refs")
    @classmethod
    def _exemplar_refs_look_like_refs(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for ref in v:
            if not ref.strip() or ":" not in ref:
                raise ValueError(
                    f"exemplar_refs must be colon-separated ref strings, got {ref!r}"
                )
        return v

    @field_validator("source_classes")
    @classmethod
    def _source_classes_non_empty_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for item in v:
            if not item.strip():
                raise ValueError("source_classes must not contain empty strings")
        return v

    @field_validator("evidence_requirements")
    @classmethod
    def _evidence_requirements_non_empty_items(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for item in v:
            if not item.strip():
                raise ValueError("evidence_requirements must not contain empty strings")
        return v

    @model_validator(mode="after")
    def _refusal_forms_must_not_claim_public(self) -> FormCapabilityContract:
        if self.form_origin == FormOrigin.REFUSAL_NO_CANDIDATE:
            if self.public_private_ceiling not in {
                PublicPrivateCeiling.PRIVATE,
                PublicPrivateCeiling.DRY_RUN,
            }:
                raise ValueError(
                    "refusal/no-candidate forms must not claim public or higher ceiling"
                )
            if self.action_primitives:
                raise ValueError(
                    "refusal/no-candidate forms must not have action primitives"
                )
            if self.live_event_object is not None:
                raise ValueError(
                    "refusal/no-candidate forms must not claim a live event object"
                )
        return self

    @model_validator(mode="after")
    def _public_forms_need_live_event_and_readback(self) -> FormCapabilityContract:
        if self.public_private_ceiling in {
            PublicPrivateCeiling.PUBLIC_LIVE,
            PublicPrivateCeiling.PUBLIC_ARCHIVE,
            PublicPrivateCeiling.MONETIZABLE,
        }:
            if self.live_event_object is None:
                raise ValueError(
                    "forms claiming public ceiling must declare a live_event_object"
                )
            if not self.readback_requirements:
                raise ValueError(
                    "forms claiming public ceiling must declare readback_requirements"
                )
            if not self.action_primitives:
                raise ValueError(
                    "forms claiming public ceiling must declare action_primitives"
                )
        return self

    @model_validator(mode="after")
    def _action_primitives_have_unique_ids(self) -> FormCapabilityContract:
        ids = [a.action_id for a in self.action_primitives]
        if len(ids) != len(set(ids)):
            raise ValueError("action_primitives must have unique action_ids")
        return self

    @model_validator(mode="after")
    def _readback_ids_unique(self) -> FormCapabilityContract:
        ids = [r.readback_id for r in self.readback_requirements]
        if len(ids) != len(set(ids)):
            raise ValueError("readback_requirements must have unique readback_ids")
        return self


def form_capability_contract_sha256(contract: FormCapabilityContract) -> str:
    payload = contract.model_dump(mode="json")
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_RUBRIC_RECITATION_RE = re.compile(
    r"\b(?:"
    r"source consequence contract|quality[- ]budget principle|"
    r"eligibility gate|excellence selection|detector[- ]trigger theater|"
    r"quality range receipt|positive[- ]excellence receipt|"
    r"consultation[_ ]manifest|role[_ ]contract[_ ]refs|"
    r"non[- ]anthropomorphic force|runtime readback doctrine|"
    r"layout responsibility doctrine|proposal[- ]only layout"
    r")\b",
    re.IGNORECASE,
)

_REGEX_THEATER_EXACT_PHRASES = (
    "Place [item] in [S/A/B/C/D]-tier",
    "#N is... or Number N:",
    "surface level, going deeper, obscure, deepest, bottom of the iceberg",
    "Where does chat land",
    "chat can challenge",
    "drop it in chat",
    "According to [source]",
    "[Source] argues",
    "[Source] writes",
    "[Source] shows",
)

_REGEX_THEATER_RE = re.compile(
    r"\[(?:item|source|S/A/B/C/D|subject|topic|criteria|ranking)\]",
    re.IGNORECASE,
)


def _has_source_consequence(contract: FormCapabilityContract) -> bool:
    if not contract.evidence_requirements:
        return False
    change_verbs = ("change", "narrow", "block", "contradict", "weaken", "strengthen", "alter")
    has_change_verb = any(
        any(verb in req.lower() for verb in change_verbs)
        for req in contract.evidence_requirements
    )
    if not has_change_verb:
        return False
    gq = contract.grounding_question.strip()
    return len(gq) >= 10


def _is_rubric_recitation(contract: FormCapabilityContract) -> list[str]:
    violations: list[str] = []
    all_text = " ".join([
        contract.grounding_question,
        contract.claim_shape.scope,
        contract.claim_shape.uncertainty_posture,
        contract.authority_hypothesis.falsification_criterion,
        *(req for req in contract.evidence_requirements),
    ])
    framework_hits = _RUBRIC_RECITATION_RE.findall(all_text)
    if len(framework_hits) >= 2 and not _has_source_consequence(contract):
        violations.append(
            f"rubric_recitation: {len(framework_hits)} framework vocabulary hits "
            f"without source consequence ({', '.join(framework_hits[:4])})"
        )
    return violations


def _is_regex_theater(contract: FormCapabilityContract) -> list[str]:
    violations: list[str] = []
    all_text = " ".join([
        contract.grounding_question,
        *(a.operation for a in contract.action_primitives),
        *(a.object_ref for a in contract.action_primitives),
    ])
    template_hits = _REGEX_THEATER_RE.findall(all_text)
    if template_hits:
        violations.append(
            f"regex_theater: {len(template_hits)} bracket-template placeholders "
            f"found — actions must use concrete object refs, not templates"
        )
    for action in contract.action_primitives:
        for phrase in _REGEX_THEATER_EXACT_PHRASES:
            if phrase.lower() in action.operation.lower():
                violations.append(
                    f"regex_theater: action {action.action_id!r} uses exact rubric "
                    f"trigger phrase {phrase!r} as operation"
                )
    if contract.public_private_ceiling not in {
        PublicPrivateCeiling.PRIVATE,
        PublicPrivateCeiling.DRY_RUN,
    }:
        ungrounded = [
            a.action_id for a in contract.action_primitives if not a.evidence_refs
        ]
        if ungrounded and len(ungrounded) == len(contract.action_primitives):
            violations.append(
                f"regex_theater: all {len(ungrounded)} action primitives lack "
                f"evidence_refs — actions must be source-bound"
            )
    return violations


def validate_form_capability_contract(
    contract: FormCapabilityContract,
) -> dict[str, Any]:
    violations: list[dict[str, str]] = []

    for detail in _is_rubric_recitation(contract):
        violations.append({"reason": "rubric_recitation", "detail": detail})

    for detail in _is_regex_theater(contract):
        violations.append({"reason": "regex_theater", "detail": detail})

    gq = contract.grounding_question.strip()
    if gq and "?" not in gq and len(gq) < 20:
        if not _has_source_consequence(contract):
            violations.append({
                "reason": "grounding_question_not_testable",
                "detail": (
                    f"grounding_question is {len(gq)} chars with no '?' and no "
                    f"source consequence in evidence_requirements"
                ),
            })

    hyp = contract.authority_hypothesis
    if hyp.current_state == hyp.requested_transition:
        violations.append({
            "reason": "authority_hypothesis_no_transition",
            "detail": (
                f"current_state and requested_transition are both "
                f"{hyp.current_state!r} — hypothesis must request a transition"
            ),
        })

    generic_verbs = {"do", "make", "perform", "execute", "create", "generate"}
    real_verbs = [
        v for v in contract.claim_shape.allowed_claim_verbs if v.lower() not in generic_verbs
    ]
    if not real_verbs:
        violations.append({
            "reason": "claim_shape_generic_verbs_only",
            "detail": (
                f"all claim verbs are generic "
                f"({', '.join(contract.claim_shape.allowed_claim_verbs)})"
            ),
        })

    if contract.public_private_ceiling in {
        PublicPrivateCeiling.PUBLIC_LIVE,
        PublicPrivateCeiling.PUBLIC_ARCHIVE,
        PublicPrivateCeiling.MONETIZABLE,
    } and not contract.layout_need_classes:
        violations.append({
            "reason": "public_form_missing_layout_needs",
            "detail": "forms claiming public ceiling must declare layout_need_classes",
        })

    return {"ok": not violations, "violations": violations}
