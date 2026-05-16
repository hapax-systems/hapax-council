"""Resolved source packets for segment prep planning.

The planner receives resolved source packets — not naked topic strings.
Each packet binds a source reference to its content hash, freshness,
rights status, and source consequence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


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
