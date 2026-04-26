"""Tests for ``agents.mail_monitor.runner.dispatch_message``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

from prometheus_client import REGISTRY

from agents.mail_monitor import runner
from agents.mail_monitor.classifier import Category

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _counter(category: str, result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_dispatch_total",
        {"category": category, "result": result},
    )
    return val or 0.0


def test_dispatch_routes_discard_label_to_process_discard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec §3.F path: Hapax/Discard label → process_discard called with
    the message id and INBOX removed."""
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    before = _counter("F_ANTIPATTERN", "processed")

    fake_service = mock.Mock()
    fake_service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}

    cat = runner.dispatch_message(
        fake_service,
        {"id": "M-discard", "label_names": ["Hapax/Discard"]},
    )

    assert cat is Category.F_ANTIPATTERN
    assert _counter("F_ANTIPATTERN", "processed") - before == 1.0
    fake_service.users.return_value.messages.return_value.modify.assert_called_once()


def test_dispatch_routes_refusal_feedback_to_emit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec §3.E path: reply-to-Hapax → refusal-feedback log entry,
    no Gmail mutations."""
    from agents.mail_monitor import audit
    from agents.mail_monitor.processors import refusal_feedback

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", tmp_path / "refusals.jsonl")
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", tmp_path / "salt")

    before = _counter("E_REFUSAL_FEEDBACK", "processed")
    fake_service = mock.Mock()

    cat = runner.dispatch_message(
        fake_service,
        {
            "id": "M-fb",
            "replies_to_hapax_thread": True,
            "sender": "operator@example.com",
            "subject": "re: foo",
            "body_text": "thanks but not interested",
        },
    )

    assert cat is Category.E_REFUSAL_FEEDBACK
    assert _counter("E_REFUSAL_FEEDBACK", "processed") - before == 1.0
    # No Gmail-side mutation for refusal-feedback.
    fake_service.users.return_value.messages.return_value.modify.assert_not_called()
    log_lines = (tmp_path / "refusals.jsonl").read_text().splitlines()
    assert len(log_lines) == 1


def test_dispatch_marks_deferred_categories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Categories A and D still land in 010/011 — those still record
    `deferred` outcome and do no IO until their processors merge."""
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    before = _counter("D_OPERATIONAL", "deferred")
    fake_service = mock.Mock()

    cat = runner.dispatch_message(
        fake_service,
        {"id": "M-op", "label_names": ["Hapax/Operational"]},
    )

    assert cat is Category.D_OPERATIONAL
    assert _counter("D_OPERATIONAL", "deferred") - before == 1.0
    fake_service.users.return_value.messages.return_value.modify.assert_not_called()


def test_dispatch_writes_audit_log_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every dispatched message produces one `messages.get` audit entry
    with the resolved Hapax label."""
    from agents.mail_monitor import audit

    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", audit_path)

    fake_service = mock.Mock()
    fake_service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}

    runner.dispatch_message(
        fake_service,
        {"id": "M-1", "label_names": ["Hapax/Discard"]},
    )

    entries = audit.read_audit_entries(audit_path)
    get_entries = [e for e in entries if e["method"] == "messages.get"]
    assert len(get_entries) == 1
    assert get_entries[0]["label"] == "Hapax/Discard"
    assert get_entries[0]["messageId"] == "M-1"


def test_dispatch_audit_records_label_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit log records the most-specific Hapax label, never raw
    sender/subject — spec §6 redaction."""
    from agents.mail_monitor import audit

    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", audit_path)
    fake_service = mock.Mock()

    runner.dispatch_message(
        fake_service,
        {"id": "M-2", "label_names": ["Hapax/Verify", "INBOX"]},
    )

    entry = audit.read_audit_entries(audit_path)[0]
    assert entry["label"] == "Hapax/Verify"
    # Body / sender / subject must NOT be in the audit log — spec §6.
    assert "body" not in entry
    assert "sender" not in entry
    assert "subject" not in entry


def test_register_processor_is_placeholder() -> None:
    import pytest

    with pytest.raises(NotImplementedError):
        runner.register_processor(Category.B_VERIFY, lambda *_: True)
