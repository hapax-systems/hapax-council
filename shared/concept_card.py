"""HapaxConceptCard — model-card style records for novel Hapax concepts.

Concepts carry claim scope, formation/provenance, limitations, related terms,
evidence references, and public allowlist approvals. This card is explanatory
and evidentiary, designed to address the conceptual wall problem without leaking
private or secret material.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PrivacyClass(StrEnum):
    """Privacy clearance level of a card."""

    PUBLIC = "public"
    INTERNAL = "internal"
    REDACTED = "redacted"
    OPERATOR_ONLY = "operator_only"
    CONSENT_GATED = "consent_gated"


class ClaimCeiling(StrEnum):
    """Graduated claim authority tier representing the maximum claim strength."""

    NO_CLAIM = "no_claim"
    INTERNAL_ONLY = "internal_only"
    PUBLICATION_WITNESS = "publication_witness"
    PEER_REVIEWED = "peer_reviewed"


class RedactionPolicy(StrEnum):
    """Redaction policies applied before public publication."""

    NONE = "none"
    NAMES = "names"
    VALUES = "values"
    FULL = "full"


class SourceQuality(StrEnum):
    """Tier-based quality rating of underlying sources/grounding."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class HapaxConceptCard(BaseModel):
    """Canonical model card record for a novel Hapax concept.

    Provides a public explanation layer that makes novel concepts and public
    claims legible without overclaiming, leaking private material, or hiding
    limitations.
    """

    model_config = ConfigDict(frozen=True)

    concept_id: str = Field(
        ...,
        min_length=1,
        description="Unique stable persistent identifier for the concept.",
    )
    concept_name: str = Field(
        ...,
        min_length=1,
        description="Human-readable name of the concept.",
    )
    description: str = Field(
        ...,
        min_length=1,
        description="Detailed description of the concept's meaning and purpose.",
    )
    formation_provenance: list[str] = Field(
        default_factory=list,
        description="Provenance chain of the concept's formation (e.g. research -> spec -> implementation).",
    )
    claim_scope: str = Field(
        ...,
        min_length=1,
        description="The scope of what this concept claims to cover.",
    )
    claim_ceiling: ClaimCeiling = Field(
        ...,
        description="The maximum claim strength or authority tier.",
    )
    evidence_refs: list[str] = Field(
        default_factory=list,
        description="References to supporting evidence cards or documents.",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Known limitations or boundaries of the concept.",
    )
    what_this_does_not_prove: str = Field(
        ...,
        min_length=1,
        description="Explicit statement of what the existence of this concept does NOT establish.",
    )
    related_terms: list[str] = Field(
        default_factory=list,
        description="Related terms or concepts for cross-reference.",
    )
    privacy_class: PrivacyClass = Field(
        default=PrivacyClass.INTERNAL,
        description="Privacy clearance level of this concept card.",
    )
    redaction_policy: RedactionPolicy = Field(
        default=RedactionPolicy.NONE,
        description="Redaction policy applied to the card before public publication.",
    )
    public_allowlist_approved: bool = Field(
        default=False,
        description="Whether the concept card has been explicitly approved for the public allowlist.",
    )
    source_quality: SourceQuality = Field(
        default=SourceQuality.MEDIUM,
        description="Overall quality rating of the underlying grounding/sources.",
    )
    license_provenance: str = Field(
        ...,
        min_length=1,
        description="License and source provenance information.",
    )
    freshness_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp indicating when this concept card was last verified or updated.",
    )


__all__ = [
    "HapaxConceptCard",
    "ClaimCeiling",
    "PrivacyClass",
    "RedactionPolicy",
    "SourceQuality",
]
