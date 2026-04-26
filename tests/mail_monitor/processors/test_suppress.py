"""Tests for ``agents.mail_monitor.processors.suppress``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

from prometheus_client import REGISTRY

from agents.mail_monitor.processors import suppress

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _counter(result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_suppress_processed_total",
        {"result": result},
    )
    return val or 0.0


def _service_double() -> mock.Mock:
    service = mock.Mock()
    service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}
    return service


# ── _extract_domain ──────────────────────────────────────────────────


def test_extract_domain_handles_bare_email() -> None:
    assert suppress._extract_domain("alice@example.com") == "example.com"


def test_extract_domain_handles_display_name_form() -> None:
    assert suppress._extract_domain('"Alice" <alice@example.com>') == "example.com"


def test_extract_domain_lowercases() -> None:
    assert suppress._extract_domain("BOB@EXAMPLE.COM") == "example.com"


def test_extract_domain_returns_none_on_invalid() -> None:
    assert suppress._extract_domain("not-an-email") is None
    assert suppress._extract_domain("") is None
    assert suppress._extract_domain(None) is None


# ── process_suppress ──────────────────────────────────────────────────


def test_process_suppress_appends_entry_and_modifies_gmail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit
    from agents.mail_monitor.processors import refusal_feedback
    from shared import contact_suppression as cs

    monkeypatch.setenv("HAPAX_CONTACT_SUPPRESSION_LIST", str(tmp_path / "suppress.yaml"))
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", tmp_path / "refusals.jsonl")
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", tmp_path / "salt")

    before_ok = _counter("ok")
    service = _service_double()

    ok = suppress.process_suppress(
        service,
        {
            "id": "M-supp-1",
            "sender": "alice@example.com",
            "subject": "re: hapax",
            "body_text": "SUPPRESS\n",
        },
    )

    assert ok is True
    assert _counter("ok") - before_ok == 1.0

    # Suppression entry persisted with email_domain.
    entries = cs.load(path=tmp_path / "suppress.yaml").entries
    assert len(entries) == 1
    assert entries[0].email_domain == "example.com"
    assert entries[0].initiator == "target_optout"
    assert entries[0].message_id == "M-supp-1"

    # Gmail-side modify called with INBOX + UNREAD removed.
    modify = service.users.return_value.messages.return_value.modify
    modify.assert_called_once()
    body = modify.call_args.kwargs["body"]
    assert set(body["removeLabelIds"]) == {"INBOX", "UNREAD"}

    # Refusal-brief log got an entry.
    log_lines = (tmp_path / "refusals.jsonl").read_text().splitlines()
    assert len(log_lines) == 1


def test_process_suppress_uses_orcid_when_provided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit
    from agents.mail_monitor.processors import refusal_feedback
    from shared import contact_suppression as cs

    monkeypatch.setenv("HAPAX_CONTACT_SUPPRESSION_LIST", str(tmp_path / "suppress.yaml"))
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", tmp_path / "refusals.jsonl")
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", tmp_path / "salt")

    suppress.process_suppress(
        _service_double(),
        {
            "id": "M-orcid",
            "sender": "alice@example.com",
            "orcid": "0000-0001-2345-6789",
        },
    )

    entry = cs.load(path=tmp_path / "suppress.yaml").entries[0]
    assert entry.orcid == "0000-0001-2345-6789"
    assert entry.email_domain == "example.com"


def test_process_suppress_skips_when_no_sender_or_orcid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit
    from agents.mail_monitor.processors import refusal_feedback

    monkeypatch.setenv("HAPAX_CONTACT_SUPPRESSION_LIST", str(tmp_path / "suppress.yaml"))
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", tmp_path / "refusals.jsonl")

    before = _counter("no_sender")
    ok = suppress.process_suppress(
        _service_double(),
        {"id": "M-anon"},
    )
    assert ok is False
    assert _counter("no_sender") - before == 1.0


def test_process_suppress_handles_gmail_http_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from googleapiclient.errors import HttpError

    from agents.mail_monitor import audit
    from agents.mail_monitor.processors import refusal_feedback

    monkeypatch.setenv("HAPAX_CONTACT_SUPPRESSION_LIST", str(tmp_path / "suppress.yaml"))
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", tmp_path / "refusals.jsonl")
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", tmp_path / "salt")

    before = _counter("api_error")
    service = mock.Mock()
    err = HttpError(resp=mock.Mock(status=403), content=b"forbidden")
    service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = err

    ok = suppress.process_suppress(
        service,
        {"id": "M-x", "sender": "alice@example.com"},
    )
    assert ok is False
    assert _counter("api_error") - before == 1.0


def test_process_suppress_is_idempotent_on_second_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two SUPPRESS replies from the same sender domain produce one
    entry — append_entry is dedupe-aware on (orcid, email_domain,
    initiator)."""
    from agents.mail_monitor import audit
    from agents.mail_monitor.processors import refusal_feedback
    from shared import contact_suppression as cs

    monkeypatch.setenv("HAPAX_CONTACT_SUPPRESSION_LIST", str(tmp_path / "suppress.yaml"))
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(refusal_feedback, "REFUSAL_LOG_PATH", tmp_path / "refusals.jsonl")
    monkeypatch.setattr(refusal_feedback, "_SALT_PATH", tmp_path / "salt")

    msg1 = {"id": "M-1", "sender": "alice@example.com"}
    msg2 = {"id": "M-2", "sender": "carol@example.com"}

    suppress.process_suppress(_service_double(), msg1)
    suppress.process_suppress(_service_double(), msg2)

    entries = cs.load(path=tmp_path / "suppress.yaml").entries
    # Same email_domain + initiator → second call no-ops in shared module.
    assert len(entries) == 1
