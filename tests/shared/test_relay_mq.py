from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from shared.relay_mq import (
    MessageFilters,
    _connect,
    ack_message,
    consume_messages,
    dead_letters,
    ensure_schema,
    expand_recipients,
    inspect_message,
    list_messages,
    purge_expired,
    send_message,
)
from shared.relay_mq_envelope import (
    DiskPressureError,
    Envelope,
    TransitionError,
)

DB = Path(":memory:")  # only for non-schema tests that use a single function call


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


class TestRecipientExpansion(unittest.TestCase):
    def test_expand_direct_single(self) -> None:
        result = expand_recipients("alpha")
        self.assertEqual(result, ["alpha"])

    def test_expand_direct_multi(self) -> None:
        result = expand_recipients("alpha,gamma,cx-red")
        self.assertEqual(sorted(result), ["alpha", "cx-red", "gamma"])

    def test_expand_broadcast_all(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(Path(td), ["alpha", "beta", "gamma", "delta"])
            result = expand_recipients("*:all", relay_dir)
            self.assertEqual(len(result), 4)

    def test_expand_broadcast_coordinators(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            relay_dir = _make_relay_dir(Path(td), ["alpha", "beta", "rte"])
            result = expand_recipients("*:coordinators", relay_dir)
            self.assertIn("alpha", result)
            self.assertNotIn("rte", result)

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
