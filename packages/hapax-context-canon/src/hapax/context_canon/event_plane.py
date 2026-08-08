"""Canonical, non-authorizing coordination event-plane support carriers.

This module owns wire values only.  It deliberately has no dependency on the
coordination event-log implementation, projection consumers, SQLite, or the
filesystem.  Producers supply already-owned exact event records.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
    model_validator,
)

from .contract import (
    _HASH_PATTERN,
    _JSON_SAFE_INTEGER_MAX,
    FrozenModel,
    _domain_hash,
    _validate_wire_string,
)

COORD_REPLAY_SNAPSHOT_SCHEMA = "hapax.coord-replay-snapshot.v1"
COORD_EVENT_VECTOR_DOMAIN = "hapax.coord-event-vector.v1"
COORD_EVENT_FRONTIER_DOMAIN = "hapax.coord-event-frontier.v1"

CoordReplaySource = Literal["sqlite", "jsonl_mirror"]


def _normalized_ledger_path(value: str | os.PathLike[str]) -> str:
    """Return one deterministic lexical absolute path without touching it."""

    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or raw != raw.strip() or "\x00" in raw:
        raise ValueError("ledger_path must be one nonblank path without edge whitespace")
    if not os.path.isabs(raw):
        raise ValueError("ledger_path must be absolute before snapshot construction")
    return os.path.normpath(raw)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(child) for child in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(child) for child in value]
    return value


class CoordEventRecord(FrozenModel):
    """Strict canonical wire image of one committed coordination event."""

    schema_version: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    event_id: str = Field(strict=True)
    timestamp: str = Field(strict=True)
    event_type: str = Field(strict=True)
    actor: str = Field(strict=True)
    subject: str = Field(strict=True)
    authority_case: str | None = Field(default=None, strict=True)
    parent_spec: str | None = Field(default=None, strict=True)
    payload: Mapping[str, JsonValue]
    sequence: int = Field(ge=1, le=_JSON_SAFE_INTEGER_MAX, strict=True)

    @field_validator(
        "event_id",
        "timestamp",
        "event_type",
        "actor",
        "subject",
        "authority_case",
        "parent_spec",
    )
    @classmethod
    def validate_strings(cls, value: str | None) -> str | None:
        return None if value is None else _validate_wire_string(value)

    @field_validator("payload", mode="after")
    @classmethod
    def freeze_payload(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        return MappingProxyType({key: _freeze_json(child) for key, child in value.items()})

    @field_serializer("payload")
    def serialize_payload(self, value: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
        thawed = _thaw_json(value)
        if not isinstance(thawed, dict):  # pragma: no cover - invariant defense
            raise ValueError("coord event payload must remain a JSON object")
        return thawed

    @model_validator(mode="after")
    def validate_canonical_json(self) -> Self:
        # The package canonical encoder rejects non-JSON values, non-string
        # object keys, non-finite numbers, and integers outside the safe range.
        from .contract import canonical_json_bytes

        canonical_json_bytes(self.model_dump(mode="json"))
        return self


class CoordReplaySnapshot(FrozenModel):
    """Content-addressed event frontier supplied by its owning reader.

    The carrier is support evidence only.  It cannot authorize an action and it
    performs no read to construct or validate itself.
    """

    model_config = ConfigDict(serialize_by_alias=True)

    schema_id: Literal["hapax.coord-replay-snapshot.v1"] = Field(alias="schema")
    ledger_path: str = Field(strict=True)
    source: CoordReplaySource
    degraded: bool = Field(strict=True)
    errors: tuple[str, ...]
    since_sequence: int = Field(ge=0, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    through_sequence: int = Field(ge=0, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    sequence_frontier: tuple[int, ...]
    events: tuple[CoordEventRecord, ...]
    event_count: int = Field(ge=0, le=_JSON_SAFE_INTEGER_MAX, strict=True)
    event_vector_ref: str = Field(strict=True)
    event_vector_hash: str = Field(pattern=_HASH_PATTERN, strict=True)
    frontier_ref: str = Field(strict=True)
    frontier_hash: str = Field(pattern=_HASH_PATTERN, strict=True)
    no_effect: Literal[True]
    may_authorize: Literal[False]
    snapshot_ref: str = Field(strict=True)
    snapshot_hash: str = Field(pattern=_HASH_PATTERN, strict=True)

    @property
    def coverage_complete(self) -> bool:
        """Whether this value has the intrinsic shape of a clean full replay.

        Sequence gaps do not imply loss: SQLite ``AUTOINCREMENT`` can advance
        across failed writes.  A clean full replay therefore needs only the
        zero query floor and either an empty vector or a first committed row at
        sequence one.  This structural predicate does not prove that the caller
        owned the ledger, that the replay is current, or that any action is
        authorized.  Operational consumers must bind an owner-produced capture
        at their effect edge.
        """

        return (
            self.source == "sqlite"
            and not self.degraded
            and not self.errors
            and self.since_sequence == 0
            and (not self.sequence_frontier or self.sequence_frontier[0] == 1)
        )

    def frontier_body(self) -> dict[str, Any]:
        return {
            "event_count": self.event_count,
            "event_vector_hash": self.event_vector_hash,
            "event_vector_ref": self.event_vector_ref,
            "ledger_path": self.ledger_path,
            "sequence_frontier": list(self.sequence_frontier),
            "since_sequence": self.since_sequence,
            "through_sequence": self.through_sequence,
        }

    def body(self) -> dict[str, Any]:
        return {
            "degraded": self.degraded,
            "errors": list(self.errors),
            "event_count": self.event_count,
            "event_vector_hash": self.event_vector_hash,
            "event_vector_ref": self.event_vector_ref,
            "events": [event.model_dump(mode="json") for event in self.events],
            "frontier_hash": self.frontier_hash,
            "frontier_ref": self.frontier_ref,
            "ledger_path": self.ledger_path,
            "may_authorize": self.may_authorize,
            "no_effect": self.no_effect,
            "schema": self.schema_id,
            "sequence_frontier": list(self.sequence_frontier),
            "since_sequence": self.since_sequence,
            "source": self.source,
            "through_sequence": self.through_sequence,
        }

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if self.ledger_path != _normalized_ledger_path(self.ledger_path):
            raise ValueError("ledger_path must be normalized and absolute")
        if any(not error or error != error.strip() for error in self.errors):
            raise ValueError("replay errors must be nonblank without edge whitespace")
        sequences = tuple(event.sequence for event in self.events)
        if (
            self.event_count != len(self.events)
            or self.sequence_frontier != sequences
            or any(sequence <= self.since_sequence for sequence in sequences)
            or tuple(sorted(sequences)) != sequences
            or len(set(sequences)) != len(sequences)
            or len({event.event_id for event in self.events}) != len(self.events)
            or self.through_sequence != (self.since_sequence if not sequences else sequences[-1])
        ):
            raise ValueError("coord replay event frontier is invalid")

        event_records = [event.model_dump(mode="json") for event in self.events]
        event_vector_hash = _domain_hash(COORD_EVENT_VECTOR_DOMAIN, event_records)
        if (
            self.event_vector_hash != event_vector_hash
            or self.event_vector_ref != f"coord-event-vector@sha256:{event_vector_hash}"
        ):
            raise ValueError("coord replay event vector identity mismatch")
        frontier_hash = _domain_hash(COORD_EVENT_FRONTIER_DOMAIN, self.frontier_body())
        if (
            self.frontier_hash != frontier_hash
            or self.frontier_ref != f"coord-event-frontier@sha256:{frontier_hash}"
        ):
            raise ValueError("coord replay frontier identity mismatch")
        snapshot_hash = _domain_hash(COORD_REPLAY_SNAPSHOT_SCHEMA, self.body())
        if (
            self.snapshot_hash != snapshot_hash
            or self.snapshot_ref != f"coord-replay-snapshot@sha256:{snapshot_hash}"
        ):
            raise ValueError("coord replay snapshot identity mismatch")
        return self


def build_coord_replay_snapshot(
    event_records: Sequence[Mapping[str, Any]],
    *,
    ledger_path: str | os.PathLike[str],
    source: CoordReplaySource,
    degraded: bool,
    errors: Sequence[str] = (),
    since_sequence: int = 0,
) -> CoordReplaySnapshot:
    """Build one snapshot from caller-owned exact canonical event mappings."""

    if isinstance(event_records, str | bytes | bytearray):
        raise ValueError("event_records must be a sequence of mappings")
    if type(degraded) is not bool:
        raise ValueError("degraded must be boolean")
    if type(since_sequence) is not int:
        raise ValueError("since_sequence must be an integer")
    if source not in {"sqlite", "jsonl_mirror"}:
        raise ValueError("source must name one supported replay backend")
    if isinstance(errors, str | bytes | bytearray):
        raise ValueError("errors must be a sequence of complete error strings")
    checked_errors = tuple(errors)
    if any(not isinstance(error, str) for error in checked_errors):
        raise ValueError("errors must be strings")

    exact_event_keys = set(CoordEventRecord.model_fields)
    checked_events: list[CoordEventRecord] = []
    for record in event_records:
        if not isinstance(record, Mapping) or set(record) != exact_event_keys:
            raise ValueError("each event record must carry the exact canonical key set")
        event = CoordEventRecord.model_validate(record)
        if event.model_dump(mode="json") != dict(record):
            raise ValueError("event record must already be in canonical wire form")
        checked_events.append(event)
    events = tuple(checked_events)
    sequences = tuple(event.sequence for event in events)
    through_sequence = since_sequence if not sequences else sequences[-1]
    ledger = _normalized_ledger_path(ledger_path)

    event_records_wire = [event.model_dump(mode="json") for event in events]
    event_vector_hash = _domain_hash(COORD_EVENT_VECTOR_DOMAIN, event_records_wire)
    event_vector_ref = f"coord-event-vector@sha256:{event_vector_hash}"
    frontier_body = {
        "event_count": len(events),
        "event_vector_hash": event_vector_hash,
        "event_vector_ref": event_vector_ref,
        "ledger_path": ledger,
        "sequence_frontier": list(sequences),
        "since_sequence": since_sequence,
        "through_sequence": through_sequence,
    }
    frontier_hash = _domain_hash(COORD_EVENT_FRONTIER_DOMAIN, frontier_body)
    frontier_ref = f"coord-event-frontier@sha256:{frontier_hash}"
    body = {
        "degraded": degraded,
        "errors": list(checked_errors),
        "event_count": len(events),
        "event_vector_hash": event_vector_hash,
        "event_vector_ref": event_vector_ref,
        "events": event_records_wire,
        "frontier_hash": frontier_hash,
        "frontier_ref": frontier_ref,
        "ledger_path": ledger,
        "may_authorize": False,
        "no_effect": True,
        "schema": COORD_REPLAY_SNAPSHOT_SCHEMA,
        "sequence_frontier": list(sequences),
        "since_sequence": since_sequence,
        "source": source,
        "through_sequence": through_sequence,
    }
    snapshot_hash = _domain_hash(COORD_REPLAY_SNAPSHOT_SCHEMA, body)
    return CoordReplaySnapshot(
        schema=COORD_REPLAY_SNAPSHOT_SCHEMA,
        ledger_path=ledger,
        source=source,
        degraded=degraded,
        errors=checked_errors,
        since_sequence=since_sequence,
        through_sequence=through_sequence,
        sequence_frontier=sequences,
        events=events,
        event_count=len(events),
        event_vector_ref=event_vector_ref,
        event_vector_hash=event_vector_hash,
        frontier_ref=frontier_ref,
        frontier_hash=frontier_hash,
        no_effect=True,
        may_authorize=False,
        snapshot_ref=f"coord-replay-snapshot@sha256:{snapshot_hash}",
        snapshot_hash=snapshot_hash,
    )


__all__ = (
    "COORD_EVENT_FRONTIER_DOMAIN",
    "COORD_EVENT_VECTOR_DOMAIN",
    "COORD_REPLAY_SNAPSHOT_SCHEMA",
    "CoordEventRecord",
    "CoordReplaySnapshot",
    "CoordReplaySource",
    "build_coord_replay_snapshot",
)
