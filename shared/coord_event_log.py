"""Single daemon-owned coordination event log.

Coordination reform Phase 4a (CASE-SDLC-REFORM-001): the canonical
coordination ledger is one SQLite WAL database outside every worktree, with a
JSONL mirror for grepability. Lanes are event actors, not ledger writers; only
the daemon writes the canonical log. Daemon-down enforcement paths can write a
spool file for later daemon ingestion.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from shared.jsonl_append import append_jsonl

#: Env var redirecting the canonical coord tree for test isolation / sandboxed
#: tools. Production leaves it unset; the default is a user-writable cache path.
COORD_DIR_ENV = "HAPAX_COORD_DIR"
#: Explicit per-surface overrides, honored ahead of ``HAPAX_COORD_DIR``.
GRANT_DIR_ENV = "HAPAX_COORD_GRANT_DIR"
GRANT_KEY_ENV = "HAPAX_COORD_GRANT_KEY"


def _xdg_cache_home() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    return Path(xdg) if xdg else Path.home() / ".cache"


def coord_base_dir() -> Path:
    """Resolve the canonical coordination tree base directory.

    Precedence: ``HAPAX_COORD_DIR`` (test/sandbox isolation) →
    ``$XDG_CACHE_HOME/hapax/coord`` → ``~/.cache/hapax/coord``.

    The default is a **user-writable cache path**, not the former root-owned
    ``/var/lib/hapax/coord``: uid 1000 cannot ``mkdir`` into ``/var/lib/hapax``,
    so that default left the R2 event log unmaterialized and the R3 escape grant
    inert (reform-improve coord SSOT provisioning). ``~/.cache`` is still one
    fixed location outside every git worktree (master design NEW-4), so the
    single-writer / no-merge-conflict invariant holds.
    """
    override = os.environ.get(COORD_DIR_ENV, "").strip()
    if override:
        return Path(override)
    return _xdg_cache_home() / "hapax" / "coord"


def default_grant_dir() -> Path:
    """Escape-grant directory: ``HAPAX_COORD_GRANT_DIR`` else ``<base>/grants``."""
    explicit = os.environ.get(GRANT_DIR_ENV, "").strip()
    return Path(explicit) if explicit else coord_base_dir() / "grants"


def default_grant_key() -> Path:
    """Escape signing key: ``HAPAX_COORD_GRANT_KEY`` else ``<base>/grant-key``."""
    explicit = os.environ.get(GRANT_KEY_ENV, "").strip()
    return Path(explicit) if explicit else coord_base_dir() / "grant-key"


#: Import-time snapshot of the canonical tree with no override set. Call
#: ``coord_base_dir`` / ``default_*`` for env-dynamic resolution.
DEFAULT_COORD_DIR = coord_base_dir()
DEFAULT_LEDGER_DB = DEFAULT_COORD_DIR / "ledger.db"
DEFAULT_JSONL_MIRROR = DEFAULT_COORD_DIR / "ledger.jsonl"
DEFAULT_SPOOL_DIR = DEFAULT_COORD_DIR / "spool"

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
        # Single-writer-safe append (flock + O_APPEND) reproducing the canonical
        # bytes exactly; ``raising=True`` preserves the rich OSError diagnostic the
        # SSOT consumer surfaces (dn-ledger-flock).
        try:
            append_jsonl(
                self.jsonl_path, event.to_record(), serialize=_canonical_json, raising=True
            )
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
        # Single-writer-safe append reproducing the canonical bytes; ``raising=True``
        # keeps the existing raise-on-failure contract (a lost spool file is a lost
        # authorization, so the caller must see an IO failure).
        append_jsonl(path, record, serialize=_canonical_json, raising=True)
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

    Production uses the user-writable ``~/.cache/hapax/coord`` tree (one log
    outside every worktree, NEW-4 — see ``coord_base_dir``). Tests and sandboxed
    CLIs set ``HAPAX_COORD_DIR`` to redirect the SQLite DB, JSONL mirror, and
    spool under a temporary directory so a tool that emits a coordination event
    never writes the production log during a test.
    """

    base = coord_base_dir()
    return CoordEventLog(
        db_path=base / "ledger.db",
        jsonl_path=base / "ledger.jsonl",
        spool_dir=base / "spool",
    )


