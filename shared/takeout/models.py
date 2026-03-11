"""models.py — Core data structures for Takeout ingestion.

NormalizedRecord is the universal intermediate representation.
Every parser emits these, and the processor routes them to
the appropriate data path (structured vs unstructured).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class ServiceConfig:
    """Configuration for a single Takeout service."""
    parser: str                                # parser module name in shared.takeout.parsers
    takeout_path: str                          # path within Takeout ZIP (e.g. "Chrome", "Mail")
    tier: int                                  # 1=high signal, 2=high volume, 3=supplementary
    data_path: Literal["structured", "unstructured"] = "unstructured"
    modality_defaults: list[str] = field(default_factory=list)
    content_type: str = ""                     # default content_type for records
    experimental: bool = False                 # parser is unvalidated against real data
    alt_paths: list[str] = field(default_factory=list)  # alternate folder names in ZIP


@dataclass
class NormalizedRecord:
    """Universal record from any Takeout service.

    Carries enough metadata for cross-modal queries while keeping
    the core content in a single text field. The record_id is
    deterministic — same input always produces the same ID.
    """
    record_id: str                              # sha256(platform + service + source_key)
    platform: str                               # "google"
    service: str                                # "gmail", "chrome", "youtube", etc.
    title: str                                  # human-readable label
    text: str                                   # primary content
    content_type: str                           # "email", "note", "search_query", etc.
    timestamp: datetime | None = None           # when this happened
    modality_tags: list[str] = field(default_factory=list)
    people: list[str] = field(default_factory=list)
    location: str = ""                          # place name or coordinates
    categories: list[str] = field(default_factory=list)
    structured_fields: dict[str, Any] = field(default_factory=dict)
    data_path: Literal["structured", "unstructured"] = "unstructured"
    source_path: str = ""                       # path within ZIP for provenance


def make_record_id(platform: str, service: str, source_key: str) -> str:
    """Generate a deterministic record ID from platform + service + source key."""
    raw = f"{platform}:{service}:{source_key}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
