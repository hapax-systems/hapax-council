from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from shared.coord_event_log import CoordEvent, CoordEventLog, CoordWriter
from shared.relay_mq import (
    CANON_ECHO_REPAIR_TAG,
    CanonEchoError,
    MessageFilters,
    _connect,
    ack_message,
    assess_canon_echo,
    build_canon_echo_envelope,
    build_successor_canon_position,
    build_successor_outbox,
    consume_messages,
    dead_letters,
    drain_successor_outboxes,
    ensure_schema,
    expand_recipients,
    inspect_message,
    list_messages,
    load_dispatch_echo_expectation,
    load_latest_canon_echo_expectation,
    load_latest_dispatch_echo_expectation,
    parse_canon_echo,
    purge_expired,
    reconcile_canon_echo,
    resolve_claim_bound_canon_position,
    send_message,
    send_successor_canon_position,
    successor_outbox_task_directory,
)
from shared.relay_mq_envelope import (
    DiskPressureError,
    Envelope,
    TransitionError,
)
from shared.sdlc_task_store import ClaimDispatchBinding

DB = Path(":memory:")  # only for non-schema tests that use a single function call


def _canon_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _dispatch_record(source_message_id: str) -> dict:
    canon = {
        "canon_hash": "a" * 64,
        "canon_version": 1,
        "image_hash": "b" * 64,
        "level": "pi0",
        "payload_sha256": hashlib.sha256(b"exact canon payload").hexdigest(),
        "stage_token": "S6",
    }
    position_body = {
        "authority_case": "CASE-ECHO-001",
        "declared_task_constraint_digest": "c" * 64,
        "effective_constraint_state": "unresolved_scope_chain",
        "lane": "cx-red",
        "legal_successors": ["S7", "BLOCKED"],
        "stage_token": "S6",
        "task_id": "task-echo",
    }
    position_hash = _canon_hash(position_body)
    position = {
        **position_body,
        "position_hash": position_hash,
        "position_ref": f"dispatch-position@sha256:{position_hash}",
    }
    binding_body = {
        "advisory_carriage": True,
        "canon": canon,
        "may_authorize": False,
        "position": position,
        "receipt_is_admission": False,
        "schema": "hapax.dispatch-canon-binding.v1",
    }
    binding_hash = _canon_hash(binding_body)
    binding = {
        **binding_body,
        "binding_hash": binding_hash,
        "binding_ref": f"dispatch-canon-binding@sha256:{binding_hash}",
    }
    return {
        "event": "methodology_dispatch",
        "ok": True,
        "launched": True,
        "launch_returncode": 0,
        "launch_eligible": True,
        "durable_mq_dispatch_bound": True,
        "durable_mq_message_id": source_message_id,
        "may_authorize": False,
        "receipt_is_admission": False,
        "canon_binding": binding,
        "canon_binding_hash": binding_hash,
        "canon_binding_ref": binding["binding_ref"],
        "dispatch_position_hash": position_hash,
        "dispatch_position_ref": position["position_ref"],
    }


def _make_envelope(**overrides) -> Envelope:
    defaults: dict = {
        "sender": "test",
        "message_type": "advisory",
        "subject": "test message",
        "recipients_spec": "alpha",
        "payload": "test payload",
    }
    defaults.update(overrides)
    return Envelope(**defaults)


def _make_relay_dir(tmp_path: Path, peers: list[str]) -> Path:
    for peer in peers:
        (tmp_path / f"{peer}.yaml").touch()
    return tmp_path


class TestSchema(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_ensure_schema_creates_tables(self) -> None:
        ensure_schema(self.db_path)
        with _connect(self.db_path) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        self.assertIn("messages", tables)
        self.assertIn("recipients", tables)
        self.assertIn("dead_letters", tables)

    def test_ensure_schema_idempotent(self) -> None:
        ensure_schema(self.db_path)
        ensure_schema(self.db_path)

    def test_wal_mode_active(self) -> None:
        with _connect(self.db_path) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            self.assertIn(mode, ("wal", "memory"))

    def test_foreign_keys_on(self) -> None:
        with _connect(self.db_path) as conn:
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            self.assertEqual(fk, 1)

    def test_dispatch_check_constraint(self) -> None:
        ensure_schema(self.db_path)
        with _connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO messages "
                    "(message_id, sender, message_type, priority, subject, "
                    "recipients_spec, payload, payload_hash, created_at) "
                    "VALUES ('test-1', 'x', 'dispatch', 2, 's', 'a', 'p', 'h', '2026-01-01')"
                )

    def test_payload_check_constraint(self) -> None:
        ensure_schema(self.db_path)
        with _connect(self.db_path) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO messages "
                    "(message_id, sender, message_type, priority, subject, "
                    "recipients_spec, payload, payload_path, payload_hash, created_at) "
                    "VALUES ('test-2', 'x', 'advisory', 2, 's', 'a', 'p', '/path', 'h', '2026-01-01')"
                )


