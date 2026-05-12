"""RAG inventory/metadata-only payload detection helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

METADATA_CONTENT_TIERS = frozenset({"metadata_only", "metadata-only", "stub", "inventory"})
METADATA_SOURCE_MARKERS = ("/.meta/", "/rag-sources/gdrive/.meta/")
METADATA_TEXT_MARKERS = ("**drive link:**", "gdrive_link:")


def _lower_text(value: object) -> str:
    return str(value or "").lower()


def _is_false_like(value: object) -> bool:
    return value is False or _lower_text(value) == "false"


def inventory_reason(payload: Mapping[str, Any]) -> str | None:
    """Return the inventory/metadata-only reason for a Qdrant payload."""
    if payload.get("is_metadata_only") is True:
        return "is_metadata_only=true"
    if _lower_text(payload.get("content_tier")) in METADATA_CONTENT_TIERS:
        return "content_tier=metadata_only"
    if _is_false_like(payload.get("retrieval_eligible")):
        return "retrieval_eligible=false"

    source = _lower_text(payload.get("source"))
    if any(marker in source for marker in METADATA_SOURCE_MARKERS):
        return "source=.meta"

    text = _lower_text(payload.get("text"))
    if any(marker in text for marker in METADATA_TEXT_MARKERS):
        return "text=drive-link-stub"

    return None


def is_inventory_payload(payload: Mapping[str, Any]) -> bool:
    """Return whether a Qdrant payload is inventory/metadata-only evidence."""
    return inventory_reason(payload) is not None
