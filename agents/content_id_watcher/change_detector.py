"""Diff old vs new snapshots into ``ChangeEvent`` instances.

Each detected change carries the kind, the affected broadcast / video
id, before / after values, and the salience weight pulled from the
decision table in ``salience``. Cold-start (no prior snapshot) emits
nothing — the first poll just establishes baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.content_id_watcher.salience import (
    KIND_CONTENT_ID_MATCH,
    KIND_INGEST_UNBIND,
    KIND_KIDS_CLASSIFICATION_CHANGE,
    KIND_LIFECYCLE_COMPLETE,
    KIND_METADATA_YT_EDITED,
    KIND_MONETIZATION_DRIFT,
    KIND_PRIORITY_CHANGE,
    KIND_VISIBILITY_CHANGE,
    intent_family_for,
    is_high_salience,
    salience_for,
)


@dataclass(frozen=True)
class ChangeEvent:
    """One detected field change on a broadcast or video.

    ``broadcast_id`` is the YouTube live broadcast id (also the resulting
    VOD video id). ``payload`` carries the before/after values plus
    derived metadata (intent_family, salience, ntfy_eligible) so the
    emitter has everything it needs without re-deriving.
    """

    kind: str
    broadcast_id: str
    old_value: Any
    new_value: Any

    @property
    def salience(self) -> float:
        return salience_for(self.kind)

    @property
    def intent_family(self) -> str:
        return intent_family_for(self.kind)

    @property
    def ntfy_eligible(self) -> bool:
        return is_high_salience(self.kind)

    def narrative(self) -> str:
        """Human-readable summary used in the impingement payload + ntfy body."""
        return (
            f"{self.kind} on broadcast {self.broadcast_id}: {self.old_value!r} → {self.new_value!r}"
        )


def detect_changes(old: dict | None, new: dict, *, broadcast_id: str) -> list[ChangeEvent]:
    """Return the list of ChangeEvents between two snapshots.

    Cold-start (``old is None``) yields no events — the first poll
    establishes the baseline. Identical snapshots also yield no events.
    """
    if old is None:
        return []

    changes: list[ChangeEvent] = []

    def _diff(field_path: str, kind: str) -> None:
        a = _read(old, field_path)
        b = _read(new, field_path)
        if a != b:
            changes.append(
                ChangeEvent(kind=kind, broadcast_id=broadcast_id, old_value=a, new_value=b)
            )

    _diff("status.lifeCycleStatus", KIND_LIFECYCLE_COMPLETE)
    _diff("status.liveBroadcastPriority", KIND_PRIORITY_CHANGE)
    _diff("contentDetails.boundStreamId", KIND_INGEST_UNBIND)
    _diff("monetizationDetails.cuepointSchedule.strategy", KIND_MONETIZATION_DRIFT)
    _diff("snippet.title", KIND_METADATA_YT_EDITED)
    _diff("snippet.description", KIND_METADATA_YT_EDITED)
    _diff("status.rejectionReason", KIND_CONTENT_ID_MATCH)
    _diff("status.publicStatsViewable", KIND_VISIBILITY_CHANGE)
    _diff("status.madeForKids", KIND_KIDS_CLASSIFICATION_CHANGE)

    return _coalesce_metadata_edits(changes)


def _coalesce_metadata_edits(events: list[ChangeEvent]) -> list[ChangeEvent]:
    """Merge title-edit + description-edit into a single metadata event."""
    metadata = [e for e in events if e.kind == KIND_METADATA_YT_EDITED]
    if len(metadata) <= 1:
        return events
    others = [e for e in events if e.kind != KIND_METADATA_YT_EDITED]
    coalesced = ChangeEvent(
        kind=KIND_METADATA_YT_EDITED,
        broadcast_id=metadata[0].broadcast_id,
        old_value={"title": metadata[0].old_value, "description": metadata[1].old_value},
        new_value={"title": metadata[0].new_value, "description": metadata[1].new_value},
    )
    return [*others, coalesced]


def _read(snapshot: dict, path: str) -> Any:
    """Walk a dotted path through ``snapshot``. Missing leg → None."""
    cursor: Any = snapshot
    for part in path.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
        if cursor is None:
            return None
    return cursor