class TestSend(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_send_advisory_roundtrip(self) -> None:
        env = _make_envelope()
        mid = send_message(self.db_path, env)
        self.assertEqual(mid, env.message_id)

        with _connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM messages WHERE message_id = ?", (mid,)).fetchone()
        self.assertIsNotNone(row)

    def test_send_creates_recipient_rows(self) -> None:
        env = _make_envelope(recipients_spec="alpha,gamma")
        mid = send_message(self.db_path, env)

        with _connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM recipients WHERE message_id = ?", (mid,)).fetchall()
        self.assertEqual(len(rows), 2)
        recipients = {r["recipient"] for r in rows}
        self.assertEqual(recipients, {"alpha", "gamma"})
        for r in rows:
            self.assertEqual(r["state"], "offered")

    def test_send_broadcast_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(Path(td), ["alpha", "beta", "gamma", "delta"])
            env = _make_envelope(recipients_spec="*:all")
            mid = send_message(self.db_path, env, relay_dir=relay_dir)

            with _connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM recipients WHERE message_id = ?", (mid,)
                ).fetchall()
            self.assertEqual(len(rows), 4)

    def test_send_dispatch_with_authority(self) -> None:
        env = _make_envelope(
            message_type="dispatch",
            authority_case="CASE-001",
        )
        mid = send_message(self.db_path, env)
        self.assertIsNotNone(mid)

    def test_send_dispatch_without_authority_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _make_envelope(message_type="dispatch")

    def test_send_duplicate_message_id_rejected(self) -> None:
        env = _make_envelope()
        send_message(self.db_path, env)
        env2 = _make_envelope(message_id=env.message_id)
        with self.assertRaises(sqlite3.IntegrityError):
            send_message(self.db_path, env2)

    def test_send_large_payload_to_blob(self) -> None:
        large = "x" * (51 * 1024)
        env = _make_envelope(payload=large)
        with patch("shared.relay_mq.BLOB_DIR", Path(self._tmp.name) / "blobs"):
            mid = send_message(self.db_path, env)
            with _connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT payload, payload_path FROM messages WHERE message_id = ?",
                    (mid,),
                ).fetchone()
            self.assertIsNone(row["payload"])
            self.assertIsNotNone(row["payload_path"])

    def test_send_disk_pressure_rejected(self) -> None:
        mock_usage = type("Usage", (), {"free": 1024})()
        env = _make_envelope()
        with patch("shutil.disk_usage", return_value=mock_usage):
            with self.assertRaises(DiskPressureError):
                send_message(self.db_path, env)


class TestConsume(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_consume_returns_pending_messages(self) -> None:
        env = _make_envelope(recipients_spec="alpha")
        send_message(self.db_path, env)
        msgs = consume_messages(self.db_path, "alpha")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].envelope.message_id, env.message_id)

    def test_consume_transitions_offered_to_read(self) -> None:
        env = _make_envelope(recipients_spec="alpha")
        send_message(self.db_path, env)
        consume_messages(self.db_path, "alpha")

        with _connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT state FROM recipients WHERE message_id = ? AND recipient = 'alpha'",
                (env.message_id,),
            ).fetchone()
        self.assertEqual(row["state"], "read")

    def test_consume_respects_limit(self) -> None:
        for _ in range(10):
            send_message(self.db_path, _make_envelope(recipients_spec="alpha"))
        msgs = consume_messages(self.db_path, "alpha", limit=3)
        self.assertEqual(len(msgs), 3)

    def test_consume_skips_already_read(self) -> None:
        env = _make_envelope(recipients_spec="alpha")
        send_message(self.db_path, env)
        consume_messages(self.db_path, "alpha")
        msgs = consume_messages(self.db_path, "alpha")
        self.assertEqual(len(msgs), 0)

    def test_consume_causal_ordering(self) -> None:
        parent = _make_envelope(recipients_spec="alpha")
        send_message(self.db_path, parent)

        child = _make_envelope(
            recipients_spec="alpha",
            parent_message_id=parent.message_id,
        )
        send_message(self.db_path, child)

        msgs = consume_messages(self.db_path, "alpha")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].envelope.message_id, parent.message_id)

        msgs2 = consume_messages(self.db_path, "alpha")
        self.assertEqual(len(msgs2), 1)
        self.assertEqual(msgs2[0].envelope.message_id, child.message_id)

    def test_consume_expired_message_dead_lettered(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=2)
        env = _make_envelope(
            recipients_spec="alpha",
            created_at=past,
            expires_at=past + timedelta(minutes=5),
            stale_after=past + timedelta(minutes=1),
        )
        send_message(self.db_path, env)
        msgs = consume_messages(self.db_path, "alpha")
        self.assertEqual(len(msgs), 0)

        dls = dead_letters(self.db_path)
        self.assertEqual(len(dls), 1)
        self.assertEqual(dls[0]["reason"], "expired")

    def test_consume_stale_message_included_with_flag(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=2)
        env = _make_envelope(
            recipients_spec="alpha",
            created_at=past,
            stale_after=past + timedelta(minutes=1),
            expires_at=past + timedelta(days=3),
        )
        send_message(self.db_path, env)
        msgs = consume_messages(self.db_path, "alpha")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].freshness, "stale")

    def test_consume_fresh_message(self) -> None:
        env = _make_envelope(recipients_spec="alpha")
        send_message(self.db_path, env)
        msgs = consume_messages(self.db_path, "alpha")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].freshness, "fresh")

    def test_consume_wrong_recipient_returns_empty(self) -> None:
        env = _make_envelope(recipients_spec="alpha")
        send_message(self.db_path, env)
        msgs = consume_messages(self.db_path, "gamma")
        self.assertEqual(len(msgs), 0)

    def test_consume_empty_database(self) -> None:
        msgs = consume_messages(self.db_path, "alpha")
        self.assertEqual(len(msgs), 0)


