from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from shared.relay_mq import _connect

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "hapax-operator-message"


def run_operator_message(*args: str, db: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(db), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_advisory_message_targets_operator(tmp_path: Path) -> None:
    db = tmp_path / "messages.db"
    result = run_operator_message(
        "--type",
        "advisory",
        "--sender",
        "cx_red",
        "--subject",
        "Lane progress",
        "--payload",
        "The lane has a progress update.",
        "--json",
        db=db,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["recipient"] == "operator"
    assert payload["sender"] == "cx-red"
    assert payload["message_type"] == "advisory"

    with _connect(db) as conn:
        message = conn.execute("SELECT * FROM messages").fetchone()
        recipient = conn.execute("SELECT * FROM recipients").fetchone()

    assert message["message_type"] == "advisory"
    assert message["recipients_spec"] == "operator"
    assert "operator-inbox" in message["tags"]
    assert recipient["recipient"] == "operator"
    assert recipient["state"] == "offered"


def test_dispatch_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "messages.db"
    result = run_operator_message(
        "--type",
        "dispatch",
        "--subject",
        "Do work",
        "--payload",
        "This must be refused.",
        db=db,
    )

    assert result.returncode == 2
    assert "refuses dispatch" in result.stderr
    assert not db.exists()


def test_query_requires_governed_reference(tmp_path: Path) -> None:
    db = tmp_path / "messages.db"
    result = run_operator_message(
        "--type",
        "query",
        "--subject",
        "Need a decision",
        "--payload",
        "Choose one.",
        db=db,
    )

    assert result.returncode == 2
    assert "require --authority-case" in result.stderr
    assert not db.exists()


def test_query_with_task_id_is_queued(tmp_path: Path) -> None:
    db = tmp_path / "messages.db"
    result = run_operator_message(
        "--type",
        "query",
        "--priority",
        "1",
        "--subject",
        "Need a decision",
        "--payload",
        "Choose one.",
        "--task-id",
        "centralized-coordination",
        "--json",
        db=db,
    )

    assert result.returncode == 0, result.stderr
    with _connect(db) as conn:
        message = conn.execute("SELECT * FROM messages").fetchone()

    assert message["message_type"] == "query"
    assert message["authority_item"] == "centralized-coordination"
    assert "task:centralized-coordination" in message["tags"]


def test_payload_file_is_supported(tmp_path: Path) -> None:
    db = tmp_path / "messages.db"
    payload = tmp_path / "payload.md"
    payload.write_text("Longer operator-visible update", encoding="utf-8")

    result = run_operator_message(
        "--type",
        "advisory",
        "--subject",
        "Payload file",
        "--payload-file",
        str(payload),
        db=db,
    )

    assert result.returncode == 0, result.stderr
    with _connect(db) as conn:
        message = conn.execute("SELECT * FROM messages").fetchone()

    assert message["payload"] is None
    assert message["payload_path"] == str(payload)
