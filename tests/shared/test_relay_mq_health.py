from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from shared.relay_mq import _connect, ack_message, consume_messages, send_message
from shared.relay_mq_envelope import Envelope
from shared.relay_mq_health import execute_escalations, execute_retries, tick_health


def _message(**overrides: object) -> Envelope:
    defaults: dict[str, object] = {
        "sender": "tester",
        "message_type": "advisory",
        "subject": "queue item",
        "recipients_spec": "alpha",
        "payload": "payload body",
    }
    defaults.update(overrides)
    return Envelope(**defaults)


def test_tick_health_counts_pending_stale_dead_letters_and_retry_candidates(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    send_message(db_path, _message(subject="pending"))
    read_env = _message(subject="read")
    send_message(db_path, read_env)
    consume_messages(db_path, "alpha", limit=1)
    stale_created = datetime.now(UTC) - timedelta(hours=2)
    send_message(
        db_path,
        _message(
            subject="stale",
            created_at=stale_created,
            stale_after=stale_created + timedelta(minutes=1),
            expires_at=stale_created + timedelta(days=1),
        ),
    )
    expired_created = datetime.now(UTC) - timedelta(days=2)
    expired = _message(
        subject="expired",
        created_at=expired_created,
        stale_after=expired_created + timedelta(minutes=1),
        expires_at=expired_created + timedelta(minutes=2),
    )
    send_message(db_path, expired)
    consume_messages(db_path, "alpha", limit=8)

    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE recipients SET state = 'read', updated_at = ? WHERE message_id = ?",
            ((datetime.now(UTC) - timedelta(hours=1)).isoformat(), read_env.message_id),
        )
        conn.commit()

    health = tick_health(db_path, last_tick_at=datetime.now(UTC), retry_interval_s=60)

    assert health is not None
    assert health.label == "ACTIVE"
    assert health.pending_count >= 1
    assert health.stale_count >= 1
    assert health.dead_letter_count == 1
    assert health.retry_candidate_count >= 1
    assert health.degraded


def test_execute_retries_reoffers_stale_read_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    env = _message()
    send_message(db_path, env)
    consume_messages(db_path, "alpha")
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE recipients SET updated_at = ? WHERE message_id = ?",
            ((datetime.now(UTC) - timedelta(hours=1)).isoformat(), env.message_id),
        )
        conn.commit()

    result = execute_retries(db_path, retry_interval_s=60)

    assert result.label == "ACTIVE"
    assert result.changed_count == 1
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT state, retry_count FROM recipients WHERE message_id = ?",
            (env.message_id,),
        ).fetchone()
    assert row["state"] == "offered"
    assert row["retry_count"] == 1


def test_execute_escalations_marks_deadline_elapsed(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    past = datetime.now(UTC) - timedelta(hours=2)
    env = _message(
        created_at=past,
        stale_after=past + timedelta(minutes=1),
        expires_at=past + timedelta(minutes=5),
    )
    send_message(db_path, env)

    result = execute_escalations(db_path)

    assert result.label == "ACTIVE"
    assert result.changed_count == 1
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT state, reason FROM recipients WHERE message_id = ?",
            (env.message_id,),
        ).fetchone()
    assert row["state"] == "escalated"
    assert row["reason"] == "deadline_elapsed"


def test_health_fail_open_labels_missing_corrupt_and_contended(tmp_path: Path) -> None:
    missing = tick_health(tmp_path / "missing" / "messages.db")
    assert missing is not None
    assert missing.label == "UNREACHABLE"

    corrupt_db = tmp_path / "corrupt.db"
    corrupt_db.write_text("not sqlite", encoding="utf-8")
    corrupt = tick_health(corrupt_db)
    assert corrupt is not None
    assert corrupt.label == "CORRUPT"

    locked_db = tmp_path / "locked.db"
    send_message(locked_db, _message())
    conn = sqlite3.connect(locked_db)
    try:
        conn.execute("BEGIN EXCLUSIVE")
        locked = tick_health(locked_db, busy_timeout_ms=1)
    finally:
        conn.rollback()
        conn.close()
    assert locked is not None
    assert locked.label in {"ACTIVE", "CONTENDED"}


def test_processed_messages_are_not_escalated(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    past = datetime.now(UTC) - timedelta(hours=2)
    env = _message(
        created_at=past,
        stale_after=past + timedelta(minutes=1),
        expires_at=past + timedelta(minutes=5),
    )
    send_message(db_path, env)
    consume_messages(db_path, "alpha")
    ack_message(db_path, env.message_id, "alpha", "accepted")
    ack_message(db_path, env.message_id, "alpha", "processed")

    result = execute_escalations(db_path)

    assert result.changed_count == 0
