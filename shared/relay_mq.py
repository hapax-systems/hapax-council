from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from shared.config import HAPAX_CACHE_DIR
from shared.relay_mq_envelope import (
    DiskPressureError,
    Envelope,
    MessageType,
    RecipientState,
    compute_payload_hash,
    deserialize_tags,
    serialize_tags,
    validate_transition,
)

DEFAULT_DB_PATH: Path = HAPAX_CACHE_DIR / "hapax" / "relay" / "messages.db"
BLOB_DIR: Path = HAPAX_CACHE_DIR / "hapax" / "relay" / "blobs"

_DISK_PRESSURE_THRESHOLD = 10 * 1024 * 1024  # 10MB

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    sender TEXT NOT NULL,
    message_type TEXT NOT NULL
        CHECK (message_type IN ('dispatch', 'advisory', 'escalation', 'query')),
    priority INTEGER NOT NULL DEFAULT 2
        CHECK (priority BETWEEN 0 AND 3),
    subject TEXT NOT NULL,
    authority_case TEXT,
    authority_item TEXT,
    parent_message_id TEXT,
    recipients_spec TEXT NOT NULL,
    payload TEXT,
    payload_path TEXT,
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT,
    stale_after TEXT,
    tags TEXT,

    CHECK (
        (message_type != 'dispatch' OR authority_case IS NOT NULL)
    ),
    CHECK (
        (payload IS NOT NULL AND payload_path IS NULL)
        OR (payload IS NULL AND payload_path IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS recipients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL REFERENCES messages(message_id),
    recipient TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'offered'
        CHECK (state IN (
            'offered', 'read', 'accepted',
            'processed', 'deferred', 'escalated'
        )),
    reason TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(message_id, recipient)
);

CREATE TABLE IF NOT EXISTS dead_letters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    reason TEXT NOT NULL,
    original_state TEXT NOT NULL,
    retry_count INTEGER NOT NULL,
    moved_at TEXT NOT NULL
);
"""

_INDEX_SQL = """\
CREATE INDEX IF NOT EXISTS idx_recipients_pending
    ON recipients(recipient, state)
    WHERE state IN ('offered', 'read');

CREATE INDEX IF NOT EXISTS idx_messages_sender
    ON messages(sender, id);

CREATE INDEX IF NOT EXISTS idx_messages_parent
    ON messages(parent_message_id)
    WHERE parent_message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_messages_authority
    ON messages(authority_case)
    WHERE authority_case IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_messages_expiry
    ON messages(expires_at)
    WHERE expires_at IS NOT NULL;
