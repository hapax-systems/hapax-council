"""Tests for ``agents.mail_monitor.processors.refusal_feedback``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from agents.mail_monitor.processors import refusal_feedback

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_emit_writes_one_jsonl_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "refusals.jsonl"
    salt_path = tmp_path / "salt"
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", log_path)
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", salt_path)

    refusal_feedback.emit_refusal_feedback(
        {"sender": "alice@example.com", "subject": "re: foo"},
        kind="feedback",
    )

    lines = log_path.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["kind"] == "feedback"
    assert entry["axiom"] == "interpersonal_transparency"
    assert entry["surface"] == "mail-monitor:feedback"


def test_emit_hashes_sender_and_subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec §6: never log raw sender / subject — hash with per-install salt."""
    log_path = tmp_path / "refusals.jsonl"
    salt_path = tmp_path / "salt"
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", log_path)
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", salt_path)

    refusal_feedback.emit_refusal_feedback(
        {"sender": "alice@example.com", "subject": "secret subject"},
    )

    entry = json.loads(log_path.read_text().splitlines()[0])
    assert "alice@example.com" not in str(entry)
    assert "secret subject" not in str(entry)
    assert len(entry["sender_hash"]) == 40  # sha1 hex
    assert len(entry["subject_hash"]) == 40


def test_emit_handles_missing_sender_subject(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mailhook payloads may lack one or both fields; entry must still
    be written."""
    log_path = tmp_path / "refusals.jsonl"
    salt_path = tmp_path / "salt"
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", log_path)
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", salt_path)

    refusal_feedback.emit_refusal_feedback({}, kind="suppress")

    entry = json.loads(log_path.read_text().splitlines()[0])
    assert entry["sender_hash"] == ""
    assert entry["subject_hash"] == ""
    assert entry["kind"] == "suppress"


def test_salt_is_per_install_and_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_path = tmp_path / "refusals.jsonl"
    salt_path = tmp_path / "salt"
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", log_path)
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", salt_path)

    refusal_feedback.emit_refusal_feedback({"sender": "x@example.com", "subject": "y"})
    e1 = json.loads(log_path.read_text().splitlines()[0])
    refusal_feedback.emit_refusal_feedback({"sender": "x@example.com", "subject": "y"})
    e2 = json.loads(log_path.read_text().splitlines()[1])
    # Same install + same input → same hash.
    assert e1["sender_hash"] == e2["sender_hash"]
    assert e1["subject_hash"] == e2["subject_hash"]
    # Salt persisted between calls.
    assert salt_path.exists()


def test_salt_files_differ_across_installs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two distinct salt paths produce different hashes for the same input."""
    log_path = tmp_path / "refusals.jsonl"
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", log_path)

    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", tmp_path / "salt-A")
    refusal_feedback.emit_refusal_feedback({"sender": "z@example.com"})
    a_hash = json.loads(log_path.read_text().splitlines()[-1])["sender_hash"]

    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", tmp_path / "salt-B")
    refusal_feedback.emit_refusal_feedback({"sender": "z@example.com"})
    b_hash = json.loads(log_path.read_text().splitlines()[-1])["sender_hash"]

    assert a_hash != b_hash
