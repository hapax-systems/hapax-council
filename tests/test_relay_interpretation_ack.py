"""Tests for relay interpretation acknowledgment columns."""

from __future__ import annotations

import sqlite3

from shared.relay_mq import _SCHEMA_SQL


def test_recipients_table_has_interpretation_columns():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA_SQL)
    cursor = conn.execute("PRAGMA table_info(recipients)")
    columns = {row[1] for row in cursor.fetchall()}
    assert "interpretation_summary" in columns
    assert "interpretation_confidence" in columns
    assert "interpreted_at" in columns
    conn.close()


def test_interpretation_columns_are_nullable():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        """INSERT INTO messages (message_id, version, sender, message_type,
           priority, subject, recipients_spec, payload, payload_hash,
           created_at)
           VALUES ('msg-1', 1, 'alpha', 'advisory', 2, 'test',
                   'beta', '{}', 'abc', '2026-05-22T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO recipients (message_id, recipient, created_at, updated_at)
           VALUES ('msg-1', 'beta', '2026-05-22T00:00:00Z', '2026-05-22T00:00:00Z')"""
    )
    row = conn.execute(
        "SELECT interpretation_summary, interpretation_confidence, interpreted_at "
        "FROM recipients WHERE message_id = 'msg-1'"
    ).fetchone()
    assert row == (None, None, None)
    conn.close()


def test_interpretation_columns_accept_values():
    conn = sqlite3.connect(":memory:")
    conn.executescript(_SCHEMA_SQL)
    conn.execute(
        """INSERT INTO messages (message_id, version, sender, message_type,
           priority, subject, recipients_spec, payload, payload_hash,
           created_at)
           VALUES ('msg-2', 1, 'alpha', 'advisory', 2, 'test',
                   'beta', '{}', 'abc', '2026-05-22T00:00:00Z')"""
    )
    conn.execute(
        """INSERT INTO recipients (message_id, recipient, state,
           interpretation_summary, interpretation_confidence, interpreted_at,
           created_at, updated_at)
           VALUES ('msg-2', 'beta', 'accepted',
                   'understood as architecture review', 0.85,
                   '2026-05-22T00:01:00Z',
                   '2026-05-22T00:00:00Z', '2026-05-22T00:01:00Z')"""
    )
    row = conn.execute(
        "SELECT interpretation_summary, interpretation_confidence "
        "FROM recipients WHERE message_id = 'msg-2'"
    ).fetchone()
    assert row[0] == "understood as architecture review"
    assert row[1] == 0.85
    conn.close()
