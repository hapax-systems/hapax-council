"""shared/frontmatter_schemas.py — Pydantic schemas for filesystem-as-bus document types.

Validates frontmatter at write boundaries. Each schema defines the required fields
for a document type flowing through the reactive engine or into the Obsidian vault.

Usage:
    from shared.frontmatter_schemas import validate_frontmatter, BriefingFrontmatter

    validate_frontmatter({"type": "briefing", "date": "2026-03-23", ...}, BriefingFrontmatter)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from shared.route_metadata_schema import AuthorityLevel, MutationSurface, QualityFloor


class _BaseFrontmatter(BaseModel):
    """Base for all frontmatter schemas. Allows extra fields for forward compatibility."""

    model_config = ConfigDict(extra="allow")


# ── Vault document types (written by vault_writer.py) ───────────────────────


class BriefingFrontmatter(_BaseFrontmatter):
    type: Literal["briefing"]
    date: str
    source: str
    tags: list[str]


class DigestFrontmatter(_BaseFrontmatter):
    type: Literal["digest"]
    date: str
    source: str
    tags: list[str]


class NudgeFrontmatter(_BaseFrontmatter):
    type: Literal["nudges"]
    updated: str
    source: str
    tags: list[str]


class GoalsFrontmatter(_BaseFrontmatter):
    type: Literal["goals"]
    updated: str
    source: str
    tags: list[str]


class DecisionFrontmatter(_BaseFrontmatter):
    type: Literal["decision"]
    status: str
    date: str
    tags: list[str]


class BridgePromptFrontmatter(_BaseFrontmatter):
    type: Literal["bridge-prompt"]
    source: str
    tags: list[str]


# ── Operator intake and cc-task document types ──────────────────────────────


class _RouteMetadataFrontmatterFields(_BaseFrontmatter):
    route_metadata_schema: Literal[1] | None = None
    quality_floor: QualityFloor | None = None
    authority_level: AuthorityLevel | None = None
    mutation_surface: MutationSurface | None = None
    mutation_scope_refs: list[str] | None = None
    risk_flags: dict[str, Any] | None = None
    context_shape: dict[str, Any] | None = None
    verification_surface: dict[str, Any] | None = None
    route_constraints: dict[str, Any] | None = None
    review_requirement: dict[str, Any] | None = None
    route_metadata: dict[str, Any] | None = None


class CcTaskFrontmatter(_RouteMetadataFrontmatterFields):
    type: Literal["cc-task"]
    task_id: str
    title: str
    status: str
    tags: list[str] | None = None


class HapaxRequestFrontmatter(_RouteMetadataFrontmatterFields):
    type: Literal["hapax-request"]
    request_id: str
    title: str
    status: str
    tags: list[str] | None = None


# ── RAG source document types (written by sync agents) ─────────────────────


class RagSourceFrontmatter(_BaseFrontmatter):
    """Minimal schema for RAG source documents written by sync agents."""

    content_type: str
    source_service: str
    date: str | None = None


FRONTMATTER_SCHEMA_REGISTRY: dict[str, type[_BaseFrontmatter]] = {
    "briefing": BriefingFrontmatter,
    "digest": DigestFrontmatter,
    "nudges": NudgeFrontmatter,
    "goals": GoalsFrontmatter,
    "decision": DecisionFrontmatter,
    "bridge-prompt": BridgePromptFrontmatter,
    "cc-task": CcTaskFrontmatter,
    "hapax-request": HapaxRequestFrontmatter,
    "rag-source": RagSourceFrontmatter,
}


# ── Validation utility ──────────────────────────────────────────────────────


def validate_frontmatter(data: dict, schema: type[_BaseFrontmatter]) -> _BaseFrontmatter:
    """Validate a frontmatter dict against a schema.

    Args:
        data: Frontmatter dict to validate.
        schema: Pydantic model class to validate against.

    Returns:
        Validated model instance.

    Raises:
        ValueError: If validation fails, with details of which fields are wrong.
    """
    try:
        return schema.model_validate(data)
    except ValidationError as e:
        raise ValueError(f"Frontmatter validation failed for {schema.__name__}: {e}") from e
