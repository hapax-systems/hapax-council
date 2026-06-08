"""Resolved source packets for segment prep planning.

The planner receives resolved source packets — not naked topic strings.
Each packet binds a source reference to its content hash, freshness,
rights status, and source consequence.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# A cited handle is an index into a recruited ``ResolvedSourceSet`` — NOT a
# free-text ref the model invents. ``src:3`` means "the 4th packet in the
# closed set the recruiter resolved". A fabricated ref (``vault:research-notes``,
# ``vault:2008-financial-crisis``) is not a handle and cannot dereference, so it
# is unconstructable-or-refused rather than shape-passed.
HANDLE_PREFIX = "src:"


class SourcePacket(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_ref: str = Field(min_length=1)
    content_hash: str = Field(min_length=1)
    snippet: str = Field(min_length=1)
    freshness: str = Field(min_length=1)
    rights_status: str = "internal"
    source_consequence: str = ""
    resolved_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ResolvedSourceSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    topic: str = Field(min_length=1)
    packets: tuple[SourcePacket, ...] = Field(min_length=1)
    set_hash: str = ""

    def compute_set_hash(self) -> str:
        payload = json.dumps(
            [p.model_dump(mode="json") for p in self.packets],
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def handles(self) -> tuple[str, ...]:
        """Every citable handle in the set — one per packet, by index."""
        return tuple(handle_for_index(i) for i in range(len(self.packets)))

    def packet_for_handle(self, handle: str) -> SourcePacket | None:
        """Dereference a handle to its packet, or None if it does not resolve.

        Returning None for an out-of-range/malformed handle IS the constructive
        constraint: a fabricated handle cannot name a real source.
        """
        index = parse_handle(handle)
        if index is None or index < 0 or index >= len(self.packets):
            return None
        return self.packets[index]

    def content_hash_for_handle(self, handle: str) -> str | None:
        packet = self.packet_for_handle(handle)
        return packet.content_hash if packet else None


def handle_for_index(index: int) -> str:
    """The canonical citable handle for the packet at ``index``."""
    if index < 0:
        raise ValueError(f"handle index must be non-negative, got {index}")
    return f"{HANDLE_PREFIX}{index}"


def parse_handle(handle: str) -> int | None:
    """Parse ``src:N`` to its integer index, or None if not a well-formed handle.

    Only ``src:`` followed by a non-negative decimal integer is a handle. A
    free-text ref (``vault:research-notes``) returns None — it is not citable.
    """
    if not isinstance(handle, str) or not handle.startswith(HANDLE_PREFIX):
        return None
    suffix = handle[len(HANDLE_PREFIX) :]
    if not suffix.isdigit():
        return None
    return int(suffix)


def build_resolved_source_set(
    topic: str, packets: Sequence[SourcePacket]
) -> ResolvedSourceSet | None:
    """Build a content-hash-bound, deduplicated, set-hashed ResolvedSourceSet.

    Returns None when there are no packets — a no-source run cannot construct a
    citable set, so the caller must REFUSE rather than fabricate to fill. Packets
    are deduplicated by ``content_hash`` (the content is the identity); first
    occurrence wins so handle indices stay stable with recruitment order.
    """
    seen: set[str] = set()
    unique: list[SourcePacket] = []
    for packet in packets:
        if packet.content_hash in seen:
            continue
        seen.add(packet.content_hash)
        unique.append(packet)
    if not unique:
        return None
    provisional = ResolvedSourceSet(topic=topic, packets=tuple(unique))
    return ResolvedSourceSet(
        topic=topic, packets=tuple(unique), set_hash=provisional.compute_set_hash()
    )


def validate_cited_handles(
    source_set: ResolvedSourceSet, cited_handles: Sequence[str]
) -> dict[str, Any]:
    """Dereference each cited handle against the resolved set (the LOAD-BEARING gate).

    This is membership, not shape: a handle is valid iff it resolves to a packet
    in ``source_set``. Empty citations are refused (a claim must cite). The
    returned ``resolved_content_hashes`` bind each accepted citation to real
    recruited content.
    """
    handles = list(cited_handles)
    unresolved = [h for h in handles if source_set.packet_for_handle(h) is None]
    resolved_content_hashes = [
        source_set.content_hash_for_handle(h)
        for h in handles
        if source_set.packet_for_handle(h) is not None
    ]
    return {
        "ok": bool(handles) and not unresolved,
        "unresolved": unresolved,
        "cited_count": len(handles),
        "resolved_content_hashes": resolved_content_hashes,
    }


def source_provenance_sha256(source_set: ResolvedSourceSet) -> str:
    """Hash of the RESOLVED source content hashes — real provenance, not model text.

    Order-independent (sorted) so it certifies *which content* grounded the
    segment, independent of recruitment order or the model's own prose.
    """
    payload = json.dumps(
        sorted(packet.content_hash for packet in source_set.packets),
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def validate_source_set(source_set: ResolvedSourceSet) -> dict[str, list[str]]:
    violations: list[str] = []

    if not source_set.packets:
        violations.append("source set has no packets — naked topic string rejected")

    seen_refs: set[str] = set()
    for packet in source_set.packets:
        if packet.source_ref in seen_refs:
            violations.append(f"duplicate source_ref: {packet.source_ref}")
        seen_refs.add(packet.source_ref)

        if not packet.source_consequence:
            violations.append(
                f"packet {packet.source_ref} has no source_consequence — "
                f"source must name what changes if absent"
            )

        if packet.freshness == "stale":
            violations.append(
                f"packet {packet.source_ref} is stale — recruit fresh source before planning"
            )

    return {"ok": not violations, "violations": violations}


def bind_source_hashes(source_set: ResolvedSourceSet) -> dict[str, str]:
    return {
        "source_set_hash": source_set.compute_set_hash(),
        **{f"source_packet_{i}_hash": p.content_hash for i, p in enumerate(source_set.packets)},
    }
