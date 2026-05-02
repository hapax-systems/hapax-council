"""YouTube packaging claim policy.

Defines the allowed and blocked claim classes for YouTube packaging
fields (titles, descriptions, thumbnails, chapters, captions, Shorts,
channel sections), the public-event-ref requirement for liveness /
run-result / refusal / correction / archive / monetization claims,
and the prohibition of expert-verdict framing, unsupported
superlatives, rights-risky media claims, and trend-as-truth claims.

This module is consumed by `youtube-content-programming-packaging-compiler`
(downstream cc-task) and the Shorts/chapter/caption emitters; it
provides the gate that all packaging payloads must pass before being
published to YouTube.

Refusal/correction language templates are also defined here so
downstream emitters use a single canonical phrasing.

cc-task: youtube-packaging-claim-policy (WSJF 8.7, P1).
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClaimClass(StrEnum):
    """Enumerated claim classes for YouTube packaging fields."""

    DESCRIPTIVE = "descriptive"
    LIVENESS = "liveness"
    RUN_RESULT = "run_result"
    REFUSAL = "refusal"
    CORRECTION = "correction"
    ARCHIVE = "archive"
    MONETIZATION = "monetization"


class BlockedClaimReason(StrEnum):
    """Reasons a packaging payload may be blocked from publication."""

    EXPERT_VERDICT_FRAMING = "expert_verdict_framing"
    UNSUPPORTED_SUPERLATIVE = "unsupported_superlative"
    RIGHTS_RISKY_MEDIA_CLAIM = "rights_risky_media_claim"
    TREND_AS_TRUTH_CLAIM = "trend_as_truth_claim"
    MISSING_PUBLIC_EVENT_REF = "missing_public_event_ref"
    UNKNOWN_CLAIM_CLASS = "unknown_claim_class"


_CLAIM_CLASSES_REQUIRING_PUBLIC_EVENT_REF = frozenset(
    {
        ClaimClass.LIVENESS,
        ClaimClass.RUN_RESULT,
        ClaimClass.REFUSAL,
        ClaimClass.CORRECTION,
        ClaimClass.ARCHIVE,
        ClaimClass.MONETIZATION,
    }
)


_EXPERT_VERDICT_PATTERNS = (
    r"\b(?:as|the)\s+(?:expert|authority|specialist|professional)\s+(?:says|verdict|opinion|finding)\b",
    r"\b(?:expert|professional|authority)['’]?s\s+(?:verdict|opinion|finding|conclusion)\b",
)

_SUPERLATIVE_PATTERNS = (
    r"\b(?:best|worst|first|only|most|greatest|fastest|smallest|largest)\b[\w\s]{0,30}\b(?:ever|in\s+the\s+world|of\s+all\s+time|on\s+earth)\b",
    r"\b(?:never|always)\s+(?:before|seen|done)\b",
)

_RIGHTS_RISKY_PATTERNS = (
    r"\b(?:featuring|covers?|samples?)\s+[A-Z][a-z]+\s+[A-Z][a-z]+\b",
    r"\b(?:soundtrack|songs?|tracks?)\s+by\s+[A-Z][a-z]+\b",
)

_TREND_AS_TRUTH_PATTERNS = (
    r"\b(?:trending|viral|going\s+viral)\s+(?:proves?|shows?|means?)\b",
    r"\b(?:everyone|all\s+the\s+kids|the\s+internet)\s+(?:agrees?|knows?|says?)\b",
)


class PackagingClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)
    claim_class: ClaimClass
    public_event_ref: str | None = None
    evidence_refs: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _require_public_event_ref(self):
        if self.claim_class in _CLAIM_CLASSES_REQUIRING_PUBLIC_EVENT_REF:
            if not self.public_event_ref:
                raise ValueError(
                    f"claim_class {self.claim_class.value!r} requires public_event_ref"
                )
        return self


class PackagingPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    field_kind: Literal[
        "title",
        "description",
        "thumbnail_text",
        "chapter",
        "caption",
        "shorts_caption",
        "channel_section",
    ]
    field_text: str = Field(min_length=1)
    claims: tuple[PackagingClaim, ...] = Field(default_factory=tuple)


class PolicyVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    blockers: tuple[BlockedClaimReason, ...] = Field(default_factory=tuple)
    blocker_details: tuple[str, ...] = Field(default_factory=tuple)


def _scan_for_patterns(text: str, patterns: tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    for pattern in patterns:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            matches.append(m.group(0))
    return matches


def evaluate_payload(payload: PackagingPayload) -> PolicyVerdict:
    """Apply the packaging policy gate to a payload."""
    blockers: list[BlockedClaimReason] = []
    details: list[str] = []

    for claim in payload.claims:
        if (
            claim.claim_class in _CLAIM_CLASSES_REQUIRING_PUBLIC_EVENT_REF
            and not claim.public_event_ref
        ):
            blockers.append(BlockedClaimReason.MISSING_PUBLIC_EVENT_REF)
            details.append(f"claim {claim.text[:50]!r} missing public_event_ref")

    text = payload.field_text

    for hits, reason, label in (
        (
            _scan_for_patterns(text, _EXPERT_VERDICT_PATTERNS),
            BlockedClaimReason.EXPERT_VERDICT_FRAMING,
            "expert-verdict phrasing",
        ),
        (
            _scan_for_patterns(text, _SUPERLATIVE_PATTERNS),
            BlockedClaimReason.UNSUPPORTED_SUPERLATIVE,
            "unsupported superlative",
        ),
        (
            _scan_for_patterns(text, _RIGHTS_RISKY_PATTERNS),
            BlockedClaimReason.RIGHTS_RISKY_MEDIA_CLAIM,
            "rights-risky media claim",
        ),
        (
            _scan_for_patterns(text, _TREND_AS_TRUTH_PATTERNS),
            BlockedClaimReason.TREND_AS_TRUTH_CLAIM,
            "trend-as-truth claim",
        ),
    ):
        if hits:
            blockers.append(reason)
            details.append(f"{label}: {hits[0]!r}")

    return PolicyVerdict(
        allowed=not blockers,
        blockers=tuple(blockers),
        blocker_details=tuple(details),
    )


REFUSAL_LANGUAGE_TEMPLATES: dict[str, str] = {
    "in_person_event_refused": (
        "This programme run does not include in-person event participation."
    ),
    "platform_partnership_refused": (
        "This channel does not accept platform partnerships, sponsorships, or paid placements."
    ),
    "interview_request_refused": (
        "This programme run does not engage with media interview requests."
    ),
    "expert_panel_refused": (
        "This programme run does not participate in expert panels or advisory roles."
    ),
}

CORRECTION_LANGUAGE_TEMPLATES: dict[str, str] = {
    "claim_corrected": (
        "Correction: an earlier description of {original_topic} has been "
        "revised to reflect the corrected understanding documented at "
        "{correction_ref}."
    ),
    "duration_corrected": (
        "Correction: stated runtime of {original_duration} has been "
        "updated to {corrected_duration} per archive verification."
    ),
    "attribution_corrected": (
        "Correction: attribution previously given to {original_attribution} "
        "has been updated to {corrected_attribution}."
    ),
}


__all__ = [
    "ClaimClass",
    "BlockedClaimReason",
    "PackagingClaim",
    "PackagingPayload",
    "PolicyVerdict",
    "evaluate_payload",
    "REFUSAL_LANGUAGE_TEMPLATES",
    "CORRECTION_LANGUAGE_TEMPLATES",
]
