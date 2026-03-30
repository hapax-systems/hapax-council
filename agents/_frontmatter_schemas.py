"""shared/frontmatter_schemas.py — Pydantic schemas for filesystem-as-bus document types.

Validates frontmatter at write boundaries. Each schema defines the required fields
for a document type flowing through the reactive engine or into the Obsidian vault.

Usage:
    from agents._frontmatter_schemas import validate_frontmatter, BriefingFrontmatter

    validate_frontmatter({"type": "briefing", "date": "2026-03-23", ...}, BriefingFrontmatter)
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError


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


# ── RAG source document types (written by sync agents) ─────────────────────


class RagSourceFrontmatter(_BaseFrontmatter):
    """Minimal schema for RAG source documents written by sync agents."""

    content_type: str
    source_service: str
    date: str | None = None


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
