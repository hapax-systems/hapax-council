"""Tests for ``agents.mail_monitor.processors.discard``."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest import mock

from prometheus_client import REGISTRY

from agents.mail_monitor.processors import discard

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _counter(result: str) -> float:
    val = REGISTRY.get_sample_value(
        "hapax_mail_monitor_discard_processed_total",
        {"result": result},
    )
    return val or 0.0


def test_process_discard_removes_inbox_and_adds_label_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    before = _counter("ok")

    fake_service = mock.Mock()
    fake_service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}

    ok = discard.process_discard(fake_service, "M-1", label_id="L_discard")

    assert ok is True
    modify_call = fake_service.users.return_value.messages.return_value.modify
    modify_call.assert_called_once()
    body = modify_call.call_args.kwargs["body"]
    assert body["addLabelIds"] == ["L_discard"]
    assert body["removeLabelIds"] == ["INBOX"]
    assert _counter("ok") - before == 1.0


def test_process_discard_never_sends_human_label_name_as_label_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")

    fake_service = mock.Mock()
    fake_service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}

    ok = discard.process_discard(fake_service, "M-1")

    assert ok is True
    body = fake_service.users.return_value.messages.return_value.modify.call_args.kwargs["body"]
    assert "addLabelIds" not in body
    assert body["removeLabelIds"] == ["INBOX"]


def test_process_discard_uses_label_id_from_enriched_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")

    fake_service = mock.Mock()
    fake_service.users.return_value.messages.return_value.modify.return_value.execute.return_value = {}

    ok = discard.process_discard(
        fake_service,
        {"id": "M-1", "label_ids_by_name": {"Hapax/Discard": "L_discard"}},
    )

    assert ok is True
    body = fake_service.users.return_value.messages.return_value.modify.call_args.kwargs["body"]
    assert body["addLabelIds"] == ["L_discard"]
    assert body["removeLabelIds"] == ["INBOX"]


def test_process_discard_handles_http_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from googleapiclient.errors import HttpError

    from agents.mail_monitor import audit

    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    before_err = _counter("api_error")

    fake_service = mock.Mock()
    err = HttpError(resp=mock.Mock(status=403), content=b"forbidden")
    fake_service.users.return_value.messages.return_value.modify.return_value.execute.side_effect = err

    ok = discard.process_discard(fake_service, "M-fail")

    assert ok is False
    assert _counter("api_error") - before_err == 1.0
