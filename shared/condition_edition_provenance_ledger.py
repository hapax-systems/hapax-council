"""Condition edition provenance ledger v2.

Ties condition-bound stills, loops, visual editions, and aesthetic
artifacts to timestamped runtime truth: source condition, rights class,
frame refs, public-event refs, and replay/manifest evidence.

Downstream consumers: marketplace publisher, demo kit, artifact catalog.
The ledger preserves aesthetic value without implying truth, safety,
or monetization authority — those gates are downstream concerns.

CC-task: condition-edition-provenance-ledger-v2
Authority: CASE-RUNTIME-TRUTH-20260429
"""

from __future__ import annotations

import logging
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

log = logging.getLogger(__name__)


class ReleaseState(StrEnum):
    BLOCKED = "blocked"
    PRIVATE_ONLY = "private_only"
    DRAFT = "draft"
    RELEASED = "released"
    LICENSED = "licensed"
    WITHDRAWN = "withdrawn"


class ProvenanceBlocker(StrEnum):
    RAW_PRIVATE_FRAME = "raw_private_frame"
    THIRD_PARTY_MEDIA = "third_party_media"
    ALBUM_COVER_UNCERTAINTY = "album_cover_uncertainty"
    MISSING_PUBLIC_EVENT_PROOF = "missing_public_event_proof"
    MISSING_RIGHTS_CLASS = "missing_rights_class"
    MISSING_FRAME_REF = "missing_frame_ref"
    MISSING_ARCHIVE_REF = "missing_archive_ref"
    MISSING_CONDITION_ID = "missing_condition_id"
    MISSING_TIMESTAMP = "missing_timestamp"


BLOCKED_RIGHTS = frozenset(
    {"uncleared", "third_party_rights_risky", "album_cover_no_explicit_rights"}
)
BLOCKED_PRIVACY = frozenset({"raw_private_frame", "unanonymized_private"})


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProvenanceRecord(_Model):
    """One edition's provenance binding to runtime truth."""

    edition_id: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)
    timestamp: datetime
    surface_lane: str = Field(min_length=1)
    frame_ref: str = Field(min_length=1)
    archive_ref: str = Field(min_length=1)
    public_event_ref: str | None = None
    replay_manifest_ref: str | None = None
    rights_class: str = Field(min_length=1)
    privacy_class: str = Field(min_length=1)
    release_state: ReleaseState
    provenance_token: str = Field(min_length=1)
    source_condition_description: str = ""
    blockers: tuple[ProvenanceBlocker, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_fail_closed(self) -> Self:
        computed = evaluate_blockers(self)
        if computed and self.release_state in (
            ReleaseState.RELEASED,
            ReleaseState.LICENSED,
        ):
            msg = (
                f"edition {self.edition_id!r} has release_state={self.release_state.value} "
                f"but blockers remain: {', '.join(b.value for b in computed)}"
            )
            raise ValueError(msg)
        return self


def evaluate_blockers(record: ProvenanceRecord) -> tuple[ProvenanceBlocker, ...]:
    blockers: list[ProvenanceBlocker] = []
    if record.rights_class in BLOCKED_RIGHTS:
        blockers.append(ProvenanceBlocker.THIRD_PARTY_MEDIA)
    if record.privacy_class in BLOCKED_PRIVACY:
        blockers.append(ProvenanceBlocker.RAW_PRIVATE_FRAME)
    if record.rights_class == "album_cover_no_explicit_rights":
        blockers.append(ProvenanceBlocker.ALBUM_COVER_UNCERTAINTY)
    if not record.public_event_ref:
        blockers.append(ProvenanceBlocker.MISSING_PUBLIC_EVENT_PROOF)
    return tuple(blockers)


class ProvenanceLedger(_Model):
    """V2 ledger: all edition provenance records."""

    schema_version: Literal[2] = 2
    generated_at: datetime
    records: tuple[ProvenanceRecord, ...] = Field(default_factory=tuple)

    def by_release_state(self, state: ReleaseState) -> tuple[ProvenanceRecord, ...]:
        return tuple(r for r in self.records if r.release_state is state)

    def releasable(self) -> tuple[ProvenanceRecord, ...]:
        return tuple(
            r
            for r in self.records
            if r.release_state in (ReleaseState.RELEASED, ReleaseState.LICENSED)
        )

    def blocked(self) -> tuple[ProvenanceRecord, ...]:
        return tuple(r for r in self.records if r.release_state is ReleaseState.BLOCKED)

    def for_marketplace(self) -> tuple[ProvenanceRecord, ...]:
        return tuple(
            r
            for r in self.records
            if r.release_state in (ReleaseState.RELEASED, ReleaseState.LICENSED)
            and r.public_event_ref is not None
        )

    def for_demo_kit(self) -> tuple[ProvenanceRecord, ...]:
        return tuple(
            r
            for r in self.records
            if r.release_state != ReleaseState.BLOCKED and r.release_state != ReleaseState.WITHDRAWN
        )