class TestAck(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _send_and_consume(self) -> str:
        env = _make_envelope(recipients_spec="alpha")
        send_message(self.db_path, env)
        consume_messages(self.db_path, "alpha")
        return env.message_id

    def test_ack_read_to_accepted(self) -> None:
        mid = self._send_and_consume()
        ok = ack_message(self.db_path, mid, "alpha", "accepted")
        self.assertTrue(ok)

    def test_ack_accepted_to_processed(self) -> None:
        mid = self._send_and_consume()
        ack_message(self.db_path, mid, "alpha", "accepted")
        ok = ack_message(self.db_path, mid, "alpha", "processed")
        self.assertTrue(ok)

    def test_ack_accepted_to_deferred_with_reason(self) -> None:
        mid = self._send_and_consume()
        ack_message(self.db_path, mid, "alpha", "accepted")
        ok = ack_message(self.db_path, mid, "alpha", "deferred", reason="blocked")
        self.assertTrue(ok)

    def test_ack_processed_to_anything_rejected(self) -> None:
        mid = self._send_and_consume()
        ack_message(self.db_path, mid, "alpha", "accepted")
        ack_message(self.db_path, mid, "alpha", "processed")
        with self.assertRaises(TransitionError):
            ack_message(self.db_path, mid, "alpha", "accepted")

    def test_ack_escalated_to_anything_rejected(self) -> None:
        mid = self._send_and_consume()
        ack_message(self.db_path, mid, "alpha", "escalated", reason="urgent")
        with self.assertRaises(TransitionError):
            ack_message(self.db_path, mid, "alpha", "accepted")

    def test_ack_offered_to_accepted_rejected(self) -> None:
        env = _make_envelope(recipients_spec="alpha")
        send_message(self.db_path, env)
        with self.assertRaises(TransitionError):
            ack_message(self.db_path, env.message_id, "alpha", "accepted")

    def test_ack_nonexistent_message_rejected(self) -> None:
        ensure_schema(self.db_path)
        ok = ack_message(self.db_path, "nonexistent-id", "alpha", "accepted")
        self.assertFalse(ok)


class TestList(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_list_no_filters(self) -> None:
        for _i in range(3):
            send_message(self.db_path, _make_envelope(recipients_spec="alpha"))
        rows = list_messages(self.db_path, MessageFilters())
        self.assertEqual(len(rows), 3)

    def test_list_filter_by_recipient(self) -> None:
        send_message(self.db_path, _make_envelope(recipients_spec="alpha"))
        send_message(self.db_path, _make_envelope(recipients_spec="gamma"))
        rows = list_messages(self.db_path, MessageFilters(recipient="alpha"))
        self.assertEqual(len(rows), 1)

    def test_list_filter_by_state(self) -> None:
        send_message(self.db_path, _make_envelope(recipients_spec="alpha"))
        send_message(self.db_path, _make_envelope(recipients_spec="alpha"))
        consume_messages(self.db_path, "alpha", limit=1)
        rows = list_messages(self.db_path, MessageFilters(recipient="alpha", state="offered"))
        self.assertEqual(len(rows), 1)

    def test_list_filter_by_priority(self) -> None:
        send_message(self.db_path, _make_envelope(priority=0, recipients_spec="alpha"))
        send_message(self.db_path, _make_envelope(priority=2, recipients_spec="alpha"))
        rows = list_messages(self.db_path, MessageFilters(priority=0))
        self.assertEqual(len(rows), 1)

    def test_list_filter_by_type(self) -> None:
        send_message(
            self.db_path,
            _make_envelope(message_type="escalation", recipients_spec="alpha"),
        )
        send_message(self.db_path, _make_envelope(recipients_spec="alpha"))
        rows = list_messages(self.db_path, MessageFilters(message_type="escalation"))
        self.assertEqual(len(rows), 1)

    def test_list_filter_by_authority_case(self) -> None:
        send_message(
            self.db_path,
            _make_envelope(
                message_type="dispatch",
                authority_case="CASE-X",
                recipients_spec="alpha",
            ),
        )
        send_message(self.db_path, _make_envelope(recipients_spec="alpha"))
        rows = list_messages(self.db_path, MessageFilters(authority_case="CASE-X"))
        self.assertEqual(len(rows), 1)

    def test_list_respects_limit(self) -> None:
        for _ in range(10):
            send_message(self.db_path, _make_envelope(recipients_spec="alpha"))
        rows = list_messages(self.db_path, MessageFilters(limit=3))
        self.assertEqual(len(rows), 3)


class TestInspect(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_inspect_returns_full_message(self) -> None:
        env = _make_envelope(recipients_spec="alpha,gamma")
        send_message(self.db_path, env)
        result = inspect_message(self.db_path, env.message_id)
        self.assertIsNotNone(result)
        self.assertEqual(result.envelope.message_id, env.message_id)
        self.assertEqual(len(result.recipients), 2)

    def test_inspect_includes_dead_letters(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=2)
        env = _make_envelope(
            recipients_spec="alpha",
            created_at=past,
            expires_at=past + timedelta(minutes=5),
            stale_after=past + timedelta(minutes=1),
        )
        send_message(self.db_path, env)
        consume_messages(self.db_path, "alpha")

        result = inspect_message(self.db_path, env.message_id)
        self.assertIsNotNone(result)
        self.assertGreater(len(result.dead_letters), 0)

    def test_inspect_nonexistent_returns_none(self) -> None:
        ensure_schema(self.db_path)
        result = inspect_message(self.db_path, "nonexistent")
        self.assertIsNone(result)


class TestDeadLetters(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_dead_letters_empty(self) -> None:
        result = dead_letters(self.db_path)
        self.assertEqual(len(result), 0)

    def test_dead_letters_after_expiry(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=2)
        env = _make_envelope(
            recipients_spec="alpha",
            created_at=past,
            expires_at=past + timedelta(minutes=5),
            stale_after=past + timedelta(minutes=1),
        )
        send_message(self.db_path, env)
        consume_messages(self.db_path, "alpha")
        result = dead_letters(self.db_path)
        self.assertEqual(len(result), 1)

    def test_dead_letters_since_filter(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=2)
        env = _make_envelope(
            recipients_spec="alpha",
            created_at=past,
            expires_at=past + timedelta(minutes=5),
            stale_after=past + timedelta(minutes=1),
        )
        send_message(self.db_path, env)
        consume_messages(self.db_path, "alpha")

        future = datetime.now(UTC) + timedelta(hours=1)
        result = dead_letters(self.db_path, since=future)
        self.assertEqual(len(result), 0)


class TestPurge(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test.db"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_purge_expired_recipients(self) -> None:
        past = datetime.now(UTC) - timedelta(hours=2)
        env = _make_envelope(
            recipients_spec="alpha",
            created_at=past,
            expires_at=past + timedelta(minutes=5),
            stale_after=past + timedelta(minutes=1),
        )
        send_message(self.db_path, env)
        result = purge_expired(self.db_path)
        self.assertEqual(result.expired_dead_lettered, 1)

    def test_purge_blob_cleanup(self) -> None:
        blob_dir = Path(self._tmp.name) / "blobs"
        blob_dir.mkdir()
        blob_file = blob_dir / "test-blob"
        blob_file.write_text("data")

        past = datetime.now(UTC) - timedelta(days=10)
        env = _make_envelope(
            recipients_spec="alpha",
            payload=None,
            payload_path=str(blob_file),
            payload_hash="abc123",
            created_at=past,
            expires_at=past + timedelta(hours=1),
            stale_after=past + timedelta(minutes=10),
        )
        send_message(self.db_path, env)
        consume_messages(self.db_path, "alpha")
        ack_message(self.db_path, env.message_id, "alpha", "accepted")
        ack_message(self.db_path, env.message_id, "alpha", "processed")

        result = purge_expired(self.db_path)
        self.assertEqual(result.blobs_deleted, 1)
        self.assertFalse(blob_file.exists())

    def test_purge_preserves_active_messages(self) -> None:
        env = _make_envelope(recipients_spec="alpha")
        send_message(self.db_path, env)
        result = purge_expired(self.db_path)
        self.assertEqual(result.expired_dead_lettered, 0)

        with _connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM recipients WHERE message_id = ?",
                (env.message_id,),
            ).fetchone()
        self.assertIsNotNone(row)


class TestCanonEcho(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "messages.db"
        self.source_message_id = "dispatch-echo-source"
        self.parent = Envelope(
            message_id=self.source_message_id,
            sender="hapax-coordinator",
            message_type="dispatch",
            priority=0,
            subject="task-echo",
            authority_case="CASE-ECHO-001",
            authority_item="task-echo",
            recipients_spec="cx-red",
            payload='{"task_id":"task-echo"}',
        )
        send_message(self.db_path, self.parent)
        self.ledger = self.root / "methodology-dispatch.jsonl"
        self.ledger.write_text(
            json.dumps(_dispatch_record(self.source_message_id), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.expected = load_dispatch_echo_expectation(
            self.ledger,
            source_message_id=self.source_message_id,
            task_id="task-echo",
            lane="cx-red",
        )
        self.now = datetime(2026, 7, 11, 15, 0, tzinfo=UTC)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _tampered_echo(
        self, *, observed_at: datetime, repair_message_id: str | None = None
    ) -> Envelope:
        valid = build_canon_echo_envelope(
            self.expected,
            sender="cx-red",
            session_id="session-1",
            observed_at=observed_at,
            repair_message_id=repair_message_id,
        )
        payload = json.loads(valid.payload or "{}")
        payload["position"]["task_id"] = "copied-from-another-task"
        body = {key: value for key, value in payload.items() if key != "echo_hash"}
        payload["echo_hash"] = _canon_hash(body)
        return Envelope(
            sender=valid.sender,
            message_type=valid.message_type,
            priority=valid.priority,
            subject=valid.subject,
            authority_case=valid.authority_case,
            authority_item=valid.authority_item,
            parent_message_id=valid.parent_message_id,
            recipients_spec=valid.recipients_spec,
            payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            created_at=observed_at,
            stale_after=valid.stale_after,
            tags=valid.tags,
        )

    def test_dispatch_receipt_derives_exact_honest_expectation(self) -> None:
        self.assertEqual(self.expected.task_id, "task-echo")
        self.assertEqual(self.expected.stage_token, "S6")
        self.assertEqual(self.expected.legal_successors, ("S7", "BLOCKED"))
        self.assertEqual(self.expected.constraint_state, "unresolved_scope_chain")
        self.assertEqual(
            self.expected.constraint_digest_kind,
            "declared_task_constraint_digest",
        )
        self.assertEqual(
            load_latest_dispatch_echo_expectation(
                self.ledger,
                task_id="task-echo",
                lane="cx-red",
            ),
            self.expected,
        )

    def test_legacy_dispatch_chain_cannot_authorize_claim_currentness(self) -> None:
        binding = ClaimDispatchBinding.create(
            task_id="task-echo",
            lane="cx-red",
            session_id="session-1",
            claim_epoch=1,
            dispatch_message_id=self.source_message_id,
            platform="codex",
            mode="headless",
            profile="full",
            authority_case="CASE-ECHO-001",
            binding_hash=self.expected.binding_hash,
        )

        with self.assertRaises(CanonEchoError) as raised:
            resolve_claim_bound_canon_position(
                binding,
                stage_token="S6",
            )

        self.assertEqual(
            raised.exception.reason_code,
            "canon_pre_gate0_claim_migration_required",
        )

    def test_echo_roundtrip_matches_mechanically(self) -> None:
        envelope = build_canon_echo_envelope(
            self.expected,
            sender="cx-red",
            session_id="session-1",
            observed_at=self.now,
        )
        echo = parse_canon_echo(envelope)
        assessment = assess_canon_echo(
            self.expected,
            echo,
            now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(assessment.status, "matched")
        self.assertEqual(assessment.reason_codes, ())

    def test_echo_duplicate_json_key_is_refused(self) -> None:
        envelope = build_canon_echo_envelope(
            self.expected,
            sender="cx-red",
            session_id="session-1",
            observed_at=self.now,
        )
        malformed = Envelope(
            sender=envelope.sender,
            message_type="advisory",
            priority=0,
            subject=envelope.subject,
            authority_case=envelope.authority_case,
            parent_message_id=envelope.parent_message_id,
            recipients_spec=envelope.recipients_spec,
            payload='{"schema":"x","schema":"y"}',
            created_at=self.now,
            tags=envelope.tags,
        )
        with self.assertRaisesRegex(CanonEchoError, "canon_echo_payload_malformed"):
            parse_canon_echo(malformed)

    def test_absence_holds_without_publishing_a_repair(self) -> None:
        before = _tree_bytes(self.root)

        result = reconcile_canon_echo(
            self.db_path,
            self.expected,
            rendered_payload="exact canon payload",
            now=self.now,
        )

        self.assertEqual(result.action, "hold")
        self.assertEqual(result.reason_code, "canon_echo_projection_required")
        self.assertEqual(_tree_bytes(self.root), before)

    def test_absent_database_holds_without_creating_a_database(self) -> None:
        absent_root = self.root / "absent-relay"
        absent_db = absent_root / "messages.db"
        before = _tree_bytes(self.root)

        result = reconcile_canon_echo(
            absent_db,
            self.expected,
            rendered_payload="exact canon payload",
            now=self.now,
        )

        self.assertEqual(result.action, "hold")
        self.assertEqual(result.reason_code, "canon_echo_repair_required")
        self.assertEqual(_tree_bytes(self.root), before)
        self.assertFalse(absent_root.exists())

    def test_observation_preserves_database_and_existing_sidecar_bytes(self) -> None:
        writer = _connect(self.db_path)
        try:
            writer.execute("SELECT 1").fetchone()
            sidecars = [Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")]
            self.assertTrue(all(path.exists() for path in sidecars))
            before = _tree_bytes(self.root)

            result = reconcile_canon_echo(
                self.db_path,
                self.expected,
                rendered_payload="exact canon payload",
                now=self.now,
            )

            self.assertEqual(result.action, "hold")
            self.assertEqual(result.reason_code, "canon_echo_projection_required")
            self.assertEqual(_tree_bytes(self.root), before)
        finally:
            writer.close()

    def test_live_database_echo_cannot_ground_without_current_projection(self) -> None:

        echo = build_canon_echo_envelope(
            self.expected,
            sender="cx-red",
            session_id="session-1",
            observed_at=self.now + timedelta(seconds=2),
        )
        send_message(self.db_path, echo)
        before = _tree_bytes(self.root)
        held = reconcile_canon_echo(
            self.db_path,
            self.expected,
            rendered_payload="exact canon payload",
            now=self.now + timedelta(seconds=3),
        )
        self.assertEqual(held.action, "hold")
        self.assertEqual(held.reason_code, "canon_echo_projection_required")
        self.assertEqual(_tree_bytes(self.root), before)

        rows = list_messages(self.db_path, MessageFilters(limit=20))
        repairs = [
            row for row in rows if row["tags"] and CANON_ECHO_REPAIR_TAG in json.loads(row["tags"])
        ]
        self.assertEqual(len(repairs), 0)

    def test_direct_send_and_global_latest_successor_apis_are_retired(self) -> None:
        with self.assertRaises(CanonEchoError) as direct:
            send_successor_canon_position(
                self.db_path,
                self.expected,
                transition_id="sdlc-txn-test",
                stage_token="S7",
                legal_successors=("S8", "BLOCKED"),
                canon_hash=self.expected.canon_hash,
                canon_version=1,
                canon_image_hash="d" * 64,
                canon_level="pi0",
                rendered_payload="successor canon payload",
                now=self.now,
            )
        self.assertEqual(direct.exception.reason_code, "canon_successor_direct_send_retired")
        with self.assertRaises(CanonEchoError) as latest:
            load_latest_canon_echo_expectation(
                task_id="task-echo",
                lane="cx-red",
                stage_token="S7",
            )
        self.assertEqual(latest.exception.reason_code, "canon_global_latest_position_retired")

    def _successor_outbox_fixture(self) -> tuple[CoordEventLog, object, Path]:
        intent = {
            "authority_case": self.expected.authority_case,
            "from_stage": self.expected.stage_token,
            "predecessor_position_ref": self.expected.position_ref,
            "task_id": self.expected.task_id,
            "to_stage": "S7",
        }
        transition_ref = f"transition-intent@sha256:{_canon_hash(intent)}"
        successor, envelope = build_successor_canon_position(
            self.expected,
            transition_id=transition_ref,
            stage_token="S7",
            legal_successors=("S8", "BLOCKED"),
            canon_hash=self.expected.canon_hash,
            canon_version=self.expected.canon_version,
            canon_image_hash="d" * 64,
            canon_level=self.expected.canon_level,
            rendered_payload="successor canon payload",
            now=self.now,
        )
        outbox = build_successor_outbox(
            self.expected,
            successor,
            envelope,
            transition_ref=transition_ref,
        )
        outbox_dir = successor_outbox_task_directory(
            self.root / "outbox",
            self.expected.task_id,
        )
        outbox_dir.mkdir(parents=True)
        path = outbox_dir / f"{outbox.action_id}.json"
        event_log = CoordEventLog(
            db_path=self.root / "coord" / "ledger.db",
            jsonl_path=self.root / "coord" / "ledger.jsonl",
            spool_dir=self.root / "coord" / "spool",
        )
        event_log.append(
            CoordEvent(
                event_id="transition-applied-test",
                timestamp=str(self.now),
                event_type="sdlc.transition_applied",
                actor="test",
                subject=self.expected.task_id,
                authority_case=self.expected.authority_case,
                payload={
                    "intent": intent,
                    "phase": "applied",
                    "projections": [
                        {
                            "after_mode": 0o600,
                            "after_present": True,
                            "after_sha256": hashlib.sha256(outbox.payload).hexdigest(),
                            "before_mode": None,
                            "before_present": False,
                            "before_sha256": None,
                            "path": str(path),
                        }
                    ],
                },
            ),
            writer=CoordWriter.daemon("test"),
        )
        path.write_bytes(outbox.payload)
        return event_log, outbox, outbox_dir

    def test_successor_outbox_drain_is_applied_only_and_idempotent(self) -> None:
        event_log, outbox, outbox_dir = self._successor_outbox_fixture()

        first = drain_successor_outboxes(
            self.db_path,
            event_log,
            outbox_dir,
            task_id=self.expected.task_id,
        )
        second = drain_successor_outboxes(
            self.db_path,
            event_log,
            outbox_dir,
            task_id=self.expected.task_id,
        )

        self.assertEqual(first, (outbox.action_id,))
        self.assertEqual(second, (outbox.action_id,))
        self.assertIsNotNone(inspect_message(self.db_path, outbox.envelope.message_id))
        delivery_ids = [
            event.event_id
            for event in event_log.replay(fail_open=False).events
            if event.event_type == "sdlc.transition_outbox_delivered"
        ]
        self.assertEqual(delivery_ids, [f"{outbox.action_id}.delivered"])
        self.assertTrue((outbox_dir / f"{outbox.action_id}.json").is_file())

    def test_successor_delivery_recovers_message_commit_before_receipt(self) -> None:
        event_log, outbox, outbox_dir = self._successor_outbox_fixture()
        send_message(self.db_path, outbox.envelope)

        delivered = drain_successor_outboxes(self.db_path, event_log, outbox_dir)

        self.assertEqual(delivered, (outbox.action_id,))
        receipts = [
            event
            for event in event_log.replay(fail_open=False).events
            if event.event_type == "sdlc.transition_outbox_delivered"
        ]
        self.assertEqual(len(receipts), 1)

    def test_successor_delivery_accepts_processed_or_exact_expired_lineage(self) -> None:
        event_log, outbox, outbox_dir = self._successor_outbox_fixture()
        drain_successor_outboxes(self.db_path, event_log, outbox_dir)
        with _connect(self.db_path) as conn:
            conn.execute(
                "UPDATE recipients SET state = 'processed' WHERE message_id = ?",
                (outbox.envelope.message_id,),
            )
            conn.commit()
        self.assertEqual(
            drain_successor_outboxes(self.db_path, event_log, outbox_dir),
            (outbox.action_id,),
        )

        assert outbox.envelope.expires_at is not None
        moved_at = (outbox.envelope.expires_at + timedelta(seconds=1)).isoformat()
        with _connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM recipients WHERE message_id = ?", (outbox.envelope.message_id,)
            )
            conn.execute(
                "INSERT INTO dead_letters "
                "(message_id, recipient, reason, original_state, retry_count, moved_at) "
                "VALUES (?, ?, 'expired', 'offered', 0, ?)",
                (outbox.envelope.message_id, self.expected.lane, moved_at),
            )
            conn.commit()
        self.assertEqual(
            drain_successor_outboxes(self.db_path, event_log, outbox_dir),
            (outbox.action_id,),
        )

    def test_successor_delivery_refuses_missing_or_ambiguous_lineage(self) -> None:
        event_log, outbox, outbox_dir = self._successor_outbox_fixture()
        drain_successor_outboxes(self.db_path, event_log, outbox_dir)
        with _connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM recipients WHERE message_id = ?", (outbox.envelope.message_id,)
            )
            conn.execute("DELETE FROM messages WHERE message_id = ?", (outbox.envelope.message_id,))
            conn.commit()
        with self.assertRaises(CanonEchoError) as missing:
            drain_successor_outboxes(self.db_path, event_log, outbox_dir)
        self.assertEqual(missing.exception.reason_code, "canon_successor_delivery_lineage_missing")

        send_message(self.db_path, outbox.envelope)
        with _connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM recipients WHERE message_id = ?", (outbox.envelope.message_id,)
            )
            for offset in (1, 2):
                assert outbox.envelope.expires_at is not None
                conn.execute(
                    "INSERT INTO dead_letters "
                    "(message_id, recipient, reason, original_state, retry_count, moved_at) "
                    "VALUES (?, ?, 'expired', 'offered', 0, ?)",
                    (
                        outbox.envelope.message_id,
                        self.expected.lane,
                        (outbox.envelope.expires_at + timedelta(seconds=offset)).isoformat(),
                    ),
                )
            conn.commit()
        with self.assertRaises(CanonEchoError) as duplicate:
            drain_successor_outboxes(self.db_path, event_log, outbox_dir)
        self.assertEqual(
            duplicate.exception.reason_code, "canon_successor_delivery_lineage_mismatch"
        )

    def test_successor_outbox_refuses_without_applied_receipt(self) -> None:
        event_log, outbox, outbox_dir = self._successor_outbox_fixture()
        empty_log = CoordEventLog(
            db_path=self.root / "empty" / "ledger.db",
            jsonl_path=self.root / "empty" / "ledger.jsonl",
            spool_dir=self.root / "empty" / "spool",
        )

        with self.assertRaises(CanonEchoError) as raised:
            drain_successor_outboxes(self.db_path, empty_log, outbox_dir)

        self.assertEqual(raised.exception.reason_code, "canon_successor_applied_receipt_missing")
        self.assertIsNone(inspect_message(self.db_path, outbox.envelope.message_id))
        self.assertEqual(
            event_log.replay(fail_open=False).events[-1].event_id, "transition-applied-test"
        )

    def test_same_intent_without_exact_outbox_projection_cannot_deliver(self) -> None:
        event_log, outbox, outbox_dir = self._successor_outbox_fixture()
        applied = event_log.replay(fail_open=False).events[-1]
        wrong_log = CoordEventLog(
            db_path=self.root / "wrong" / "ledger.db",
            jsonl_path=self.root / "wrong" / "ledger.jsonl",
            spool_dir=self.root / "wrong" / "spool",
        )
        wrong_log.append(
            CoordEvent(
                event_id="same-intent-wrong-projection",
                timestamp=applied.timestamp,
                event_type="sdlc.transition_applied",
                actor=applied.actor,
                subject=applied.subject,
                authority_case=applied.authority_case,
                payload={**applied.payload, "projections": []},
            ),
            writer=CoordWriter.daemon("test"),
        )

        with self.assertRaises(CanonEchoError) as raised:
            drain_successor_outboxes(self.db_path, wrong_log, outbox_dir)

        self.assertEqual(
            raised.exception.reason_code,
            "canon_successor_outbox_projection_not_applied",
        )
        self.assertIsNone(inspect_message(self.db_path, outbox.envelope.message_id))

    def test_successor_outbox_task_filter_does_not_deliver_other_task(self) -> None:
        event_log, outbox, outbox_dir = self._successor_outbox_fixture()

        delivered = drain_successor_outboxes(
            self.db_path,
            event_log,
            outbox_dir,
            task_id="different-task",
        )

        self.assertEqual(delivered, ())
        self.assertIsNone(inspect_message(self.db_path, outbox.envelope.message_id))

    def test_successor_outbox_refuses_filename_mismatch_and_symlink(self) -> None:
        event_log, outbox, outbox_dir = self._successor_outbox_fixture()
        exact_path = outbox_dir / f"{outbox.action_id}.json"
        wrong_path = outbox_dir / "canon-successor-outbox-wrong.json"
        exact_path.rename(wrong_path)
        with self.assertRaises(CanonEchoError) as wrong_name:
            drain_successor_outboxes(self.db_path, event_log, outbox_dir)
        self.assertEqual(
            wrong_name.exception.reason_code, "canon_successor_outbox_filename_mismatch"
        )

        wrong_path.unlink()
        outside = self.root / "outside.json"
        outside.write_bytes(outbox.payload)
        exact_path.symlink_to(outside)
        with self.assertRaises(CanonEchoError) as symlink:
            drain_successor_outboxes(self.db_path, event_log, outbox_dir)
        self.assertEqual(symlink.exception.reason_code, "canon_successor_outbox_unreadable")

    def test_successor_outbox_refuses_noncanonical_equivalent_bytes(self) -> None:
        event_log, outbox, outbox_dir = self._successor_outbox_fixture()
        path = outbox_dir / f"{outbox.action_id}.json"
        path.write_bytes(outbox.payload + b"\n")

        with self.assertRaises(CanonEchoError) as raised:
            drain_successor_outboxes(self.db_path, event_log, outbox_dir)

        self.assertEqual(raised.exception.reason_code, "canon_successor_outbox_not_canonical")

    def test_task_partition_isolates_unrelated_corrupt_outbox(self) -> None:
        event_log, outbox, outbox_dir = self._successor_outbox_fixture()
        other = successor_outbox_task_directory(self.root / "outbox", "other-task")
        other.mkdir()
        (other / "canon-successor-outbox-corrupt.json").write_text("not json\n")

        delivered = drain_successor_outboxes(
            self.db_path,
            event_log,
            outbox_dir,
            task_id=self.expected.task_id,
        )

        self.assertEqual(delivered, (outbox.action_id,))

    def test_successor_outbox_refuses_symlinked_directory_ancestor(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        linked_root = self.root / "linked-root"
        linked_root.symlink_to(outside, target_is_directory=True)

        with self.assertRaises(CanonEchoError) as raised:
            drain_successor_outboxes(
                self.db_path,
                CoordEventLog(
                    db_path=self.root / "coord" / "unused.db",
                    jsonl_path=self.root / "coord" / "unused.jsonl",
                    spool_dir=self.root / "coord" / "unused-spool",
                ),
                linked_root / "task-partition",
            )

        self.assertEqual(raised.exception.reason_code, "canon_successor_outbox_directory_unsafe")


class TestRecipientExpansion(unittest.TestCase):
    def test_expand_direct_single(self) -> None:
        result = expand_recipients("alpha")
        self.assertEqual(result, ["alpha"])

    def test_expand_direct_multi(self) -> None:
        result = expand_recipients("alpha,gamma,cx-red")
        self.assertEqual(sorted(result), ["alpha", "cx-red", "gamma"])

    def test_expand_broadcast_all(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(
                Path(td),
                ["alpha", "beta", "gamma", "delta", "antigrav", "agy", "gemini-cli"],
            )
            result = expand_recipients("*:all", relay_dir)
            self.assertEqual(len(result), 4)
            self.assertNotIn("antigrav", result)
            self.assertNotIn("agy", result)
            self.assertNotIn("gemini-cli", result)

    def test_expand_broadcast_all_filters_mixed_case_retired_peers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(
                Path(td),
                ["alpha", "Antigrav", "AGY", "Gemini-CLI", "Gemini-CLI-2"],
            )
            result = expand_recipients("*:all", relay_dir)
            self.assertEqual(result, ["alpha"])

    def test_expand_broadcast_coordinators(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(Path(td), ["alpha", "beta", "rte", "antigravity"])
            result = expand_recipients("*:coordinators", relay_dir)
            self.assertIn("alpha", result)
            self.assertNotIn("rte", result)
            self.assertNotIn("antigravity", result)

    def test_expand_broadcast_coordinators_filters_mixed_case_retired_peers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(Path(td), ["alpha", "Antigravity", "AGY"])
            result = expand_recipients("*:coordinators", relay_dir)
            self.assertEqual(result, ["alpha"])

    def test_expand_broadcast_claude(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(Path(td), ["alpha", "beta", "cx-red", "iota"])
            result = expand_recipients("*:claude", relay_dir)
            self.assertIn("alpha", result)
            self.assertNotIn("cx-red", result)
            self.assertNotIn("iota", result)

    def test_expand_broadcast_codex(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(Path(td), ["alpha", "cx-red", "cx-blue"])
            result = expand_recipients("*:codex", relay_dir)
            self.assertIn("cx-red", result)
            self.assertIn("cx-blue", result)
            self.assertNotIn("alpha", result)

    def test_expand_broadcast_gemini_is_retired(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(Path(td), ["alpha", "iota", "cx-red"])
            with self.assertRaisesRegex(ValueError, "Unknown broadcast group"):
                expand_recipients("*:gemini", relay_dir)

    def test_expand_broadcast_antigrav_is_retired(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(
                Path(td),
                ["alpha", "agy", "agy-2", "antigrav", "antigrav-2", "antigravity", "cx-red"],
            )
            with self.assertRaisesRegex(ValueError, "agy.review.direct"):
                expand_recipients("*:antigrav", relay_dir)

    def test_expand_broadcast_vibe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(Path(td), ["alpha", "vbe-1", "vbe-2", "cx-red"])
            result = expand_recipients("*:vibe", relay_dir)
            self.assertIn("vbe-1", result)
            self.assertIn("vbe-2", result)
            self.assertNotIn("alpha", result)
            self.assertNotIn("cx-red", result)

    def test_expand_broadcast_workers_spans_all_runtimes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(
                Path(td),
                [
                    "alpha",
                    "cx-red",
                    "iota",
                    "agy",
                    "agy-2",
                    "antigrav",
                    "antigravity",
                    "gemini-cli",
                    "vbe-1",
                    "rte",
                    "alpha-status",
                ],
            )
            result = expand_recipients("*:workers", relay_dir)
            self.assertIn("alpha", result)
            self.assertIn("cx-red", result)
            self.assertNotIn("iota", result)
            self.assertNotIn("agy", result)
            self.assertNotIn("antigrav", result)
            self.assertNotIn("antigravity", result)
            self.assertNotIn("gemini-cli", result)
            self.assertIn("vbe-1", result)
            # Coordinators-only and stray status-file stems are not worker lanes.
            self.assertNotIn("rte", result)
            self.assertNotIn("alpha-status", result)

    def test_expand_direct_antigrav_is_retired(self) -> None:
        with self.assertRaisesRegex(ValueError, "agy.review.direct"):
            expand_recipients("alpha,antigrav")
        with self.assertRaises(ValueError) as agy_error:
            expand_recipients("alpha,agy")
        self.assertIn("agy is not a relay peer", str(agy_error.exception))
        self.assertNotIn("agy relay recipients are retired/excised", str(agy_error.exception))
        with self.assertRaisesRegex(ValueError, "agy.review.direct"):
            expand_recipients("alpha,gemini-cli")

    def test_expand_broadcast_unknown_group(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(Path(td), ["alpha"])
            with self.assertRaises(ValueError):
                expand_recipients("*:unknown", relay_dir)

    def test_expand_normalizes_roles(self) -> None:
        result = expand_recipients("Alpha, CX_Red")
        self.assertEqual(sorted(result), ["alpha", "cx-red"])


if __name__ == "__main__":
    unittest.main()
    (load_dispatch_echo_expectation,)
    (parse_canon_echo,)
