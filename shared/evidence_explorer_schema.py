"""Canonical record schema for the private Hapax Evidence Explorer.

The Evidence Explorer indexes redacted summaries and metadata for local evidence
artifacts. A record is intentionally descriptive only: it can point to evidence
and expose facets for private filtering, but it cannot mark work as authorized,
released, complete, or public-safe.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from shared.route_metadata_schema import FreshnessState

FacetValue = str | int | float | bool | tuple[str, ...]


class EvidenceExplorerRecordKind(StrEnum):
    """Controlled vocabulary for artifacts the Evidence Explorer may index."""

    DISPATCH_TRACE = "dispatch_trace"
    GROUNDING_RECEIPT = "grounding_receipt"
    EVAL_RECEIPT = "eval_receipt"
    EVIDENCE_CARD = "evidence_card"
    QDRANT_METADATA_SUMMARY = "qdrant_metadata_summary"
    CC_TASK_CLOSE_DOSSIER = "cc_task_close_dossier"


class EvidenceExplorerPrivacyClass(StrEnum):
    """Privacy class for explorer records and their redacted summaries."""

    PRIVATE = "private"
    REDACTED_PUBLIC = "redacted_public"


class EvidenceExplorerLink(BaseModel):
    """A typed link from one explorer record to a related local artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rel: str = Field(
        min_length=1,
        description="Relationship name, such as source, task_note, parent_spec, receipt, or qdrant.",
    )
    target: str = Field(
        min_length=1,
        description="Path, URI, or stable local reference for the related evidence artifact.",
    )
    label: str = Field(
        default="",
        description="Optional operator-facing label for the link target.",
    )

    @field_validator("rel", "target", "label")
    @classmethod
    def _strip_text(cls, value: str, info: ValidationInfo) -> str:
        stripped = value.strip()
        if info.field_name in {"rel", "target"} and not stripped:
            raise ValueError("field must not be blank")
        return stripped


class EvidenceExplorerRecord(BaseModel):
    """Private, read-only explorer metadata for one evidence-like artifact.

    Required fields bind each record to its source artifact, authority context,
    route metadata, privacy posture, freshness state, hashes, linked artifacts,
    filter facets, and redacted searchable summary. The schema has no fields for
    authorization, completion, release, or publication status.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str = Field(
        min_length=1,
        description="Canonical filesystem path or local source reference for the artifact indexed.",
    )
    record_kind: EvidenceExplorerRecordKind = Field(
        description="Machine-readable artifact kind used for filtering and ingest routing.",
    )
    timestamp: datetime = Field(
        description="Timezone-aware timestamp for the source artifact or observation.",
    )
    authority_case: str = Field(
        min_length=1,
        description="AuthorityCase identifier that admitted this evidence chain.",
    )
    parent_spec: str = Field(
        min_length=1,
        description="Parent request/spec path or stable reference that bounds the work authority.",
    )
    task_id: str = Field(
        min_length=1,
        description="cc-task or routed work item identifier associated with the artifact.",
    )
    request_id: str = Field(
        min_length=1,
        description="Request identifier associated with the evidence chain.",
    )
    route: str = Field(
        min_length=1,
        description="Route or lane metadata observed when the artifact was produced.",
    )
    platform: str = Field(
        min_length=1,
        description="Execution platform that produced or owns the artifact, such as codex or claude.",
    )
    privacy_class: EvidenceExplorerPrivacyClass = Field(
        description="Private explorer privacy class for the record summary and metadata.",
    )
    freshness_state: FreshnessState = Field(
        description="Controlled freshness state observed for the source evidence.",
    )
    hashes: dict[str, str] = Field(
        min_length=1,
        description="Named content hashes, usually including source_sha256 or frontmatter_sha256.",
    )
    links: tuple[EvidenceExplorerLink, ...] = Field(
        description="Structured links to adjacent local evidence, source, task, or receipt artifacts.",
    )
    facets: dict[str, FacetValue] = Field(
        description="Supplemental scalar or string-list metadata facets for private filtering.",
    )
    redacted_summary: str = Field(
        min_length=1,
        max_length=4000,
        description="Searchable summary with raw private evidence, secrets, and sensitive text removed.",
    )

    @field_validator(
        "source_path",
        "authority_case",
        "parent_spec",
        "task_id",
        "request_id",
        "route",
        "platform",
        "redacted_summary",
    )
    @classmethod
    def _required_text_is_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be blank")
        return stripped

    @field_validator("timestamp")
    @classmethod
    def _timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @field_validator("hashes")
    @classmethod
    def _hashes_are_named_strings(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for key, digest in value.items():
            clean_key = key.strip()
            clean_digest = digest.strip()
            if not clean_key or not clean_digest:
                raise ValueError("hash names and values must be non-blank")
            cleaned[clean_key] = clean_digest
        return cleaned

    @field_validator("facets")
    @classmethod
    def _facet_keys_are_named(cls, value: dict[str, FacetValue]) -> dict[str, FacetValue]:
        cleaned: dict[str, FacetValue] = {}
        for key, facet_value in value.items():
            clean_key = key.strip()
            if not clean_key:
                raise ValueError("facet names must be non-blank")
            cleaned[clean_key] = facet_value
        return cleaned


__all__ = [
    "EvidenceExplorerLink",
    "EvidenceExplorerPrivacyClass",
    "EvidenceExplorerRecord",
    "EvidenceExplorerRecordKind",
    "FacetValue",
    "FreshnessState",
]
