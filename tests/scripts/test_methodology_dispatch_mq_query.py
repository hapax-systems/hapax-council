"""Binding lookup must not scan unrelated message bodies or widen authority."""

import importlib.machinery
import importlib.util
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from shared.relay_mq import ensure_schema

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "hapax-methodology-dispatch"


@pytest.fixture
def dispatcher() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("dispatch_mq_query_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "messages.db"
    ensure_schema(path)
    return path


def insert_message(db: Path, **overrides) -> str:
    now = datetime.now(UTC)
    fields = {
        "message_id": "matching",
        "sender": "fixture",
        "message_type": "dispatch",
        "subject": "unrelated subject",
        "authority_case": "CASE-FIXTURE",
        "authority_item": "task-fixture",
        "recipients_spec": "cx-fixture",
        "payload": "isolated test data",
        "payload_hash": "fixture-only",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=2)).isoformat(),
        "stale_after": (now + timedelta(hours=1)).isoformat(),
    }
    recipient = overrides.pop("recipient", "cx-fixture")
    state = overrides.pop("state", "accepted")
    fields.update(overrides)
    with sqlite3.connect(db) as conn:
        conn.execute(
            f"INSERT INTO messages ({','.join(fields)}) VALUES ({','.join('?' for _ in fields)})",
            tuple(fields.values()),
        )
        conn.execute(
            "INSERT INTO recipients (message_id,recipient,state,created_at,updated_at) "
            "VALUES (?,?,?,?,?)",
            (fields["message_id"], recipient, state, now.isoformat(), now.isoformat()),
        )
    return fields["message_id"]


def binding(dispatcher: ModuleType, db: Path, **kwargs):
    fields = {"authority_case": "CASE-FIXTURE", "authority_item": "item-fixture"}
    validation = dispatcher.Validation(
        True, "fixture", dispatcher.TaskNote(db.parent / "isolated-task.md", fields)
    )
    return dispatcher.check_durable_dispatch_binding(
        task_id="task-fixture",
        lane="cx-fixture",
        validation=validation,
        db_path=db,
        **kwargs,
    )


def test_binding_lookup_work_is_bounded_with_unrelated_authority_messages(
    dispatcher, db, monkeypatch
):
    insert_message(db)
    # Same AuthorityCase, other tasks/lanes. Real schema and indexes; no query mock.
    # The payload makes fetching messages materially different from reading recipients.
    count = 4_000
    with sqlite3.connect(db) as conn:
        conn.executemany(
            "INSERT INTO messages (message_id,sender,message_type,subject,authority_case,"
            "authority_item,recipients_spec,payload,payload_hash,created_at) "
            "VALUES (?,'fixture','dispatch','noise','CASE-FIXTURE','noise','cx-other',"
            "?,'fixture-only','2000-01-01')",
            ((f"noise-{i}", "x" * 8192) for i in range(count)),
        )
        conn.executemany(
            "INSERT INTO recipients (message_id,recipient,state,created_at,updated_at) "
            "VALUES (?,'cx-other','accepted','2000-01-01','2000-01-01')",
            ((f"noise-{i}",) for i in range(count)),
        )
    connect = sqlite3.connect
    steps = 0

    def limited_connect(*args, **kwargs):
        conn = connect(*args, **kwargs)

        def progress():
            nonlocal steps
            steps += 100
            # Deterministic VM work bound, independent of runner/cache/disk speed.
            return int(steps > count * 8)

        conn.set_progress_handler(progress, 100)
        return conn

    monkeypatch.setattr(dispatcher.sqlite3, "connect", limited_connect)
    result = binding(dispatcher, db)
    assert result.ok, (result.reason, steps)
    assert result.message_id == "matching"


@pytest.mark.parametrize(
    "overrides,requested_id",
    [
        ({"recipient": "cx-other"}, None),
        ({"authority_case": "CASE-OTHER"}, None),
        ({"authority_item": "other-task"}, None),
        ({"message_type": "advisory"}, None),
        ({}, "different-message"),
        ({"expires_at": "2000-01-01T00:00:00Z"}, None),
        ({"stale_after": "2000-01-01T00:00:00Z"}, None),
        ({"stale_after": None}, None),
    ],
)
def test_lookup_refuses_nonmatching_or_noncurrent_binding(dispatcher, db, overrides, requested_id):
    insert_message(db, **overrides)
    result = binding(dispatcher, db, message_id=requested_id)
    assert not result.ok
    assert result.advisory_only
    assert result.message_id is None


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"authority_item": "item-fixture"},
        {"authority_item": "other", "subject": "task-fixture"},
        {"state": "processed"},
    ],
)
def test_lookup_preserves_binding_alternatives_and_recipient_states(dispatcher, db, overrides):
    message_id = insert_message(db, **overrides)
    result = binding(dispatcher, db, message_id=message_id)
    assert result.ok
    assert result.message_id == message_id


def test_lookup_retains_latest_five_window(dispatcher, db):
    insert_message(db, message_id="older-valid")
    for i in range(5):
        insert_message(db, message_id=f"expired-{i}", expires_at="2000-01-01T00:00:00Z")
    assert not binding(dispatcher, db).ok
    insert_message(db, message_id="newest-valid")
    assert binding(dispatcher, db).message_id == "newest-valid"


def test_lookup_database_error_is_not_a_binding(dispatcher, db):
    db.write_bytes(b"not a SQLite database")
    result = binding(dispatcher, db)
    assert not result.ok
    assert result.reason.startswith("durable_mq_unreadable:")