"""


def _connect(db_path: Path, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA wal_autocheckpoint = 1000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def ensure_schema(db_path: Path) -> None:
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA_SQL)
        conn.executescript(_INDEX_SQL)


def _normalize_role(role: str) -> str:
    return role.strip().lower().replace("_", "-")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _envelope_to_row(env: Envelope) -> dict:
    return {
        "message_id": env.message_id,
        "version": env.version,
        "sender": env.sender,
        "message_type": env.message_type,
        "priority": env.priority,
        "subject": env.subject,
        "authority_case": env.authority_case,
        "authority_item": env.authority_item,
        "parent_message_id": env.parent_message_id,
        "recipients_spec": env.recipients_spec,
        "payload": env.payload,
        "payload_path": env.payload_path,
        "payload_hash": env.payload_hash,
        "created_at": env.created_at.isoformat(),
        "expires_at": env.expires_at.isoformat() if env.expires_at else None,
        "stale_after": env.stale_after.isoformat() if env.stale_after else None,
        "tags": serialize_tags(env.tags),
    }


def _row_to_envelope(row: sqlite3.Row) -> Envelope:
    d = dict(row)
    d["created_at"] = datetime.fromisoformat(d["created_at"])
    if d.get("expires_at"):
        d["expires_at"] = datetime.fromisoformat(d["expires_at"])
    if d.get("stale_after"):
        d["stale_after"] = datetime.fromisoformat(d["stale_after"])
    if d.get("tags"):
        d["tags"] = deserialize_tags(d["tags"])
    d.pop("id", None)
    return Envelope.model_construct(**d)


def expand_recipients(
    spec: str,
    relay_dir: Path | None = None,
) -> list[str]:
    if relay_dir is None:
        relay_dir = HAPAX_CACHE_DIR / "hapax" / "relay"

    if spec.startswith("*:"):
        group = spec[2:].strip().lower()
        yaml_files = sorted(relay_dir.glob("*.yaml"))
        peers = [f.stem for f in yaml_files]

        if not peers:
            raise ValueError(f"Broadcast spec '{spec}' but no peers found in {relay_dir}")

        claude_names = {
            "alpha",
            "beta",
            "gamma",
            "delta",
            "epsilon",
            "zeta",
            "eta",
            "theta",
        }

        if group == "all":
            return peers
        elif group == "coordinators":
            return [p for p in peers if p != "rte" and not p.startswith("timer:")]
        elif group == "claude":
            return [p for p in peers if p in claude_names and not p.startswith("cx-")]
        elif group == "codex":
            return [p for p in peers if p.startswith("cx-")]
        elif group == "gemini":
            return [p for p in peers if p == "iota"]
        else:
            raise ValueError(f"Unknown broadcast group: '{group}'")

    tokens = [_normalize_role(t) for t in spec.split(",") if t.strip()]
    if not tokens:
        raise ValueError("Empty recipients spec")
    return tokens


def send_message(
    db_path: Path,
    envelope: Envelope,
    relay_dir: Path | None = None,
) -> str:
    if envelope.payload_path and envelope.payload_hash is None:
        content = Path(envelope.payload_path).read_bytes()
        envelope.payload_hash = compute_payload_hash(content)

    if envelope.payload and len(envelope.payload) > 50 * 1024:
        BLOB_DIR.mkdir(parents=True, exist_ok=True)
        blob_path = BLOB_DIR / envelope.message_id
        blob_path.write_text(envelope.payload, encoding="utf-8")
        envelope = envelope.model_copy(update={"payload": None, "payload_path": str(blob_path)})

    if str(db_path) != ":memory:":
        free = shutil.disk_usage(db_path.parent).free
        if free < _DISK_PRESSURE_THRESHOLD:
            raise DiskPressureError(
                f"Disk pressure: {free} bytes free at {db_path.parent} (< 10MB)"
            )

    recipients = expand_recipients(envelope.recipients_spec, relay_dir)
    now = _now_iso()

    with _connect(db_path) as conn:
        ensure_schema(db_path)
        row = _envelope_to_row(envelope)
        cols = ", ".join(row.keys())
        placeholders = ", ".join(f":{k}" for k in row)
        conn.execute(f"INSERT INTO messages ({cols}) VALUES ({placeholders})", row)

        for recipient in recipients:
            conn.execute(
                "INSERT INTO recipients (message_id, recipient, state, created_at, updated_at) "
                "VALUES (:message_id, :recipient, 'offered', :now, :now)",
                {"message_id": envelope.message_id, "recipient": recipient, "now": now},
            )
        conn.commit()

    return envelope.message_id


@dataclass
class ConsumedMessage:
    envelope: Envelope
    freshness: Literal["fresh", "stale", "expired"]
    recipient_state: str
    retry_count: int


def consume_messages(
    db_path: Path,
    role: str,
    limit: int = 8,
    busy_timeout_ms: int = 5000,
) -> list[ConsumedMessage]:
    role = _normalize_role(role)
    now = datetime.now(UTC)
    now_iso = now.isoformat()

    with _connect(db_path, busy_timeout_ms) as conn:
        ensure_schema(db_path)

        rows = conn.execute(
            """
            SELECT m.*, r.state AS recipient_state, r.retry_count
            FROM messages m
            JOIN recipients r ON r.message_id = m.message_id
            WHERE r.recipient = :role
              AND r.state = 'offered'
              AND (m.parent_message_id IS NULL
                   OR EXISTS (SELECT 1 FROM recipients r2
                              WHERE r2.message_id = m.parent_message_id
                                AND r2.recipient = :role
                                AND r2.state != 'offered'))
            ORDER BY m.id
            LIMIT :limit
            """,
            {"role": role, "limit": limit},
        ).fetchall()

        result: list[ConsumedMessage] = []
        read_ids: list[str] = []

        for row in rows:
            envelope = _row_to_envelope(row)
            retry_count = row["retry_count"]
            msg_id = envelope.message_id

            expires_at = envelope.expires_at
            stale_after = envelope.stale_after

            if expires_at and expires_at < now:
                conn.execute(
                    "INSERT INTO dead_letters "
                    "(message_id, recipient, reason, original_state, retry_count, moved_at) "
                    "VALUES (:mid, :role, 'expired', 'offered', :rc, :now)",
                    {"mid": msg_id, "role": role, "rc": retry_count, "now": now_iso},
                )
                conn.execute(
                    "DELETE FROM recipients WHERE message_id = :mid AND recipient = :role",
                    {"mid": msg_id, "role": role},
                )
                continue

            if stale_after and stale_after < now:
                freshness: Literal["fresh", "stale", "expired"] = "stale"
            else:
                freshness = "fresh"

            result.append(
                ConsumedMessage(
                    envelope=envelope,
                    freshness=freshness,
                    recipient_state="read",
                    retry_count=retry_count,
                )
            )
            read_ids.append(msg_id)

        for mid in read_ids:
            conn.execute(
                "UPDATE recipients SET state = 'read', updated_at = :now "
                "WHERE message_id = :mid AND recipient = :role AND state = 'offered'",
                {"mid": mid, "role": role, "now": now_iso},
            )

        conn.commit()

    return result


def ack_message(
    db_path: Path,
    message_id: str,
    role: str,
    new_state: RecipientState,
    reason: str | None = None,
) -> bool:
    role = _normalize_role(role)
    now_iso = _now_iso()

    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT state FROM recipients WHERE message_id = :mid AND recipient = :role",
            {"mid": message_id, "role": role},
        ).fetchone()

        if row is None:
            return False

        current_state: RecipientState = row["state"]
        validate_transition(current_state, new_state, reason)

        cursor = conn.execute(
            "UPDATE recipients SET state = :new_state, reason = :reason, updated_at = :now "
            "WHERE message_id = :mid AND recipient = :role AND state = :current",
            {
                "new_state": new_state,
                "reason": reason,
                "now": now_iso,
                "mid": message_id,
                "role": role,
                "current": current_state,
            },
        )

        if cursor.rowcount == 0:
            return False

        conn.commit()

    return True


@dataclass
class MessageFilters:
    recipient: str | None = None
    state: RecipientState | None = None
    priority: int | None = None
    message_type: MessageType | None = None
    sender: str | None = None
    authority_case: str | None = None
    since: datetime | None = None
    limit: int = 50


def list_messages(
    db_path: Path,
    filters: MessageFilters,
) -> list[dict]:
    conditions: list[str] = []
    params: dict[str, object] = {}
    needs_join = filters.recipient is not None or filters.state is not None

    if filters.recipient:
        conditions.append("r.recipient = :recipient")
        params["recipient"] = _normalize_role(filters.recipient)
    if filters.state:
        conditions.append("r.state = :state")
        params["state"] = filters.state
    if filters.priority is not None:
        conditions.append("m.priority = :priority")
        params["priority"] = filters.priority
    if filters.message_type:
        conditions.append("m.message_type = :message_type")
        params["message_type"] = filters.message_type
    if filters.sender:
        conditions.append("m.sender = :sender")
        params["sender"] = _normalize_role(filters.sender)
    if filters.authority_case:
        conditions.append("m.authority_case = :authority_case")
        params["authority_case"] = filters.authority_case
    if filters.since:
        conditions.append("m.created_at >= :since")
        params["since"] = filters.since.isoformat()

    params["limit"] = filters.limit

    if needs_join:
        select = "SELECT m.*, r.state AS recipient_state, r.recipient AS r_recipient"
        from_clause = "FROM messages m JOIN recipients r ON r.message_id = m.message_id"
    else:
        select = "SELECT m.*"
        from_clause = "FROM messages m"

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"{select} {from_clause} {where} ORDER BY m.id DESC LIMIT :limit"

    with _connect(db_path) as conn:
        ensure_schema(db_path)
        rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]


@dataclass
class MessageInspection:
    envelope: Envelope
    recipients: list[dict] = field(default_factory=list)
    dead_letters: list[dict] = field(default_factory=list)


def inspect_message(
    db_path: Path,
    message_id: str,
) -> MessageInspection | None:
    with _connect(db_path) as conn:
        ensure_schema(db_path)

        row = conn.execute(
            "SELECT * FROM messages WHERE message_id = :mid",
            {"mid": message_id},
        ).fetchone()
        if row is None:
            return None

        envelope = _row_to_envelope(row)

        r_rows = conn.execute(
            "SELECT recipient, state, reason, retry_count, created_at, updated_at "
            "FROM recipients WHERE message_id = :mid",
            {"mid": message_id},
        ).fetchall()

        dl_rows = conn.execute(
            "SELECT recipient, reason, original_state, retry_count, moved_at "
            "FROM dead_letters WHERE message_id = :mid",
            {"mid": message_id},
        ).fetchall()

    return MessageInspection(
        envelope=envelope,
        recipients=[dict(r) for r in r_rows],
        dead_letters=[dict(r) for r in dl_rows],
    )


def dead_letters(
    db_path: Path,
    since: datetime | None = None,
    limit: int = 50,
) -> list[dict]:
    params: dict[str, object] = {"limit": limit}
    where = ""
    if since:
        where = "WHERE moved_at >= :since"
        params["since"] = since.isoformat()

    with _connect(db_path) as conn:
        ensure_schema(db_path)
        rows = conn.execute(
            f"SELECT * FROM dead_letters {where} ORDER BY id DESC LIMIT :limit",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


@dataclass
class PurgeResult:
    expired_dead_lettered: int
    blobs_deleted: int


def purge_expired(db_path: Path) -> PurgeResult:
    now_iso = _now_iso()
    expired_count = 0
    blobs_deleted = 0

    with _connect(db_path) as conn:
        ensure_schema(db_path)

        expired_rows = conn.execute(
            """
            SELECT r.message_id, r.recipient, r.state, r.retry_count
            FROM recipients r
            JOIN messages m ON m.message_id = r.message_id
            WHERE r.state = 'offered'
              AND m.expires_at IS NOT NULL
              AND m.expires_at < :now
            """,
            {"now": now_iso},
        ).fetchall()

        for row in expired_rows:
            conn.execute(
                "INSERT INTO dead_letters "
                "(message_id, recipient, reason, original_state, retry_count, moved_at) "
                "VALUES (:mid, :recip, 'expired', :state, :rc, :now)",
                {
                    "mid": row["message_id"],
                    "recip": row["recipient"],
                    "state": row["state"],
                    "rc": row["retry_count"],
                    "now": now_iso,
                },
            )
            conn.execute(
                "DELETE FROM recipients WHERE message_id = :mid AND recipient = :recip",
                {"mid": row["message_id"], "recip": row["recipient"]},
            )
            expired_count += 1

        seven_days_ago = datetime.now(UTC).isoformat()
        terminal_msgs = conn.execute(
            """
            SELECT m.message_id, m.payload_path
            FROM messages m
            WHERE m.payload_path IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM recipients r
                  WHERE r.message_id = m.message_id
                    AND r.state NOT IN ('processed', 'escalated')
              )
              AND NOT EXISTS (
                  SELECT 1 FROM recipients r
                  WHERE r.message_id = m.message_id
                    AND r.updated_at > :cutoff
              )
              AND (
                  EXISTS (SELECT 1 FROM recipients r WHERE r.message_id = m.message_id)
                  OR EXISTS (SELECT 1 FROM dead_letters d WHERE d.message_id = m.message_id)
              )
            """,
            {"cutoff": seven_days_ago},
        ).fetchall()

        for row in terminal_msgs:
            blob_path = Path(row["payload_path"])
            if blob_path.exists():
                blob_path.unlink()
                blobs_deleted += 1

        conn.commit()

    return PurgeResult(expired_dead_lettered=expired_count, blobs_deleted=blobs_deleted)