@dataclass(frozen=True)
class ProvisionResult:
    """Outcome of provisioning the coord SSOT tree + escape-grant signing key."""

    base_dir: Path
    spool_dir: Path
    grant_dir: Path
    grant_key: Path
    created: tuple[str, ...]
    key_created: bool

    def to_record(self) -> dict[str, Any]:
        return {
            "base_dir": str(self.base_dir),
            "spool_dir": str(self.spool_dir),
            "grant_dir": str(self.grant_dir),
            "grant_key": str(self.grant_key),
            "created": list(self.created),
            "key_created": self.key_created,
        }


def provision_coord_tree(
    *,
    base_dir: Path | str | None = None,
    grant_dir: Path | str | None = None,
    grant_key: Path | str | None = None,
) -> ProvisionResult:
    """Materialize the coord SSOT tree + escape signing key so R2/R3 are live.

    Idempotently creates ``{base, base/spool, grant_dir}`` and the 0600 escape
    signing key, then proves the base is writable with a probe file. This is the
    daemon-independent provisioner (master design §4.3/§4.4): a boot oneshot — or
    the operator by hand — runs it with no kernel present, so the R2 event log can
    materialize and the R3 escape grant is no longer inert.

    Raises ``CoordEventLogError`` **loudly** (never a silent swallow — the SSOT
    provisioning acceptance criterion) when the tree cannot be created or the base
    is not writable, e.g. the legacy root-owned ``/var/lib/hapax/coord`` default
    that uid 1000 could never provision.
    """
    from shared.governance.coord_capabilities import load_or_create_key

    base = Path(base_dir) if base_dir is not None else coord_base_dir()
    gdir = Path(grant_dir) if grant_dir is not None else default_grant_dir()
    gkey = Path(grant_key) if grant_key is not None else default_grant_key()
    spool = base / "spool"

    created: list[str] = []
    for directory in (base, spool, gdir):
        existed = directory.is_dir()
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CoordEventLogError(
                f"coord SSOT provisioning failed: cannot create {directory}: "
                f"{type(exc).__name__}: {exc} "
                f"(base {base} must be writable by uid {os.getuid()})"
            ) from exc
        if not existed:
            created.append(str(directory))

    probe = base / ".provision-probe"
    try:
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise CoordEventLogError(
            f"coord SSOT base {base} exists but is not writable: {type(exc).__name__}: {exc}"
        ) from exc

    key_existed = gkey.exists()
    try:
        load_or_create_key(gkey)
    except OSError as exc:
        raise CoordEventLogError(
            f"coord escape-grant key {gkey} could not be provisioned: {type(exc).__name__}: {exc}"
        ) from exc

    return ProvisionResult(
        base_dir=base,
        spool_dir=spool,
        grant_dir=gdir,
        grant_key=gkey,
        created=tuple(created),
        key_created=not key_existed,
    )


# --- daemon-writer CLI -------------------------------------------------------
# The single canonical writer exposed as a subprocess entrypoint so the SBCL
# coordination kernel (the daemon) can perform a real coord.* commit without a
# second ledger-write implementation (master design §4.3; reform manifest unit
# K — "collapse the Lisp/Python writer split"). Invoke as a MODULE from the
# council root (``python -m shared.coord_event_log append ...``); a plain-script
# invocation would put ``shared/`` on ``sys.path[0]`` where ``shared/operator.py``
# shadows the stdlib ``operator`` module.


