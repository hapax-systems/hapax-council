"""Tests for ``agents.mail_monitor.audit``."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest import mock

from agents.mail_monitor import audit

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_audit_call_appends_one_jsonl_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    audit.audit_call(
        "messages.get",
        message_id="MID-1",
        label="Hapax/Verify",
    )

    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["method"] == "messages.get"
    assert payload["messageId"] == "MID-1"
    assert payload["label"] == "Hapax/Verify"
    assert payload["scope"] == "gmail.modify"
    assert payload["result"] == "ok"
    assert "ts" in payload


def test_audit_call_creates_parent_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "nested" / "deeper" / "audit.jsonl"
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", target)
    audit.audit_call("users.watch", result="ok")
    assert target.exists()


def test_audit_call_swallows_io_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A write failure must never propagate — audit loss never crashes
    the daemon."""

    class _BoomPath(type(audit.AUDIT_LOG_PATH)):
        def open(self, *args: object, **kwargs: object) -> object:  # noqa: ARG002
            raise OSError("disk full")

    fake_path = mock.MagicMock()
    fake_path.parent.mkdir = mock.Mock()
    fake_path.open = mock.Mock(side_effect=OSError("disk full"))
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", fake_path)

    # No assertion required other than "doesn't raise".
    audit.audit_call("messages.get", message_id="X")


def test_audit_call_appends_multiple_independent_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    for i in range(5):
        audit.audit_call("messages.get", message_id=f"M-{i}")
    entries = audit.read_audit_entries(tmp_path / "audit.jsonl")
    assert [e["messageId"] for e in entries] == [f"M-{i}" for i in range(5)]


def test_audit_call_records_filter_id_when_provided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    audit.audit_call(
        "users.settings.filters.create",
        filter_id="FID-42",
        label="Hapax/Verify",
    )
    entry = audit.read_audit_entries(tmp_path / "audit.jsonl")[0]
    assert entry["filterId"] == "FID-42"
    assert "messageId" not in entry


def test_audit_call_supports_extra_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit, "AUDIT_LOG_PATH", tmp_path / "audit.jsonl")
    audit.audit_call(
        "messages.modify",
        message_id="M-x",
        extra={"action": "remove_inbox"},
    )
    entry = audit.read_audit_entries(tmp_path / "audit.jsonl")[0]
    assert entry["action"] == "remove_inbox"


def test_read_audit_entries_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert audit.read_audit_entries(tmp_path / "nope.jsonl") == []


def test_read_audit_entries_skips_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text(
        '{"ts":"x","method":"messages.get"}\nnot-json\n{"ts":"y","method":"messages.modify"}\n'
    )
    entries = audit.read_audit_entries(path)
    assert len(entries) == 2
    assert entries[0]["method"] == "messages.get"
    assert entries[1]["method"] == "messages.modify"
