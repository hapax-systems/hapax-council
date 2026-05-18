from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from shared.relay_mq import _connect, dead_letters, send_message
from shared.relay_mq_envelope import Envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-mq-consume"


def _load_script() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("hapax_mq_consume", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


def _env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(overrides)
    return env


def _run(db_path: Path, role: str = "alpha", *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--role",
            role,
            "--db",
            str(db_path),
            *extra,
        ],
        text=True,
        capture_output=True,
        timeout=5,
    )


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


def _recipient_state(db_path: Path, message_id: str, role: str = "alpha") -> str | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT state FROM recipients WHERE message_id = ? AND recipient = ?",
            (message_id, role),
        ).fetchone()
    return None if row is None else str(row["state"])


def test_formats_fresh_stale_and_expired_messages_and_marks_read(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    fresh = _message(subject="fresh dispatch", message_type="dispatch", authority_case="CASE-1")
    stale_created = datetime.now(UTC) - timedelta(hours=2)
    stale = _message(
        subject="stale advisory",
        created_at=stale_created,
        stale_after=stale_created + timedelta(minutes=1),
        expires_at=stale_created + timedelta(days=1),
    )
    expired_created = datetime.now(UTC) - timedelta(days=2)
    expired = _message(
        subject="expired advisory",
        created_at=expired_created,
        stale_after=expired_created + timedelta(minutes=1),
        expires_at=expired_created + timedelta(minutes=2),
    )
    for env in (fresh, stale, expired):
        send_message(db_path, env)

    result = _run(db_path)

    assert result.returncode == 0, result.stderr
    assert "MQ INBOX (alpha):" in result.stdout
    assert "[FRESH DISPATCH/P2] fresh dispatch" in result.stdout
    assert "authority: CASE-1" in result.stdout
    assert "[STALE ADVISORY/P2] stale advisory" in result.stdout
    assert "[EXPIRED ADVISORY/P2] expired advisory" in result.stdout
    assert _recipient_state(db_path, fresh.message_id) == "read"
    assert _recipient_state(db_path, stale.message_id) == "read"
    assert _recipient_state(db_path, expired.message_id) is None
    assert dead_letters(db_path)[0]["message_id"] == expired.message_id


def test_causal_order_defers_child_until_parent_read(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    parent = _message(subject="parent")
    child = _message(subject="child", parent_message_id=parent.message_id)
    send_message(db_path, parent)
    send_message(db_path, child)

    first = _run(db_path, "alpha", "--limit", "8")
    second = _run(db_path, "alpha", "--limit", "8")

    assert "parent" in first.stdout
    assert "child" not in first.stdout
    assert "child" in second.stdout


def test_output_failure_rolls_back_offered_to_read(tmp_path: Path) -> None:
    db_path = tmp_path / "messages.db"
    env = _message(subject="atomic item")
    send_message(db_path, env)
    module = _load_script()

    def fail_write(_text: str) -> None:
        raise OSError("stdout closed")

    with pytest.raises(OSError):
        module.consume_and_surface(
            db_path,
            role="alpha",
            limit=8,
            busy_timeout_ms=100,
            write_output=fail_write,
        )

    assert _recipient_state(db_path, env.message_id) == "offered"


def test_missing_corrupt_locked_timeout_and_import_failure_fail_open(tmp_path: Path) -> None:
    missing = _run(tmp_path / "missing.db")
    assert missing.returncode == 0
    assert missing.stdout == ""

    corrupt_db = tmp_path / "corrupt.db"
    corrupt_db.write_text("not sqlite", encoding="utf-8")
    corrupt = _run(corrupt_db)
    assert corrupt.returncode == 0
    assert corrupt.stdout == ""

    locked_db = tmp_path / "locked.db"
    send_message(locked_db, _message(subject="locked"))
    conn = sqlite3.connect(locked_db)
    try:
        conn.execute("BEGIN IMMEDIATE")
        locked = _run(locked_db, "alpha", "--timeout", "0.1")
    finally:
        conn.rollback()
        conn.close()
    assert locked.returncode == 0

    timeout = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--role",
            "alpha",
            "--db",
            str(locked_db),
            "--timeout",
            "0.1",
        ],
        text=True,
        capture_output=True,
        timeout=5,
        env=_env(HAPAX_MQ_CONSUME_TEST_SLEEP="1"),
    )
    assert timeout.returncode == 0

    import_failure = subprocess.run(
        [sys.executable, str(SCRIPT), "--role", "alpha", "--timeout", "0.1"],
        text=True,
        capture_output=True,
        timeout=5,
        env=_env(HAPAX_MQ_CONSUME_FORCE_IMPORT_ERROR="1"),
    )
    assert import_failure.returncode == 0
