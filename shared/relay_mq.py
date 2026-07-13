from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

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
from shared.sdlc_task_store import ClaimDispatchBinding

HAPAX_HOME: Path = Path(os.environ.get("HAPAX_HOME", str(Path.home())))
HAPAX_CACHE_DIR: Path = HAPAX_HOME / ".cache"
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
    return Envelope.model_validate(d)


# Canonical Claude coordination-lane names (greek slots). Codex lanes are
# ``cx-<color>``; Vibe lanes start ``vbe``/``vibe``. Antigrav/Antigravity/legacy
# Gemini relay peers are retired and filtered/refused here so stale YAML files
# cannot remain live broadcast targets. The live agy surface is a read-only
# review route, not a relay peer. These predicates are the single source of truth
# shared by the per-runtime broadcast groups and the cross-runtime ``workers``
# group.
_CLAUDE_LANE_NAMES = frozenset(
    {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"}
)
_RETIRED_ANTIGRAV_NEXT_ACTION = (
    "antigrav and legacy gemini-cli relay recipients are retired/excised; agy is "
    "not a relay peer and only exists as agy.review.direct through "
    "scripts/hapax-agy-reviewer for admitted read-only review-plane work"
)


def _is_claude_lane(peer: str) -> bool:
    return peer in _CLAUDE_LANE_NAMES and not peer.startswith("cx-")


def _is_codex_lane(peer: str) -> bool:
    return peer.startswith("cx-")


def _is_retired_antigrav_lane(peer: str) -> bool:
    normalized = _normalize_role(peer)
    return normalized == "gemini-cli" or normalized.startswith(("agy", "antigrav", "gemini-cli-"))


def _is_vibe_lane(peer: str) -> bool:
    return peer.startswith("vbe") or peer.startswith("vibe")


def _is_worker_lane(peer: str) -> bool:
    """A recognised executor lane across active runtimes."""
    return _is_claude_lane(peer) or _is_codex_lane(peer) or _is_vibe_lane(peer)


def _live_relay_peers(peers: list[str]) -> list[str]:
    return [p for p in peers if not _is_retired_antigrav_lane(p)]


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

        live_peers = _live_relay_peers(peers)

        if group == "all":
            return live_peers
        elif group == "coordinators":
            return [p for p in live_peers if p != "rte" and not p.startswith("timer:")]
        elif group == "claude":
            return [p for p in live_peers if _is_claude_lane(p)]
        elif group == "codex":
            return [p for p in live_peers if _is_codex_lane(p)]
        elif group == "antigrav":
            raise ValueError(_RETIRED_ANTIGRAV_NEXT_ACTION)
        elif group == "vibe":
            return [p for p in live_peers if _is_vibe_lane(p)]
        elif group == "workers":
            return [p for p in live_peers if _is_worker_lane(p)]
        else:
            raise ValueError(f"Unknown broadcast group: '{group}'")

    tokens = [_normalize_role(t) for t in spec.split(",") if t.strip()]
    if not tokens:
        raise ValueError("Empty recipients spec")
    retired = [t for t in tokens if _is_retired_antigrav_lane(t)]
    if retired:
        raise ValueError(_RETIRED_ANTIGRAV_NEXT_ACTION)
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


# --- canon-position echo ------------------------------------------------------

CANON_ECHO_SCHEMA = "hapax.canon-position-echo.v1"
CANON_ECHO_REPAIR_SCHEMA = "hapax.canon-position-echo-repair.v1"
CANON_ECHO_HASH_PREFIX_LENGTH = 16
CANON_ECHO_TAG = "canon-position-echo"
CANON_ECHO_REPAIR_TAG = "canon-position-echo-repair"
CANON_SUCCESSOR_SCHEMA = "hapax.canon-successor-reinjection.v1"
CANON_SUCCESSOR_TAG = "canon-position-successor"
CANON_SUCCESSOR_OUTBOX_SCHEMA = "hapax.canon-successor-outbox.v1"
CANON_SUCCESSOR_OUTBOX_DELIVERED = "sdlc.transition_outbox_delivered"


class CanonEchoError(RuntimeError):
    def __init__(self, reason_code: str, repair_action: str, detail: str | None = None) -> None:
        self.reason_code = reason_code
        self.repair_action = repair_action
        self.detail = detail
        message = f"{reason_code}: {repair_action}"
        if detail:
            message += f" ({detail})"
        super().__init__(message)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _content_hash(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _strict_json_object(raw: str, *, reason_code: str) -> dict:
    def pairs(values: list[tuple[str, object]]) -> dict:
        out: dict[str, object] = {}
        for key, value in values:
            if key in out:
                raise CanonEchoError(
                    reason_code,
                    "remove duplicate JSON keys and emit one canonical object",
                    key,
                )
            out[key] = value
        return out

    try:
        payload = json.loads(raw, object_pairs_hook=pairs)
    except CanonEchoError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise CanonEchoError(
            reason_code,
            "emit valid UTF-8 canonical JSON",
            str(exc),
        ) from exc
    if not isinstance(payload, dict):
        raise CanonEchoError(reason_code, "emit a JSON object at the payload root")
    return payload


def _aware_datetime(value: object, *, field_name: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise CanonEchoError(
            "canon_echo_timestamp_malformed",
            f"emit {field_name} as an ISO-8601 timestamp with timezone",
        ) from exc
    if parsed.tzinfo is None:
        raise CanonEchoError(
            "canon_echo_timestamp_naive",
            f"emit {field_name} with an explicit timezone",
        )
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class ExpectedCanonEcho:
    source_message_id: str
    task_id: str
    lane: str
    authority_case: str
    binding_ref: str
    binding_hash: str
    canon_version: int
    canon_hash: str
    canon_hash_prefix: str
    canon_image_hash: str
    canon_level: str
    canon_payload_sha256: str
    position_ref: str
    position_hash: str
    stage_token: str
    legal_successors: tuple[str, ...]
    constraint_state: str
    constraint_digest_kind: str
    constraint_digest: str

    def to_echo_body(self) -> dict:
        return {
            "binding": {"hash": self.binding_hash, "ref": self.binding_ref},
            "canon": {
                "hash_prefix": self.canon_hash_prefix,
                "image_hash": self.canon_image_hash,
                "level": self.canon_level,
                "version": self.canon_version,
            },
            "constraint_mask": {
                "digest": self.constraint_digest,
                "digest_kind": self.constraint_digest_kind,
                "state": self.constraint_state,
            },
            "lane": self.lane,
            "position": {
                "hash": self.position_hash,
                "next": list(self.legal_successors),
                "ref": self.position_ref,
                "stage_token": self.stage_token,
                "task_id": self.task_id,
            },
            "source_message_id": self.source_message_id,
        }

    def to_record(self) -> dict:
        return {
            "authority_case": self.authority_case,
            "binding_hash": self.binding_hash,
            "binding_ref": self.binding_ref,
            "canon_hash": self.canon_hash,
            "canon_hash_prefix": self.canon_hash_prefix,
            "canon_image_hash": self.canon_image_hash,
            "canon_level": self.canon_level,
            "canon_payload_sha256": self.canon_payload_sha256,
            "canon_version": self.canon_version,
            "constraint_digest": self.constraint_digest,
            "constraint_digest_kind": self.constraint_digest_kind,
            "constraint_state": self.constraint_state,
            "lane": self.lane,
            "legal_successors": list(self.legal_successors),
            "position_hash": self.position_hash,
            "position_ref": self.position_ref,
            "source_message_id": self.source_message_id,
            "stage_token": self.stage_token,
            "task_id": self.task_id,
        }

    @classmethod
    def from_record(cls, value: object) -> ExpectedCanonEcho:
        if not isinstance(value, dict):
            raise CanonEchoError(
                "canon_expected_echo_record_malformed",
                "restore the exact expected-canon record mapping",
            )
        exact_keys = {
            "authority_case",
            "binding_hash",
            "binding_ref",
            "canon_hash",
            "canon_hash_prefix",
            "canon_image_hash",
            "canon_level",
            "canon_payload_sha256",
            "canon_version",
            "constraint_digest",
            "constraint_digest_kind",
            "constraint_state",
            "lane",
            "legal_successors",
            "position_hash",
            "position_ref",
            "source_message_id",
            "stage_token",
            "task_id",
        }
        if (
            set(value) != exact_keys
            or not isinstance(value.get("canon_version"), int)
            or not isinstance(value.get("legal_successors"), list)
            or any(not isinstance(item, str) for item in value.get("legal_successors", []))
            or any(
                not isinstance(value.get(key), str) or not value.get(key)
                for key in exact_keys - {"canon_version", "legal_successors"}
            )
        ):
            raise CanonEchoError(
                "canon_expected_echo_record_malformed",
                "restore the exact typed expected-canon record",
            )
        expected = cls(
            source_message_id=value["source_message_id"],
            task_id=value["task_id"],
            lane=value["lane"],
            authority_case=value["authority_case"],
            binding_ref=value["binding_ref"],
            binding_hash=value["binding_hash"],
            canon_version=value["canon_version"],
            canon_hash=value["canon_hash"],
            canon_hash_prefix=value["canon_hash_prefix"],
            canon_image_hash=value["canon_image_hash"],
            canon_level=value["canon_level"],
            canon_payload_sha256=value["canon_payload_sha256"],
            position_ref=value["position_ref"],
            position_hash=value["position_hash"],
            stage_token=value["stage_token"],
            legal_successors=tuple(value["legal_successors"]),
            constraint_state=value["constraint_state"],
            constraint_digest_kind=value["constraint_digest_kind"],
            constraint_digest=value["constraint_digest"],
        )
        if expected.canon_hash_prefix != expected.canon_hash[:CANON_ECHO_HASH_PREFIX_LENGTH]:
            raise CanonEchoError(
                "canon_expected_echo_record_hash_prefix_mismatch",
                "restore the exact canon hash prefix",
            )
        return expected

    @property
    def repair_key(self) -> str:
        return _content_hash({"schema": CANON_ECHO_REPAIR_SCHEMA, **self.to_echo_body()})


def expected_canon_echo_from_dispatch_record(
    record: dict, *, source_message_id: str
) -> ExpectedCanonEcho:
    if (
        record.get("event") != "methodology_dispatch"
        or record.get("ok") is not True
        or record.get("launched") is not True
        or record.get("launch_returncode") != 0
        or record.get("launch_eligible") is not True
        or record.get("durable_mq_dispatch_bound") is not True
        or record.get("durable_mq_message_id") != source_message_id
        or record.get("may_authorize") is not False
        or record.get("receipt_is_admission") is not False
    ):
        raise CanonEchoError(
            "dispatch_echo_receipt_ineligible",
            "select the successful non-authorizing methodology receipt bound to this MQ message",
            source_message_id,
        )
    binding = record.get("canon_binding")
    if not isinstance(binding, dict):
        raise CanonEchoError(
            "dispatch_echo_binding_missing",
            "restore the complete canon binding in the methodology receipt",
        )
    binding_hash = binding.get("binding_hash")
    binding_ref = binding.get("binding_ref")
    binding_body = {
        key: value for key, value in binding.items() if key not in {"binding_hash", "binding_ref"}
    }
    if (
        not isinstance(binding_hash, str)
        or _content_hash(binding_body) != binding_hash
        or binding_ref != f"dispatch-canon-binding@sha256:{binding_hash}"
        or record.get("canon_binding_hash") != binding_hash
        or record.get("canon_binding_ref") != binding_ref
    ):
        raise CanonEchoError(
            "dispatch_echo_binding_hash_mismatch",
            "restore the exact content-addressed dispatch canon binding",
        )
    canon = binding.get("canon")
    position = binding.get("position")
    if not isinstance(canon, dict) or not isinstance(position, dict):
        raise CanonEchoError(
            "dispatch_echo_binding_shape_malformed",
            "restore the canon and position mappings in the dispatch binding",
        )
    position_hash = position.get("position_hash")
    position_ref = position.get("position_ref")
    position_body = {
        key: value
        for key, value in position.items()
        if key not in {"position_hash", "position_ref"}
    }
    if (
        not isinstance(position_hash, str)
        or _content_hash(position_body) != position_hash
        or position_ref != f"dispatch-position@sha256:{position_hash}"
        or record.get("dispatch_position_hash") != position_hash
        or record.get("dispatch_position_ref") != position_ref
    ):
        raise CanonEchoError(
            "dispatch_echo_position_hash_mismatch",
            "restore the exact content-addressed dispatch position",
        )
    canon_hash = canon.get("canon_hash")
    image_hash = canon.get("image_hash")
    payload_hash = canon.get("payload_sha256")
    constraint_digest = position.get("declared_task_constraint_digest")
    legal_successors = position.get("legal_successors")
    scalar_values = (
        binding_hash,
        binding_ref,
        canon_hash,
        image_hash,
        payload_hash,
        position_hash,
        position_ref,
        constraint_digest,
        position.get("effective_constraint_state"),
        position.get("stage_token"),
        position.get("task_id"),
        position.get("lane"),
        position.get("authority_case"),
        canon.get("level"),
    )
    if (
        any(not isinstance(value, str) or not value for value in scalar_values)
        or not isinstance(canon.get("canon_version"), int)
        or not isinstance(legal_successors, list | tuple)
        or not legal_successors
        or any(not isinstance(value, str) or not value for value in legal_successors)
        or position.get("effective_constraint_state") != "unresolved_scope_chain"
    ):
        raise CanonEchoError(
            "dispatch_echo_binding_semantics_malformed",
            "restore the exact task, stage, successor, canon, and declared-constraint fields",
        )
    return ExpectedCanonEcho(
        source_message_id=source_message_id,
        task_id=str(position["task_id"]),
        lane=str(position["lane"]),
        authority_case=str(position["authority_case"]),
        binding_ref=str(binding_ref),
        binding_hash=str(binding_hash),
        canon_version=int(canon["canon_version"]),
        canon_hash=str(canon_hash),
        canon_hash_prefix=str(canon_hash)[:CANON_ECHO_HASH_PREFIX_LENGTH],
        canon_image_hash=str(image_hash),
        canon_level=str(canon["level"]),
        canon_payload_sha256=str(payload_hash),
        position_ref=str(position_ref),
        position_hash=str(position_hash),
        stage_token=str(position["stage_token"]),
        legal_successors=tuple(str(value) for value in legal_successors),
        constraint_state="unresolved_scope_chain",
        constraint_digest_kind="declared_task_constraint_digest",
        constraint_digest=str(constraint_digest),
    )


def load_dispatch_echo_expectation(
    ledger_path: Path,
    *,
    source_message_id: str,
    task_id: str | None = None,
    lane: str | None = None,
) -> ExpectedCanonEcho:
    matches: list[ExpectedCanonEcho] = []
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CanonEchoError(
            "dispatch_echo_receipt_ledger_unreadable",
            "restore the methodology dispatch receipt ledger",
            str(ledger_path),
        ) from exc
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        record = _strict_json_object(line, reason_code="dispatch_echo_receipt_ledger_malformed")
        if record.get("durable_mq_message_id") != source_message_id:
            continue
        expected = expected_canon_echo_from_dispatch_record(
            record, source_message_id=source_message_id
        )
        if task_id is not None and expected.task_id != task_id:
            raise CanonEchoError(
                "dispatch_echo_task_mismatch",
                "select the dispatch receipt for the exact claimed task",
                f"line={number}",
            )
        if lane is not None and expected.lane != lane:
            raise CanonEchoError(
                "dispatch_echo_lane_mismatch",
                "select the dispatch receipt for the exact owning lane",
                f"line={number}",
            )
        matches.append(expected)
    if not matches:
        raise CanonEchoError(
            "dispatch_echo_receipt_missing",
            "restore the methodology receipt bound to the durable dispatch message",
            source_message_id,
        )
    if any(item != matches[0] for item in matches[1:]):
        raise CanonEchoError(
            "dispatch_echo_receipt_conflict",
            "reconcile conflicting receipts that name one durable dispatch message",
            source_message_id,
        )
    return matches[-1]


def load_latest_dispatch_echo_expectation(
    ledger_path: Path,
    *,
    task_id: str,
    lane: str,
) -> ExpectedCanonEcho:
    try:
        lines = ledger_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CanonEchoError(
            "dispatch_echo_receipt_ledger_unreadable",
            "restore the methodology dispatch receipt ledger",
            str(ledger_path),
        ) from exc
    matches: list[ExpectedCanonEcho] = []
    for line in lines:
        if not line.strip():
            continue
        record = _strict_json_object(line, reason_code="dispatch_echo_receipt_ledger_malformed")
        source_message_id = record.get("durable_mq_message_id")
        if not isinstance(source_message_id, str) or not source_message_id:
            continue
        binding = record.get("canon_binding")
        position = binding.get("position") if isinstance(binding, dict) else None
        if (
            not isinstance(position, dict)
            or position.get("task_id") != task_id
            or position.get("lane") != lane
        ):
            continue
        matches.append(
            expected_canon_echo_from_dispatch_record(record, source_message_id=source_message_id)
        )
    if not matches:
        raise CanonEchoError(
            "dispatch_echo_receipt_missing",
            "restore the latest methodology receipt for the exact task and lane",
            f"{task_id}:{lane}",
        )
    return matches[-1]


@dataclass(frozen=True)
class CanonPositionEcho:
    envelope: Envelope
    body: dict
    observed_at: datetime
    stale_after: datetime
    repair_message_id: str | None = None


@dataclass(frozen=True)
class CanonEchoAssessment:
    status: Literal["matched", "mismatch", "stale"]
    reason_codes: tuple[str, ...]
    message_id: str


@dataclass(frozen=True)
class CanonEchoReconciliation:
    action: Literal["grounded", "repair_issued", "awaiting_repair", "block"]
    reason_code: str
    echo_message_id: str | None = None
    repair_message_id: str | None = None


def _payload_text(envelope: Envelope) -> str:
    if envelope.payload is not None:
        text = envelope.payload
        content = text.encode("utf-8")
    elif envelope.payload_path is not None:
        try:
            content = Path(envelope.payload_path).read_bytes()
            text = content.decode("utf-8")
        except (OSError, UnicodeError) as exc:
            raise CanonEchoError(
                "canon_echo_payload_unreadable",
                "restore the exact UTF-8 MQ payload",
                envelope.message_id,
            ) from exc
    else:
        raise CanonEchoError(
            "canon_echo_payload_missing",
            "restore the inline or referenced MQ payload",
            envelope.message_id,
        )
    if compute_payload_hash(content) != envelope.payload_hash:
        raise CanonEchoError(
            "canon_echo_payload_hash_mismatch",
            "restore the MQ payload committed by payload_hash",
            envelope.message_id,
        )
    return text


def build_canon_echo_envelope(
    expected: ExpectedCanonEcho,
    *,
    sender: str,
    session_id: str,
    observed_at: datetime | None = None,
    stale_after: datetime | None = None,
    repair_message_id: str | None = None,
) -> Envelope:
    observed = (observed_at or datetime.now(UTC)).astimezone(UTC)
    stale = (stale_after or (observed + timedelta(minutes=10))).astimezone(UTC)
    body = {
        **expected.to_echo_body(),
        "kind": "canon_position_echo",
        "may_authorize": False,
        "observed_at": observed.isoformat(),
        "schema": CANON_ECHO_SCHEMA,
        "session_id": session_id,
        "stale_after": stale.isoformat(),
    }
    if repair_message_id is not None:
        body["repair_message_id"] = repair_message_id
    payload = {**body, "echo_hash": _content_hash(body)}
    return Envelope(
        sender=sender,
        message_type="advisory",
        priority=0,
        subject=f"canon echo: {expected.task_id}",
        authority_case=expected.authority_case,
        authority_item=expected.task_id,
        parent_message_id=repair_message_id or expected.source_message_id,
        recipients_spec="hapax-coordinator",
        payload=_canonical_json_bytes(payload).decode("ascii"),
        created_at=observed,
        stale_after=stale,
        tags=[CANON_ECHO_TAG],
    )


def parse_canon_echo(envelope: Envelope) -> CanonPositionEcho:
    checked = Envelope.model_validate(envelope.model_dump(mode="python"))
    if checked.parent_message_id is None or CANON_ECHO_TAG not in (checked.tags or []):
        raise CanonEchoError(
            "canon_echo_envelope_binding_missing",
            "send the echo as a tagged child of the durable dispatch message",
            checked.message_id,
        )
    payload = _strict_json_object(
        _payload_text(checked), reason_code="canon_echo_payload_malformed"
    )
    exact_keys = {
        "binding",
        "canon",
        "constraint_mask",
        "echo_hash",
        "kind",
        "lane",
        "may_authorize",
        "observed_at",
        "position",
        "schema",
        "session_id",
        "source_message_id",
        "stale_after",
    }
    repair_message_id = payload.get("repair_message_id")
    if repair_message_id is not None:
        exact_keys.add("repair_message_id")
    body = {key: value for key, value in payload.items() if key != "echo_hash"}
    if (
        set(payload) != exact_keys
        or payload.get("schema") != CANON_ECHO_SCHEMA
        or payload.get("kind") != "canon_position_echo"
        or payload.get("may_authorize") is not False
        or (
            repair_message_id is None
            and payload.get("source_message_id") != checked.parent_message_id
        )
        or (
            repair_message_id is not None
            and (
                not isinstance(repair_message_id, str)
                or not repair_message_id
                or checked.parent_message_id != repair_message_id
            )
        )
        or payload.get("echo_hash") != _content_hash(body)
    ):
        raise CanonEchoError(
            "canon_echo_shape_or_hash_mismatch",
            "emit the exact self-hashed canon-position echo schema",
            checked.message_id,
        )
    for key, expected_keys in {
        "binding": {"hash", "ref"},
        "canon": {"hash_prefix", "image_hash", "level", "version"},
        "constraint_mask": {"digest", "digest_kind", "state"},
        "position": {"hash", "next", "ref", "stage_token", "task_id"},
    }.items():
        value = payload.get(key)
        if not isinstance(value, dict) or set(value) != expected_keys:
            raise CanonEchoError(
                "canon_echo_nested_shape_malformed",
                "emit the exact binding, canon, constraint, and position subobjects",
                key,
            )
    observed = _aware_datetime(payload["observed_at"], field_name="observed_at")
    stale = _aware_datetime(payload["stale_after"], field_name="stale_after")
    if (
        stale - observed != timedelta(minutes=10)
        or checked.created_at.astimezone(UTC) != observed
        or checked.stale_after is None
        or checked.stale_after.astimezone(UTC) != stale
        or checked.expires_at is None
        or checked.expires_at.astimezone(UTC) < stale
    ):
        raise CanonEchoError(
            "canon_echo_freshness_window_invalid",
            "bind envelope creation, observation, and expiry to one ordered window",
            checked.message_id,
        )
    return CanonPositionEcho(
        envelope=checked,
        body=body,
        observed_at=observed,
        stale_after=stale,
        repair_message_id=repair_message_id,
    )


def assess_canon_echo(
    expected: ExpectedCanonEcho,
    echo: CanonPositionEcho,
    *,
    now: datetime | None = None,
    expected_sender: str | None = None,
    expected_session_id: str | None = None,
) -> CanonEchoAssessment:
    reasons: list[str] = []
    observed = echo.body
    expected_body = expected.to_echo_body()
    for key in ("binding", "canon", "constraint_mask", "lane", "position", "source_message_id"):
        if observed.get(key) != expected_body[key]:
            reasons.append(f"canon_echo_{key}_mismatch")
    if not isinstance(observed.get("session_id"), str) or not observed["session_id"]:
        reasons.append("canon_echo_session_missing")
    if expected_session_id is not None and observed.get("session_id") != expected_session_id:
        reasons.append("canon_echo_session_mismatch")
    if expected_sender is not None:
        normalized = expected_sender.strip().lower().replace("_", "-")
        if echo.envelope.sender != normalized:
            reasons.append("canon_echo_sender_mismatch")
    if echo.envelope.authority_case != expected.authority_case:
        reasons.append("canon_echo_authority_case_mismatch")
    if echo.envelope.authority_item != expected.task_id:
        reasons.append("canon_echo_authority_item_mismatch")
    if echo.envelope.recipients_spec != "hapax-coordinator":
        reasons.append("canon_echo_recipient_mismatch")
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if echo.observed_at > current + timedelta(seconds=30):
        reasons.append("canon_echo_observed_in_future")
    if current > echo.stale_after:
        reasons.append("canon_echo_stale")
        status: Literal["matched", "mismatch", "stale"] = "stale"
    else:
        status = "mismatch" if reasons else "matched"
    return CanonEchoAssessment(status, tuple(reasons), echo.envelope.message_id)


def require_matching_canon_echo(
    db_path: Path,
    expected: ExpectedCanonEcho,
    *,
    echo_message_id: str,
    now: datetime | None = None,
    expected_sender: str | None = None,
    expected_session_id: str | None = None,
) -> CanonPositionEcho:
    inspected = inspect_message(db_path, echo_message_id)
    if inspected is None:
        raise CanonEchoError(
            "canon_echo_receipt_missing",
            "restore the exact child MQ echo receipt before transition",
            echo_message_id,
        )
    echo = parse_canon_echo(inspected.envelope)
    assessment = assess_canon_echo(
        expected,
        echo,
        now=now,
        expected_sender=expected_sender,
        expected_session_id=expected_session_id,
    )
    if assessment.status != "matched":
        raise CanonEchoError(
            "canon_echo_receipt_not_matching",
            "use the fresh exact echo bound to the current dispatch position",
            ",".join(assessment.reason_codes),
        )
    return echo


def _child_envelopes(db_path: Path, source_message_id: str) -> list[Envelope]:
    del source_message_id
    if not db_path.is_file():
        return []
    raise CanonEchoError(
        "canon_echo_projection_required",
        "consume a source-local immutable current relay projection; the live WAL database is not an effect-pure observation surface",
        str(db_path),
    )


def build_successor_canon_position(
    predecessor: ExpectedCanonEcho,
    *,
    transition_id: str,
    stage_token: str,
    legal_successors: tuple[str, ...],
    canon_hash: str,
    canon_version: int,
    canon_image_hash: str,
    canon_level: str,
    rendered_payload: str,
    now: datetime | None = None,
) -> tuple[ExpectedCanonEcho, Envelope]:
    created = (now or datetime.now(UTC)).astimezone(UTC)
    payload_sha256 = compute_payload_hash(rendered_payload)
    position_body = {
        "authority_case": predecessor.authority_case,
        "constraint_digest": predecessor.constraint_digest,
        "constraint_digest_kind": predecessor.constraint_digest_kind,
        "constraint_state": predecessor.constraint_state,
        "lane": predecessor.lane,
        "legal_successors": list(legal_successors),
        "predecessor_position_ref": predecessor.position_ref,
        "stage_token": stage_token,
        "task_id": predecessor.task_id,
        "transition_id": transition_id,
    }
    position_hash = _content_hash(position_body)
    position_ref = f"successor-position@sha256:{position_hash}"
    binding_body = {
        "canon": {
            "canon_hash": canon_hash,
            "canon_version": canon_version,
            "image_hash": canon_image_hash,
            "level": canon_level,
            "payload_sha256": payload_sha256,
        },
        "may_authorize": False,
        "position": {**position_body, "position_hash": position_hash, "position_ref": position_ref},
        "schema": CANON_SUCCESSOR_SCHEMA,
    }
    binding_hash = _content_hash(binding_body)
    binding_ref = f"successor-canon-binding@sha256:{binding_hash}"
    message_seed = {
        "binding_hash": binding_hash,
        "predecessor_source_message_id": predecessor.source_message_id,
        "transition_id": transition_id,
    }
    message_id = f"canon-successor-{_content_hash(message_seed)[:40]}"
    expected = ExpectedCanonEcho(
        source_message_id=message_id,
        task_id=predecessor.task_id,
        lane=predecessor.lane,
        authority_case=predecessor.authority_case,
        binding_ref=binding_ref,
        binding_hash=binding_hash,
        canon_version=canon_version,
        canon_hash=canon_hash,
        canon_hash_prefix=canon_hash[:CANON_ECHO_HASH_PREFIX_LENGTH],
        canon_image_hash=canon_image_hash,
        canon_level=canon_level,
        canon_payload_sha256=payload_sha256,
        position_ref=position_ref,
        position_hash=position_hash,
        stage_token=stage_token,
        legal_successors=legal_successors,
        constraint_state=predecessor.constraint_state,
        constraint_digest_kind=predecessor.constraint_digest_kind,
        constraint_digest=predecessor.constraint_digest,
    )
    body = {
        "authority_case": predecessor.authority_case,
        "canon_hash": canon_hash,
        "canon_payload": rendered_payload,
        "canon_payload_sha256": payload_sha256,
        "expected_echo": expected.to_echo_body(),
        "kind": "canon_successor_reinjection",
        "may_authorize": False,
        "predecessor_position_ref": predecessor.position_ref,
        "predecessor_source_message_id": predecessor.source_message_id,
        "schema": CANON_SUCCESSOR_SCHEMA,
        "transition_id": transition_id,
    }
    payload = {**body, "reinjection_hash": _content_hash(body)}
    envelope = Envelope(
        message_id=message_id,
        sender="sdlc-transition",
        message_type="advisory",
        priority=0,
        subject=f"successor canon position: {predecessor.task_id}:{stage_token}",
        authority_case=predecessor.authority_case,
        authority_item=predecessor.task_id,
        parent_message_id=predecessor.source_message_id,
        recipients_spec=predecessor.lane,
        payload=_canonical_json_bytes(payload).decode("ascii"),
        created_at=created,
        tags=[CANON_SUCCESSOR_TAG],
    )
    return expected, envelope


def persist_exact_envelope(db_path: Path, envelope: Envelope) -> tuple[Envelope, bool]:
    try:
        send_message(db_path, envelope)
    except sqlite3.IntegrityError as exc:
        inspected = inspect_message(db_path, envelope.message_id)
        if inspected is None or inspected.envelope.model_dump(mode="json") != envelope.model_dump(
            mode="json"
        ):
            raise CanonEchoError(
                "canon_successor_message_id_collision",
                "preserve the first exact successor reinjection message",
                envelope.message_id,
            ) from exc
        return inspected.envelope, True
    return envelope, False


def send_successor_canon_position(
    db_path: Path,
    predecessor: ExpectedCanonEcho,
    *,
    transition_id: str,
    stage_token: str,
    legal_successors: tuple[str, ...],
    canon_hash: str,
    canon_version: int,
    canon_image_hash: str,
    canon_level: str,
    rendered_payload: str,
    now: datetime | None = None,
) -> tuple[ExpectedCanonEcho, Envelope, bool]:
    raise CanonEchoError(
        "canon_successor_direct_send_retired",
        "project a durable successor outbox in the applied transition, then drain it",
        predecessor.task_id,
    )


@dataclass(frozen=True)
class SuccessorOutbox:
    action_id: str
    transition_ref: str
    predecessor: ExpectedCanonEcho
    successor: ExpectedCanonEcho
    envelope: Envelope
    payload: bytes


def build_successor_outbox(
    predecessor: ExpectedCanonEcho,
    successor: ExpectedCanonEcho,
    envelope: Envelope,
    *,
    transition_ref: str,
) -> SuccessorOutbox:
    parsed = expected_canon_echo_from_successor(envelope)
    if parsed != successor or envelope.parent_message_id != predecessor.source_message_id:
        raise CanonEchoError(
            "canon_successor_outbox_binding_mismatch",
            "bind the exact successor envelope and predecessor into one outbox action",
            envelope.message_id,
        )
    core = {
        "envelope": envelope.model_dump(mode="json"),
        "envelope_sha256": _content_hash(envelope.model_dump(mode="json")),
        "kind": "relay_mq.envelope.send",
        "may_authorize": False,
        "predecessor": predecessor.to_record(),
        "schema": CANON_SUCCESSOR_OUTBOX_SCHEMA,
        "successor": successor.to_record(),
        "transition_ref": transition_ref,
    }
    action_id = f"canon-successor-outbox-{_content_hash(core)}"
    body = {**core, "action_id": action_id}
    payload = _canonical_json_bytes({**body, "outbox_hash": _content_hash(body)}) + b"\n"
    return SuccessorOutbox(
        action_id=action_id,
        transition_ref=transition_ref,
        predecessor=predecessor,
        successor=successor,
        envelope=envelope,
        payload=payload,
    )


def parse_successor_outbox(payload: bytes) -> SuccessorOutbox:
    try:
        text = payload.decode("ascii")
    except UnicodeError as exc:
        raise CanonEchoError(
            "canon_successor_outbox_encoding_invalid",
            "restore the exact ASCII canonical outbox payload",
        ) from exc
    record = _strict_json_object(text, reason_code="canon_successor_outbox_malformed")
    exact_keys = {
        "action_id",
        "envelope",
        "envelope_sha256",
        "kind",
        "may_authorize",
        "outbox_hash",
        "predecessor",
        "schema",
        "successor",
        "transition_ref",
    }
    body = {key: value for key, value in record.items() if key != "outbox_hash"}
    core = {key: value for key, value in body.items() if key != "action_id"}
    action_id = f"canon-successor-outbox-{_content_hash(core)}"
    if (
        set(record) != exact_keys
        or record.get("schema") != CANON_SUCCESSOR_OUTBOX_SCHEMA
        or record.get("kind") != "relay_mq.envelope.send"
        or record.get("may_authorize") is not False
        or record.get("action_id") != action_id
        or record.get("outbox_hash") != _content_hash(body)
        or not isinstance(record.get("transition_ref"), str)
        or not record["transition_ref"]
    ):
        raise CanonEchoError(
            "canon_successor_outbox_shape_or_hash_mismatch",
            "restore the exact self-hashed successor outbox action",
        )
    try:
        envelope = Envelope.model_validate(record["envelope"])
    except (TypeError, ValueError) as exc:
        raise CanonEchoError(
            "canon_successor_outbox_envelope_malformed",
            "restore the exact typed MQ envelope in the outbox",
        ) from exc
    if record.get("envelope_sha256") != _content_hash(envelope.model_dump(mode="json")):
        raise CanonEchoError(
            "canon_successor_outbox_envelope_hash_mismatch",
            "restore the envelope committed by the outbox hash",
            envelope.message_id,
        )
    predecessor = ExpectedCanonEcho.from_record(record["predecessor"])
    successor = ExpectedCanonEcho.from_record(record["successor"])
    parsed = expected_canon_echo_from_successor(envelope)
    if parsed != successor or envelope.parent_message_id != predecessor.source_message_id:
        raise CanonEchoError(
            "canon_successor_outbox_binding_mismatch",
            "restore the successor and predecessor committed by the envelope",
            envelope.message_id,
        )
    if payload != _canonical_json_bytes(record) + b"\n":
        raise CanonEchoError(
            "canon_successor_outbox_not_canonical",
            "restore the exact canonical successor outbox bytes",
            action_id,
        )
    return SuccessorOutbox(
        action_id=action_id,
        transition_ref=str(record["transition_ref"]),
        predecessor=predecessor,
        successor=successor,
        envelope=envelope,
        payload=payload,
    )


def _successor_delivery_event(
    applied_event: object,
    outbox: SuccessorOutbox,
    outbox_path: Path,
) -> object:
    from shared.coord_event_log import CoordEvent

    recipient = _normalize_role(outbox.successor.lane)
    return CoordEvent(
        event_id=f"{outbox.action_id}.delivered",
        timestamp=str(applied_event.timestamp),
        event_type=CANON_SUCCESSOR_OUTBOX_DELIVERED,
        actor="sdlc-transition-outbox",
        subject=outbox.successor.task_id,
        authority_case=outbox.successor.authority_case,
        payload={
            "action_id": outbox.action_id,
            "delivery_semantics": "durable_mq_carriage",
            "envelope_message_id": outbox.envelope.message_id,
            "envelope_sha256": _content_hash(outbox.envelope.model_dump(mode="json")),
            "may_authorize": False,
            "outbox_path": str(Path(os.path.abspath(outbox_path.expanduser()))),
            "outbox_sha256": hashlib.sha256(outbox.payload).hexdigest(),
            "receipt_is_admission": False,
            "recipient": recipient,
            "schema": CANON_SUCCESSOR_OUTBOX_SCHEMA,
            "transition_ref": outbox.transition_ref,
        },
    )


def _exact_delivery_receipt(event_log: object, expected: object) -> object | None:
    replay = event_log.replay(fail_open=False)
    if replay.degraded or replay.source != "sqlite":
        raise CanonEchoError(
            "canon_successor_delivery_replay_degraded",
            "restore canonical SQLite replay before successor delivery",
        )
    matches = [event for event in replay.events if event.event_id == expected.event_id]
    if not matches:
        return None
    if len(matches) != 1 or matches[0].to_record() != expected.to_record(
        sequence=matches[0].sequence
    ):
        raise CanonEchoError(
            "canon_successor_outbox_delivery_collision",
            "preserve the first exact delivery receipt",
            expected.event_id,
        )
    return matches[0]


def _lineage_is_exact(
    envelope: Envelope,
    recipient: str,
    live_rows: list[sqlite3.Row],
    dead_rows: list[sqlite3.Row],
) -> bool:
    if len(live_rows) == 1 and not dead_rows:
        row = live_rows[0]
        try:
            created = datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            updated = datetime.fromisoformat(str(row["updated_at"]).replace("Z", "+00:00"))
        except ValueError:
            return False
        return (
            row["recipient"] == recipient
            and row["state"]
            in {"offered", "read", "accepted", "processed", "deferred", "escalated"}
            and isinstance(row["retry_count"], int)
            and row["retry_count"] >= 0
            and updated >= created
        )
    if live_rows or len(dead_rows) != 1 or envelope.expires_at is None:
        return False
    row = dead_rows[0]
    try:
        moved = datetime.fromisoformat(str(row["moved_at"]).replace("Z", "+00:00"))
    except ValueError:
        return False
    return (
        row["recipient"] == recipient
        and row["reason"] == "expired"
        and row["original_state"] == "offered"
        and isinstance(row["retry_count"], int)
        and row["retry_count"] >= 0
        and moved >= envelope.expires_at.astimezone(UTC)
    )


def deliver_successor_outbox(
    db_path: Path,
    event_log: object,
    outbox: SuccessorOutbox,
    *,
    outbox_path: Path,
    timestamp: str | None = None,
) -> bool:
    del timestamp  # Applied-event time is the deterministic delivery receipt time.
    applied_event = _require_successor_applied(
        event_log,
        outbox.predecessor,
        outbox.successor,
        outbox.envelope,
        transition_ref=outbox.transition_ref,
        outbox_path=outbox_path,
        outbox_payload=outbox.payload,
    )
    event = _successor_delivery_event(applied_event, outbox, outbox_path)
    existing_receipt = _exact_delivery_receipt(event_log, event)
    recipient = _normalize_role(outbox.successor.lane)
    if expand_recipients(outbox.envelope.recipients_spec) != [recipient]:
        raise CanonEchoError(
            "canon_successor_recipient_mismatch",
            "bind the successor to exactly one normalized owning lane",
            outbox.envelope.recipients_spec,
        )
    message_existed = False
    with _connect(db_path) as conn:
        ensure_schema(db_path)
        conn.execute("BEGIN IMMEDIATE")
        message_row = conn.execute(
            "SELECT * FROM messages WHERE message_id = ?",
            (outbox.envelope.message_id,),
        ).fetchone()
        live_rows = conn.execute(
            "SELECT * FROM recipients WHERE message_id = ? ORDER BY id",
            (outbox.envelope.message_id,),
        ).fetchall()
        dead_rows = conn.execute(
            "SELECT * FROM dead_letters WHERE message_id = ? ORDER BY id",
            (outbox.envelope.message_id,),
        ).fetchall()
        if message_row is None:
            if existing_receipt is not None or live_rows or dead_rows:
                raise CanonEchoError(
                    "canon_successor_delivery_lineage_missing",
                    "restore the exact message lineage committed before the delivery receipt",
                    outbox.envelope.message_id,
                )
            row = _envelope_to_row(outbox.envelope)
            columns = ", ".join(row)
            placeholders = ", ".join(f":{key}" for key in row)
            conn.execute(f"INSERT INTO messages ({columns}) VALUES ({placeholders})", row)
            now = _now_iso()
            conn.execute(
                "INSERT INTO recipients "
                "(message_id, recipient, state, created_at, updated_at) "
                "VALUES (?, ?, 'offered', ?, ?)",
                (outbox.envelope.message_id, recipient, now, now),
            )
        else:
            message_existed = True
            if _row_to_envelope(message_row).model_dump(mode="json") != outbox.envelope.model_dump(
                mode="json"
            ) or not _lineage_is_exact(outbox.envelope, recipient, live_rows, dead_rows):
                raise CanonEchoError(
                    "canon_successor_delivery_lineage_mismatch",
                    "preserve one exact live or expired successor enqueue lineage",
                    outbox.envelope.message_id,
                )
        conn.commit()
    from shared.coord_event_log import CoordWriter, DuplicateEventError

    if existing_receipt is None:
        try:
            event_log.append(event, writer=CoordWriter.daemon("sdlc-transition-outbox"))
        except DuplicateEventError:
            _exact_delivery_receipt(event_log, event)
    return existing_receipt is not None or message_existed


def successor_outbox_task_directory(root: Path, task_id: str) -> Path:
    if not task_id.strip():
        raise CanonEchoError(
            "canon_successor_outbox_task_missing",
            "bind the durable outbox partition to one exact task",
        )
    normalized_root = Path(os.path.abspath(root.expanduser()))
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    return normalized_root / f"task-{digest}"


def _open_real_directory_fd(path: Path) -> int:
    normalized = Path(os.path.abspath(path.expanduser()))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for component in normalized.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except Exception:
        os.close(fd)
        raise


def ensure_successor_outbox_task_directory(root: Path, task_id: str) -> Path:
    directory = successor_outbox_task_directory(root, task_id)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for component in directory.parts[1:]:
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                next_fd = os.open(component, flags, dir_fd=fd)
                os.fsync(fd)
            os.close(fd)
            fd = next_fd
        return directory
    except Exception:
        os.close(fd)
        raise
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def drain_successor_outboxes(
    db_path: Path,
    event_log: object,
    outbox_dir: Path,
    *,
    task_id: str | None = None,
) -> tuple[str, ...]:
    """Deliver every exact applied outbox for one task, retaining durable files."""

    try:
        directory_fd = _open_real_directory_fd(outbox_dir)
    except FileNotFoundError:
        return ()
    except OSError as exc:
        raise CanonEchoError(
            "canon_successor_outbox_directory_unsafe",
            "restore the durable outbox as one real directory",
            str(outbox_dir),
        ) from exc
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise CanonEchoError(
                "canon_successor_outbox_directory_unsafe",
                "restore the durable outbox as one real directory",
                str(outbox_dir),
            )
        with os.scandir(directory_fd) as entries:
            names = sorted(
                entry.name
                for entry in entries
                if entry.name.startswith("canon-successor-outbox-") and entry.name.endswith(".json")
            )
        delivered: list[str] = []
        for name in names:
            path = outbox_dir / name
            try:
                file_fd = os.open(
                    name,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory_fd,
                )
                try:
                    if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                        raise OSError("outbox entry is not a regular file")
                    chunks: list[bytes] = []
                    while chunk := os.read(file_fd, 1024 * 1024):
                        chunks.append(chunk)
                    payload = b"".join(chunks)
                finally:
                    os.close(file_fd)
            except OSError as exc:
                raise CanonEchoError(
                    "canon_successor_outbox_unreadable",
                    "restore the exact durable successor outbox file",
                    str(path),
                ) from exc
            outbox = parse_successor_outbox(payload)
            if name != f"{outbox.action_id}.json":
                raise CanonEchoError(
                    "canon_successor_outbox_filename_mismatch",
                    "name the durable outbox by its exact content-addressed action id",
                    str(path),
                )
            if task_id is not None and outbox.successor.task_id != task_id:
                continue
            deliver_successor_outbox(db_path, event_log, outbox, outbox_path=path)
            delivered.append(outbox.action_id)
        return tuple(delivered)
    finally:
        os.close(directory_fd)


def expected_canon_echo_from_successor(envelope: Envelope) -> ExpectedCanonEcho:
    checked = Envelope.model_validate(envelope.model_dump(mode="python"))
    if CANON_SUCCESSOR_TAG not in (checked.tags or []) or checked.parent_message_id is None:
        raise CanonEchoError(
            "canon_successor_envelope_binding_missing",
            "restore the tagged successor message and its predecessor parent",
            checked.message_id,
        )
    payload = _strict_json_object(
        _payload_text(checked), reason_code="canon_successor_payload_malformed"
    )
    exact_keys = {
        "authority_case",
        "canon_hash",
        "canon_payload",
        "canon_payload_sha256",
        "expected_echo",
        "kind",
        "may_authorize",
        "predecessor_position_ref",
        "predecessor_source_message_id",
        "reinjection_hash",
        "schema",
        "transition_id",
    }
    body = {key: value for key, value in payload.items() if key != "reinjection_hash"}
    if (
        set(payload) != exact_keys
        or payload.get("schema") != CANON_SUCCESSOR_SCHEMA
        or payload.get("kind") != "canon_successor_reinjection"
        or payload.get("may_authorize") is not False
        or payload.get("predecessor_source_message_id") != checked.parent_message_id
        or payload.get("reinjection_hash") != _content_hash(body)
        or not isinstance(payload.get("expected_echo"), dict)
    ):
        raise CanonEchoError(
            "canon_successor_shape_or_hash_mismatch",
            "restore the exact self-hashed successor reinjection payload",
            checked.message_id,
        )
    expected_body = payload["expected_echo"]
    binding = expected_body.get("binding")
    canon = expected_body.get("canon")
    constraint = expected_body.get("constraint_mask")
    position = expected_body.get("position")
    if not all(isinstance(value, dict) for value in (binding, canon, constraint, position)):
        raise CanonEchoError(
            "canon_successor_expected_echo_malformed",
            "restore the exact expected echo binding in the successor payload",
        )
    assert isinstance(binding, dict)
    assert isinstance(canon, dict)
    assert isinstance(constraint, dict)
    assert isinstance(position, dict)
    legal_successors = position.get("next")
    if (
        set(expected_body)
        != {
            "binding",
            "canon",
            "constraint_mask",
            "lane",
            "position",
            "source_message_id",
        }
        or set(binding) != {"hash", "ref"}
        or set(canon) != {"hash_prefix", "image_hash", "level", "version"}
        or set(constraint) != {"digest", "digest_kind", "state"}
        or set(position) != {"hash", "next", "ref", "stage_token", "task_id"}
        or expected_body.get("source_message_id") != checked.message_id
        or not isinstance(legal_successors, list)
        or any(not isinstance(value, str) for value in legal_successors)
        or canon.get("hash_prefix")
        != str(payload.get("canon_hash"))[:CANON_ECHO_HASH_PREFIX_LENGTH]
        or payload.get("canon_payload_sha256")
        != compute_payload_hash(str(payload.get("canon_payload")))
    ):
        raise CanonEchoError(
            "canon_successor_expected_echo_mismatch",
            "restore the successor message whose echo binding matches its exact payload",
            checked.message_id,
        )
    position_body = {
        "authority_case": payload.get("authority_case"),
        "constraint_digest": constraint.get("digest"),
        "constraint_digest_kind": constraint.get("digest_kind"),
        "constraint_state": constraint.get("state"),
        "lane": expected_body.get("lane"),
        "legal_successors": legal_successors,
        "predecessor_position_ref": None,
        "stage_token": position.get("stage_token"),
        "task_id": position.get("task_id"),
        "transition_id": payload.get("transition_id"),
    }
    # The full predecessor ref sits outside the low-rate echo but remains inside
    # the self-hashed reinjection payload, allowing exact position recomputation.
    predecessor_position_ref = payload.get("predecessor_position_ref")
    if not isinstance(predecessor_position_ref, str) or not predecessor_position_ref:
        raise CanonEchoError(
            "canon_successor_predecessor_position_missing",
            "bind the exact predecessor position in the successor payload",
            checked.message_id,
        )
    position_body["predecessor_position_ref"] = predecessor_position_ref
    expected_position_hash = _content_hash(position_body)
    binding_body = {
        "canon": {
            "canon_hash": payload.get("canon_hash"),
            "canon_version": canon.get("version"),
            "image_hash": canon.get("image_hash"),
            "level": canon.get("level"),
            "payload_sha256": payload.get("canon_payload_sha256"),
        },
        "may_authorize": False,
        "position": {
            **position_body,
            "position_hash": expected_position_hash,
            "position_ref": f"successor-position@sha256:{expected_position_hash}",
        },
        "schema": CANON_SUCCESSOR_SCHEMA,
    }
    expected_binding_hash = _content_hash(binding_body)
    expected_message_id = f"canon-successor-{_content_hash({'binding_hash': expected_binding_hash, 'predecessor_source_message_id': checked.parent_message_id, 'transition_id': payload.get('transition_id')})[:40]}"
    if (
        position.get("hash") != expected_position_hash
        or position.get("ref") != f"successor-position@sha256:{expected_position_hash}"
        or binding.get("hash") != expected_binding_hash
        or binding.get("ref") != f"successor-canon-binding@sha256:{expected_binding_hash}"
        or checked.message_id != expected_message_id
        or checked.sender != "sdlc-transition"
        or checked.message_type != "advisory"
        or checked.priority != 0
        or checked.authority_case != payload.get("authority_case")
        or checked.authority_item != position.get("task_id")
        or checked.recipients_spec != expected_body.get("lane")
    ):
        raise CanonEchoError(
            "canon_successor_binding_hash_mismatch",
            "restore the exact content-addressed successor position and binding",
            checked.message_id,
        )
    return ExpectedCanonEcho(
        source_message_id=checked.message_id,
        task_id=str(position.get("task_id")),
        lane=str(expected_body.get("lane")),
        authority_case=str(payload.get("authority_case")),
        binding_ref=str(binding.get("ref")),
        binding_hash=str(binding.get("hash")),
        canon_version=int(canon.get("version")),
        canon_hash=str(payload.get("canon_hash")),
        canon_hash_prefix=str(canon.get("hash_prefix")),
        canon_image_hash=str(canon.get("image_hash")),
        canon_level=str(canon.get("level")),
        canon_payload_sha256=str(payload.get("canon_payload_sha256")),
        position_ref=str(position.get("ref")),
        position_hash=str(position.get("hash")),
        stage_token=str(position.get("stage_token")),
        legal_successors=tuple(legal_successors),
        constraint_state=str(constraint.get("state")),
        constraint_digest_kind=str(constraint.get("digest_kind")),
        constraint_digest=str(constraint.get("digest")),
    )


def load_latest_canon_echo_expectation(
    *,
    task_id: str,
    lane: str,
    stage_token: str | None = None,
) -> ExpectedCanonEcho:
    raise CanonEchoError(
        "canon_global_latest_position_retired",
        "resolve the current position from the exact claim binding and causal chain",
        f"{task_id}:{lane}:{stage_token or '*'}",
    )


def _require_claim_dispatch_root(
    binding: ClaimDispatchBinding,
) -> ExpectedCanonEcho:
    raise CanonEchoError(
        "canon_pre_gate0_claim_migration_required",
        (
            "migrate this exact legacy claim into a typed applied ownership proof "
            "and authenticated outcome replay before resolving lifecycle currentness"
        ),
        binding.receipt_hash,
    )


def _require_successor_applied(
    event_log: object,
    predecessor: ExpectedCanonEcho,
    successor: ExpectedCanonEcho,
    envelope: Envelope,
    *,
    transition_ref: str | None = None,
    outbox_path: Path | None = None,
    outbox_payload: bytes | None = None,
) -> object:
    payload = _strict_json_object(
        _payload_text(envelope), reason_code="canon_successor_payload_malformed"
    )
    payload_transition_ref = payload.get("transition_id")
    if not isinstance(payload_transition_ref, str) or not payload_transition_ref:
        raise CanonEchoError(
            "canon_successor_transition_id_missing",
            "bind the successor to one exact applied transition attempt",
            envelope.message_id,
        )
    try:
        replay = event_log.replay(fail_open=False)
    except Exception as exc:
        raise CanonEchoError(
            "canon_successor_transition_log_unavailable",
            "restore canonical transition replay before resolving successors",
            str(exc),
        ) from exc
    if transition_ref is not None and payload_transition_ref != transition_ref:
        raise CanonEchoError(
            "canon_successor_transition_ref_mismatch",
            "restore the successor bound to the prepared transition intent ref",
            envelope.message_id,
        )
    matches = []
    for event in replay.events:
        intent = event.payload.get("intent")
        if event.event_type != "sdlc.transition_applied" or not isinstance(intent, dict):
            continue
        candidate = f"transition-intent@sha256:{_content_hash(intent)}"
        if candidate == payload_transition_ref:
            matches.append(event)
    if len(matches) != 1:
        raise CanonEchoError(
            "canon_successor_applied_receipt_missing",
            "restore one exact applied transition receipt for the successor",
            str(payload_transition_ref),
        )
    event = matches[0]
    intent = event.payload.get("intent")
    if (
        event.event_type != "sdlc.transition_applied"
        or event.subject != predecessor.task_id
        or event.authority_case != predecessor.authority_case
        or event.payload.get("phase") != "applied"
        or not isinstance(intent, dict)
        or intent.get("task_id") != predecessor.task_id
        or intent.get("authority_case") != predecessor.authority_case
        or intent.get("from_stage") != predecessor.stage_token
        or intent.get("to_stage") != successor.stage_token
        or intent.get("predecessor_position_ref") != predecessor.position_ref
        or successor.stage_token not in predecessor.legal_successors
    ):
        raise CanonEchoError(
            "canon_successor_applied_receipt_mismatch",
            "restore the successor causally bound to the exact predecessor and legal edge",
            str(payload_transition_ref),
        )
    if (
        successor.task_id != predecessor.task_id
        or successor.lane != predecessor.lane
        or successor.authority_case != predecessor.authority_case
        or successor.canon_hash != predecessor.canon_hash
        or successor.canon_version != predecessor.canon_version
        or successor.canon_level != predecessor.canon_level
        or successor.constraint_state != predecessor.constraint_state
        or successor.constraint_digest_kind != predecessor.constraint_digest_kind
        or successor.constraint_digest != predecessor.constraint_digest
    ):
        raise CanonEchoError(
            "canon_successor_carry_forward_mismatch",
            "carry task, lane, authority, canon, and declared constraints unchanged",
            envelope.message_id,
        )
    if (outbox_path is None) != (outbox_payload is None):
        raise CanonEchoError(
            "canon_successor_outbox_projection_binding_missing",
            "bind both the durable outbox path and exact bytes to the applied receipt",
            envelope.message_id,
        )
    if outbox_path is not None and outbox_payload is not None:
        normalized_path = str(Path(os.path.abspath(outbox_path.expanduser())))
        expected_projection = {
            "after_mode": 0o600,
            "after_present": True,
            "after_sha256": hashlib.sha256(outbox_payload).hexdigest(),
            "before_mode": None,
            "before_present": False,
            "before_sha256": None,
            "path": normalized_path,
        }
        projections = event.payload.get("projections")
        if (
            not isinstance(projections, list)
            or sum(item == expected_projection for item in projections) != 1
        ):
            raise CanonEchoError(
                "canon_successor_outbox_projection_not_applied",
                "restore the applied receipt that commits this exact absent-to-durable outbox projection",
                normalized_path,
            )
    return event


def resolve_claim_bound_canon_position(
    binding: ClaimDispatchBinding,
    *,
    stage_token: str | None = None,
) -> ExpectedCanonEcho:
    """HOLD legacy claims until a typed applied-ownership migration is installed."""

    del stage_token
    return _require_claim_dispatch_root(binding)


def _repair_envelope(
    expected: ExpectedCanonEcho,
    *,
    rendered_payload: str,
    created_at: datetime,
) -> Envelope:
    observed_hash = compute_payload_hash(rendered_payload)
    if observed_hash != expected.canon_payload_sha256:
        raise CanonEchoError(
            "canon_echo_repair_payload_hash_mismatch",
            "rebuild the exact same-level payload committed by the dispatch binding",
        )
    body = {
        **expected.to_echo_body(),
        "canon_payload": rendered_payload,
        "canon_payload_sha256": observed_hash,
        "kind": "canon_position_echo_repair",
        "may_authorize": False,
        "repair_key": expected.repair_key,
        "schema": CANON_ECHO_REPAIR_SCHEMA,
    }
    payload = {**body, "repair_hash": _content_hash(body)}
    return Envelope(
        message_id=f"canon-echo-repair-{expected.repair_key[:32]}",
        sender="hapax-coordinator",
        message_type="advisory",
        priority=0,
        subject=f"canon echo repair: {expected.task_id}",
        authority_case=expected.authority_case,
        authority_item=expected.task_id,
        parent_message_id=expected.source_message_id,
        recipients_spec=expected.lane,
        payload=_canonical_json_bytes(payload).decode("ascii"),
        created_at=created_at,
        tags=[CANON_ECHO_REPAIR_TAG],
    )


def _matching_repair(
    children: list[Envelope], expected: ExpectedCanonEcho, *, rendered_payload: str
) -> Envelope | None:
    matches: list[Envelope] = []
    for envelope in children:
        if CANON_ECHO_REPAIR_TAG not in (envelope.tags or []):
            continue
        payload = _strict_json_object(
            _payload_text(envelope), reason_code="canon_echo_repair_payload_malformed"
        )
        body = {key: value for key, value in payload.items() if key != "repair_hash"}
        expected_envelope = _repair_envelope(
            expected,
            rendered_payload=rendered_payload,
            created_at=envelope.created_at,
        )
        if (
            set(payload)
            != {
                "binding",
                "canon",
                "canon_payload",
                "canon_payload_sha256",
                "constraint_mask",
                "kind",
                "lane",
                "may_authorize",
                "position",
                "repair_hash",
                "repair_key",
                "schema",
                "source_message_id",
            }
            or payload.get("schema") != CANON_ECHO_REPAIR_SCHEMA
            or payload.get("repair_key") != expected.repair_key
            or payload.get("source_message_id") != expected.source_message_id
            or payload.get("may_authorize") is not False
            or payload.get("repair_hash") != _content_hash(body)
            or envelope.model_dump(mode="json") != expected_envelope.model_dump(mode="json")
        ):
            raise CanonEchoError(
                "canon_echo_repair_binding_mismatch",
                "preserve the one exact repair bound to the current dispatch position",
                envelope.message_id,
            )
        matches.append(envelope)
    if len(matches) > 1:
        raise CanonEchoError(
            "canon_echo_repair_duplicate",
            "retain one deterministic repair message for the stable repair key",
            expected.repair_key,
        )
    return matches[0] if matches else None


def ensure_canon_echo_repair(
    db_path: Path,
    expected: ExpectedCanonEcho,
    *,
    rendered_payload: str,
    now: datetime | None = None,
) -> tuple[Envelope, bool]:
    del db_path, expected, rendered_payload, now
    raise CanonEchoError(
        "canon_echo_repair_materialization_held",
        "materialize the repair only through a current authority grant, admission decision, and execution lease",
    )


def reconcile_canon_echo(
    db_path: Path,
    expected: ExpectedCanonEcho,
    *,
    rendered_payload: str,
    now: datetime | None = None,
    expected_sender: str | None = None,
    expected_session_id: str | None = None,
) -> CanonEchoReconciliation:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        children = _child_envelopes(db_path, expected.source_message_id)
    except CanonEchoError as exc:
        return CanonEchoReconciliation("hold", exc.reason_code)
    repair = _matching_repair(children, expected, rendered_payload=rendered_payload)
    if repair is None:
        echoes: list[CanonPositionEcho] = []
        malformed_echo_ids: list[str] = []
        for envelope in children:
            if CANON_ECHO_TAG not in (envelope.tags or []):
                continue
            try:
                echo = parse_canon_echo(envelope)
                if echo.repair_message_id is None:
                    echoes.append(echo)
            except CanonEchoError:
                malformed_echo_ids.append(envelope.message_id)
        echoes.sort(key=lambda item: item.observed_at)
        assessment = (
            assess_canon_echo(
                expected,
                echoes[-1],
                now=current,
                expected_sender=expected_sender,
                expected_session_id=expected_session_id,
            )
            if len(echoes) == 1 and not malformed_echo_ids
            else None
        )
        if assessment is not None and assessment.status == "matched":
            return CanonEchoReconciliation(
                "grounded",
                "canon_echo_matched",
                echo_message_id=assessment.message_id,
            )
        return CanonEchoReconciliation(
            "hold",
            "canon_echo_repair_required",
            echo_message_id=(assessment.message_id if assessment else None)
            or (malformed_echo_ids[-1] if malformed_echo_ids else None),
        )
    responses = [
        envelope
        for envelope in _child_envelopes(db_path, repair.message_id)
        if CANON_ECHO_TAG in (envelope.tags or [])
    ]
    if len(responses) > 1:
        return CanonEchoReconciliation(
            "block",
            "canon_echo_failed",
            echo_message_id=responses[-1].message_id,
            repair_message_id=repair.message_id,
        )
    if responses:
        response = responses[0]
        try:
            echo = parse_canon_echo(response)
            if echo.repair_message_id != repair.message_id:
                raise CanonEchoError(
                    "canon_echo_repair_response_binding_mismatch",
                    "reply as a child of the exact deterministic repair",
                    response.message_id,
                )
            assessment = assess_canon_echo(
                expected,
                echo,
                now=current,
                expected_sender=expected_sender,
                expected_session_id=expected_session_id,
            )
        except CanonEchoError:
            assessment = None
        if assessment is not None and assessment.status == "matched":
            return CanonEchoReconciliation(
                "grounded",
                "canon_echo_matched_after_repair",
                echo_message_id=response.message_id,
                repair_message_id=repair.message_id,
            )
        return CanonEchoReconciliation(
            "block",
            "canon_echo_failed",
            echo_message_id=response.message_id,
            repair_message_id=repair.message_id,
        )
    assert repair.stale_after is not None
    if current > repair.stale_after.astimezone(UTC):
        return CanonEchoReconciliation(
            "block",
            "canon_echo_failed",
            repair_message_id=repair.message_id,
        )
    return CanonEchoReconciliation(
        "awaiting_repair",
        "canon_echo_repair_pending",
        repair_message_id=repair.message_id,
    )
