"""Single daemon-owned coordination event log.

Coordination reform Phase 4a (CASE-SDLC-REFORM-001): the canonical
coordination ledger is one SQLite WAL database outside every worktree, with a
JSONL mirror for grepability. Lanes are event actors, not ledger writers; only
the daemon writes the canonical log. Daemon-down enforcement paths can write a
spool file for later daemon ingestion.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

DEFAULT_COORD_DIR = Path("/var/lib/hapax/coord")
DEFAULT_LEDGER_DB = DEFAULT_COORD_DIR / "ledger.db"
DEFAULT_JSONL_MIRROR = DEFAULT_COORD_DIR / "ledger.jsonl"
DEFAULT_SPOOL_DIR = DEFAULT_COORD_DIR / "spool"

#: Env var redirecting the canonical coord log for test isolation / sandboxed
#: tools. Production leaves it unset (the log lives outside every worktree).
COORD_DIR_ENV = "HAPAX_COORD_DIR"

_SCHEMA_VERSION = 1
_WRITER_KINDS = {"daemon", "shim", "lane"}


class CoordEventLogError(RuntimeError):
    """Base error for coordination event-log operations."""


class DirectLaneWriteError(CoordEventLogError):
    """Raised when a lane tries to write the daemon-owned canonical log."""


class DuplicateEventError(CoordEventLogError):
    """Raised when an event_id is already present in the canonical log."""


@dataclass(frozen=True)
class CoordWriter:
    """Identity of the process attempting a ledger operation."""

    name: str
    kind: Literal["daemon", "shim", "lane"]
    lane_id: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("coord writer name is required")
        if self.kind not in _WRITER_KINDS:
            raise ValueError(f"unsupported coord writer kind: {self.kind!r}")

    @classmethod
    def daemon(cls, name: str = "hapax-coord") -> CoordWriter:
        return cls(name=name, kind="daemon")

    @classmethod
    def shim(cls, name: str = "cc-task-gate", *, lane: str | None = None) -> CoordWriter:
        return cls(name=name, kind="shim", lane_id=lane)

    @classmethod
    def lane(cls, lane: str) -> CoordWriter:
        return cls(name=lane, kind="lane", lane_id=lane)

    def to_record(self) -> dict[str, str | None]:
        return {"name": self.name, "kind": self.kind, "lane": self.lane_id}


@dataclass(frozen=True)
class CoordEvent:
    """One typed coordination event.

    ``actor`` names the lane/tool/person the event is about. ``CoordWriter`` is
    separate and names the process writing the ledger.
    """

    event_id: str
    timestamp: str
    event_type: str
    actor: str
    subject: str
    authority_case: str | None = None
    parent_spec: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    sequence: int | None = None
    schema_version: int = _SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in ("event_id", "timestamp", "event_type", "actor", "subject"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        if self.sequence is not None and self.sequence < 1:
            raise ValueError("sequence must be a positive integer")
        payload = _json_round_trip(self.payload)
        if not isinstance(payload, dict):
            raise ValueError("coord event payload must be a JSON object")
        object.__setattr__(self, "payload", payload)

    def with_sequence(self, sequence: int) -> CoordEvent:
        return replace(self, sequence=sequence)

    def to_record(self, *, sequence: int | None = None) -> dict[str, Any]:
        seq = self.sequence if sequence is None else sequence
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "actor": self.actor,
            "subject": self.subject,
            "authority_case": self.authority_case,
            "parent_spec": self.parent_spec,
            "payload": dict(self.payload),
        }
        if seq is not None:
            record["sequence"] = seq
        return record

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> CoordEvent:
        payload = record.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ValueError("coord event record payload must be an object")
        sequence = record.get("sequence")
        return cls(
            event_id=str(record["event_id"]),
            timestamp=str(record["timestamp"]),
            event_type=str(record["event_type"]),
            actor=str(record["actor"]),
            subject=str(record["subject"]),
            authority_case=_optional_str(record.get("authority_case")),
            parent_spec=_optional_str(record.get("parent_spec")),
            payload=payload,
            sequence=int(sequence) if sequence is not None else None,
            schema_version=int(record.get("schema_version", _SCHEMA_VERSION)),
        )


@dataclass(frozen=True)
class AppendReceipt:
    """Result of a canonical append or fail-open spool write."""

    event_id: str
    appended: bool
    spooled: bool
    sequence: int | None
    db_path: Path
    jsonl_path: Path
    spool_path: Path | None = None
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplayResult:
    """Replay output with degradation metadata."""

    events: tuple[CoordEvent, ...]
    source: Literal["sqlite", "jsonl_mirror"]
    degraded: bool = False
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpoolIngestResult:
    """Result of draining fail-open spool intents into the canonical log."""

    ingested: int
    duplicates: int
    failed: int
    removed: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class BootReconcileResult:
    """Result of the daemon boot path: replay + spool ingestion."""

    replayed: int
    spool_ingested: int
    spool_duplicates: int
    spool_failed: int
    degraded: bool = False
    replay_source: Literal["sqlite", "jsonl_mirror"] = "sqlite"
    errors: tuple[str, ...] = ()

    def to_record(self) -> dict[str, Any]:
        return {
            "replayed": self.replayed,
            "degraded": self.degraded,
            "replay_source": self.replay_source,
            "spool_ingested": self.spool_ingested,
            "spool_duplicates": self.spool_duplicates,
            "spool_failed": self.spool_failed,
            "errors": list(self.errors),
        }


class CoordEventLog:
    """SQLite + JSONL coordination event log."""

    def __init__(
        self,
        *,
        db_path: Path | str = DEFAULT_LEDGER_DB,
        jsonl_path: Path | str = DEFAULT_JSONL_MIRROR,
        spool_dir: Path | str = DEFAULT_SPOOL_DIR,
    ) -> None:
        self.db_path = Path(db_path)
        self.jsonl_path = Path(jsonl_path)
        self.spool_dir = Path(spool_dir)

    def append(
        self,
        event: CoordEvent,
        *,
        writer: CoordWriter,
        fail_open: bool = False,
    ) -> AppendReceipt:
        """Append ``event`` to the daemon-owned canonical log.

        Direct lane writes are refused before any filesystem mutation. If the
        canonical append fails and ``fail_open`` is true, the event is written to
        a spool JSONL file for daemon ingestion and the receipt records the
        degraded write.
        """

        if writer.kind != "daemon":
            raise DirectLaneWriteError(
                f"{writer.kind} writer {writer.name!r} cannot append the canonical coord log"
            )

        try:
            sequence = self._append_sqlite(event)
        except DuplicateEventError:
            raise
        except Exception as exc:
            if not fail_open:
                raise CoordEventLogError(f"canonical coord append failed: {exc}") from exc
            reason = f"canonical_append_failed:{type(exc).__name__}:{exc}"
            spool_path = self._write_spool(event, writer=writer, reason=reason)
            return AppendReceipt(
                event_id=event.event_id,
                appended=False,
                spooled=True,
                sequence=None,
                db_path=self.db_path,
                jsonl_path=self.jsonl_path,
                spool_path=spool_path,
                errors=(reason,),
            )

        sequenced = event.with_sequence(sequence)
        mirror_errors = self._append_jsonl_mirror(sequenced)
        return AppendReceipt(
            event_id=event.event_id,
            appended=True,
            spooled=False,
            sequence=sequence,
            db_path=self.db_path,
            jsonl_path=self.jsonl_path,
            errors=mirror_errors,
        )

    def spool_fail_open(
        self,
        event: CoordEvent,
        *,
        writer: CoordWriter,
        reason: str,
    ) -> AppendReceipt:
        """Write a daemon-down fail-open event to the spool.

        The shim may write spool files; lanes still may not write any ledger
        surface directly.
        """

        if writer.kind == "lane":
            raise DirectLaneWriteError(
                f"lane writer {writer.name!r} cannot write coord spool directly"
            )
        spool_path = self._write_spool(event, writer=writer, reason=reason)
        return AppendReceipt(
            event_id=event.event_id,
            appended=False,
            spooled=True,
            sequence=None,
            db_path=self.db_path,
            jsonl_path=self.jsonl_path,
            spool_path=spool_path,
        )

    def replay(self, *, fail_open: bool = False) -> ReplayResult:
        """Replay the canonical log.

        When SQLite is corrupt or unavailable, ``fail_open=True`` falls back to
        the JSONL mirror and skips malformed mirror lines.
        """

        try:
            return ReplayResult(events=tuple(self._replay_sqlite()), source="sqlite")
        except Exception as exc:
            if not fail_open:
                raise CoordEventLogError(f"coord replay failed: {exc}") from exc
            events, mirror_errors = self._replay_jsonl_mirror()
            error = f"sqlite_replay_failed:{type(exc).__name__}:{exc}"
            return ReplayResult(
                events=tuple(events),
                source="jsonl_mirror",
                degraded=True,
                errors=(error, *mirror_errors),
            )

    def ingest_spool(self) -> SpoolIngestResult:
        """Drain fail-open spool intents into the canonical log (daemon boot path).

        Each spool file holds one intent written by a shim while the daemon was
        down. The daemon (the single writer) appends each to the canonical log
        and removes the consumed file. A duplicate (event already canonical) is
        idempotent success — the file is still removed. A file that fails to parse
        or append is LEFT in place and recorded, so a transient fault never loses
        a spooled authorization (master design §4.3).
        """

        if not self.spool_dir.is_dir():
            return SpoolIngestResult(ingested=0, duplicates=0, failed=0)

        ingested = 0
        duplicates = 0
        failed = 0
        removed: list[str] = []
        errors: list[str] = []
        for spool_path in sorted(self.spool_dir.glob("*.jsonl")):
            try:
                event = self._read_spool_event(spool_path)
            except Exception as exc:
                failed += 1
                errors.append(f"{spool_path.name}: parse_failed:{type(exc).__name__}:{exc}")
                continue

            consumed = False
            try:
                self.append(event, writer=CoordWriter.daemon())
                ingested += 1
                consumed = True
            except DuplicateEventError:
                duplicates += 1
                consumed = True
            except Exception as exc:
                failed += 1
                errors.append(f"{spool_path.name}: append_failed:{type(exc).__name__}:{exc}")

            if consumed:
                try:
                    spool_path.unlink()
                    removed.append(spool_path.name)
                except OSError as exc:
                    errors.append(f"{spool_path.name}: unlink_failed:{type(exc).__name__}:{exc}")

        return SpoolIngestResult(
            ingested=ingested,
            duplicates=duplicates,
            failed=failed,
            removed=tuple(removed),
            errors=tuple(errors),
        )

    def boot_reconcile(self, *, fail_open: bool = True) -> BootReconcileResult:
        """Replay the canonical log then ingest fail-open spool intents.

        Realizes "the heap is DERIVED" (master design §2.2/NEW-5): on boot the
        daemon rebuilds in-memory state from the canonical log and folds in any
        intents spooled while it was down, so no authorization survives only in a
        process image.
        """

        replay = self.replay(fail_open=fail_open)
        ingest = self.ingest_spool()
        return BootReconcileResult(
            replayed=len(replay.events),
            spool_ingested=ingest.ingested,
            spool_duplicates=ingest.duplicates,
            spool_failed=ingest.failed,
            degraded=replay.degraded,
            replay_source=replay.source,
            errors=(*replay.errors, *ingest.errors),
        )

    def _read_spool_event(self, spool_path: Path) -> CoordEvent:
        line = spool_path.read_text(encoding="utf-8").splitlines()[0]
        record = json.loads(line)
        return CoordEvent.from_record(record["event"])

    def _append_sqlite(self, event: CoordEvent) -> int:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        payload_json = _canonical_json(event.payload)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            _ensure_schema(conn)
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO coord_events (
                        event_id,
                        timestamp,
                        event_type,
                        actor,
                        subject,
                        authority_case,
                        parent_spec,
                        payload_json,
                        canonical_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.timestamp,
                        event.event_type,
                        event.actor,
                        event.subject,
                        event.authority_case,
                        event.parent_spec,
                        payload_json,
                        _canonical_json(event.to_record()),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateEventError(f"coord event already exists: {event.event_id}") from exc
            sequence = int(cursor.lastrowid)
            conn.execute(
                "UPDATE coord_events SET canonical_json = ? WHERE sequence = ?",
                (_canonical_json(event.to_record(sequence=sequence)), sequence),
            )
            conn.commit()
            return sequence

    def _append_jsonl_mirror(self, event: CoordEvent) -> tuple[str, ...]:
        try:
            self.jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            with self.jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical_json(event.to_record()) + "\n")
        except OSError as exc:
            return (f"jsonl_mirror_failed:{type(exc).__name__}:{exc}",)
        return ()

    def _replay_sqlite(self) -> list[CoordEvent]:
        if not self.db_path.exists():
            return []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT sequence, canonical_json FROM coord_events ORDER BY sequence"
            ).fetchall()
        events: list[CoordEvent] = []
        for sequence, canonical_json in rows:
            record = json.loads(str(canonical_json))
            record.setdefault("sequence", sequence)
            events.append(CoordEvent.from_record(record))
        return events

    def _replay_jsonl_mirror(self) -> tuple[list[CoordEvent], tuple[str, ...]]:
        events: list[CoordEvent] = []
        errors: list[str] = []
        try:
            lines = self.jsonl_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            return events, (f"jsonl_mirror_unavailable:{type(exc).__name__}:{exc}",)

        for lineno, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                events.append(CoordEvent.from_record(record))
            except Exception as exc:
                errors.append(f"{self.jsonl_path}: line {lineno}: {type(exc).__name__}: {exc}")
        return events, tuple(errors)

    def _write_spool(self, event: CoordEvent, *, writer: CoordWriter, reason: str) -> Path:
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        # A uuid4 nonce keeps two intents with an identical timestamp+event_id from
        # clobbering each other on disk: each spooled fail-open intent must survive
        # until the daemon ingests it on boot, so a lost file is a lost authorization
        # (coordination reform Phase 4 §4.3 — the spool is the daemon-down write path).
        nonce = uuid.uuid4().hex[:8]
        path = (
            self.spool_dir
            / f"{_safe_filename(_now_iso())}-{_safe_filename(event.event_id)}-{nonce}.jsonl"
        )
        record = {
            "schema_version": _SCHEMA_VERSION,
            "spooled_at": _now_iso(),
            "writer": writer.to_record(),
            "reason": reason,
            "event": event.to_record(),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(record) + "\n")
        return path


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS coord_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            subject TEXT NOT NULL,
            authority_case TEXT,
            parent_spec TEXT,
            payload_json TEXT NOT NULL,
            canonical_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coord_events_subject_sequence "
        "ON coord_events(subject, sequence)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_coord_events_type_sequence "
        "ON coord_events(event_type, sequence)"
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _json_round_trip(value: object) -> object:
    return json.loads(_canonical_json(value))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "coord-event"


def default_event_log() -> CoordEventLog:
    """Return the canonical coord log, honoring ``HAPAX_COORD_DIR`` for isolation.

    Production uses ``/var/lib/hapax/coord`` (one log outside every worktree,
    NEW-4). Tests and sandboxed CLIs set ``HAPAX_COORD_DIR`` to redirect the
    SQLite DB, JSONL mirror, and spool under a temporary directory so a tool that
    emits a coordination event never writes the production log during a test.
    """

    base = Path(os.environ.get(COORD_DIR_ENV, str(DEFAULT_COORD_DIR)))
    return CoordEventLog(
        db_path=base / "ledger.db",
        jsonl_path=base / "ledger.jsonl",
        spool_dir=base / "spool",
    )


__all__ = [
    "AppendReceipt",
    "BootReconcileResult",
    "COORD_DIR_ENV",
    "CoordEvent",
    "CoordEventLog",
    "CoordEventLogError",
    "CoordWriter",
    "DEFAULT_COORD_DIR",
    "DEFAULT_JSONL_MIRROR",
    "DEFAULT_LEDGER_DB",
    "DEFAULT_SPOOL_DIR",
    "DirectLaneWriteError",
    "DuplicateEventError",
    "ReplayResult",
    "SpoolIngestResult",
    "default_event_log",
]

# Public API consumed by the coordination daemon/shim through dynamic dispatch.
_DYNAMIC_ENTRYPOINTS = (
    CoordWriter.daemon,
    CoordWriter.shim,
    CoordEventLog.replay,
    CoordEventLog.spool_fail_open,
    CoordEventLog.ingest_spool,
    CoordEventLog.boot_reconcile,
)