def _coord_event_from_args(args: argparse.Namespace) -> CoordEvent:
    payload: dict[str, Any] = {}
    if args.payload:
        parsed = json.loads(args.payload)
        if not isinstance(parsed, dict):
            raise ValueError("--payload must be a JSON object")
        payload.update(parsed)
    if args.origin:
        payload["origin"] = args.origin
    return CoordEvent(
        event_id=args.event_id or f"coord-verb-{uuid.uuid4().hex}",
        timestamp=args.timestamp or _now_iso(),
        event_type=args.event_type,
        actor=args.actor,
        subject=args.subject,
        authority_case=args.authority_case,
        parent_spec=args.parent_spec,
        payload=payload,
    )


def _event_log_from_args(args: argparse.Namespace) -> CoordEventLog:
    if not (args.db_path or args.jsonl_path or args.spool_dir):
        return default_event_log()
    base = coord_base_dir()
    return CoordEventLog(
        db_path=Path(args.db_path) if args.db_path else base / "ledger.db",
        jsonl_path=Path(args.jsonl_path) if args.jsonl_path else base / "ledger.jsonl",
        spool_dir=Path(args.spool_dir) if args.spool_dir else base / "spool",
    )


def _cli_append(args: argparse.Namespace) -> int:
    """Append one coord event as the daemon writer; emit the receipt as JSON.

    Exit 0 on a durable canonical append (or an idempotent duplicate, or a
    fail-open spool); non-zero on a hard failure so the caller can fall back to
    its daemon-down path rather than claim a mutation it did not perform.
    """
    try:
        event = _coord_event_from_args(args)
    except ValueError as exc:
        print(json.dumps({"error": f"invalid_event: {exc}"}), file=sys.stderr)
        return 2
    log = _event_log_from_args(args)
    try:
        receipt = log.append(
            event, writer=CoordWriter.daemon(name=args.writer_name), fail_open=args.fail_open
        )
    except DuplicateEventError:
        print(
            json.dumps(
                {
                    "event_id": event.event_id,
                    "appended": True,
                    "spooled": False,
                    "sequence": None,
                    "duplicate": True,
                    "db_path": str(log.db_path),
                    "jsonl_path": str(log.jsonl_path),
                    "spool_path": None,
                    "errors": [],
                }
            )
        )
        return 0
    except CoordEventLogError as exc:
        print(
            json.dumps({"error": f"append_failed: {exc}", "event_id": event.event_id}),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "event_id": receipt.event_id,
                "appended": receipt.appended,
                "spooled": receipt.spooled,
                "sequence": receipt.sequence,
                "duplicate": False,
                "db_path": str(receipt.db_path),
                "jsonl_path": str(receipt.jsonl_path),
                "spool_path": str(receipt.spool_path) if receipt.spool_path else None,
                "errors": list(receipt.errors),
            }
        )
    )
    return 0


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coord_event_log",
        description="Daemon-owned coordination ledger writer (single canonical writer).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    ap = sub.add_parser("append", help="append one coord event as the daemon writer")
    ap.add_argument("--event-type", required=True)
    ap.add_argument("--actor", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--authority-case", default=None)
    ap.add_argument("--parent-spec", default=None)
    ap.add_argument("--origin", default=None, help="stamped into payload['origin']")
    ap.add_argument("--payload", default=None, help="JSON object merged into the event payload")
    ap.add_argument("--writer-name", default="hapax-coord")
    ap.add_argument("--event-id", default=None, help="explicit id for idempotent retries")
    ap.add_argument("--timestamp", default=None)
    ap.add_argument(
        "--fail-open", action="store_true", help="spool the event if the canonical append fails"
    )
    ap.add_argument("--db-path", default=None)
    ap.add_argument("--jsonl-path", default=None)
    ap.add_argument("--spool-dir", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_cli_parser().parse_args(argv)
    if args.command == "append":
        return _cli_append(args)
    return 2


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
    "GRANT_DIR_ENV",
    "GRANT_KEY_ENV",
    "ProvisionResult",
    "ReplayResult",
    "SpoolIngestResult",
    "coord_base_dir",
    "default_event_log",
    "default_grant_dir",
    "default_grant_key",
    "main",
    "provision_coord_tree",
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


if __name__ == "__main__":
    raise SystemExit(main())
