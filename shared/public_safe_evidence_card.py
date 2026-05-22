"""PublicSafeEvidenceCard — public, citable evidence container.

Extracted and redacted from private Evidence Explorer records after allowlist and
redaction checks pass. Contains mandatory source_quality and license_provenance.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shared.capability_evidence_card import PrivacyClass


class SourceQuality(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RedactionPolicy(StrEnum):
    NONE = "none"
    NAMES = "names"
    VALUES = "values"
    FULL = "full"


class ClaimCeiling(StrEnum):
    NO_CLAIM = "no_claim"
    INTERNAL_ONLY = "internal_only"
    PUBLICATION_WITNESS = "publication_witness"
    PEER_REVIEWED = "peer_reviewed"


class GateVerdict(BaseModel):
    model_config = ConfigDict(frozen=True)

    approved: bool
    reason: str | None = None


class PublicSafeEvidenceCard(BaseModel):
    """Public-safe representation of an evidence card."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(min_length=1)
    source_card_id: str = Field(min_length=1)
    public_claim: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)
    source_quality: SourceQuality
    license_provenance: str = Field(min_length=1)
    redaction_policy: RedactionPolicy = RedactionPolicy.NONE
    redacted_fields: list[str] = Field(default_factory=list)
    public_allowlist_approved: bool = False
    privacy_class: PrivacyClass = PrivacyClass.PUBLIC
    freshness_deadline: datetime | None = None
    limitations: list[str] = Field(default_factory=list)
    what_this_does_not_prove: list[str]
    claim_ceiling: ClaimCeiling = ClaimCeiling.NO_CLAIM
    methodology_ref: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def passes_gate(self, *, now: datetime | None = None) -> GateVerdict:
        """Evaluate if the card passes the publication gate."""
        if not self.public_allowlist_approved:
            return GateVerdict(
                approved=False,
                reason="public_allowlist_approved is False",
            )
        if self.freshness_deadline is not None:
            from datetime import UTC

            current = now or datetime.now(UTC)
            if self.freshness_deadline.tzinfo is None:
                current = current.replace(tzinfo=None)
            if current > self.freshness_deadline:
                return GateVerdict(
                    approved=False,
                    reason="freshness_deadline has passed",
                )
        return GateVerdict(approved=True)


__all__ = [
    "PublicSafeEvidenceCard",
    "SourceQuality",
    "RedactionPolicy",
    "ClaimCeiling",
    "GateVerdict",
]
