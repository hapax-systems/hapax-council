from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest import mock
from zoneinfo import ZoneInfo

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "send-stakeholder-revenue-brief.py"
TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 4, 30, 8, 45, tzinfo=TZ)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("stakeholder_revenue_brief", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


brief = _load_module()


def _source(path: Path) -> Path:
    path.write_text(
        """---
title: Stakeholder Brief
status: draft
gmail_message_id: old-message
---
# Stakeholder Brief

Opening note.

## Revenue

Scenario table.
""",
        encoding="utf-8",
    )
    return path


def _config(
    tmp_path: Path,
    *,
    send: bool = False,
    force: bool = False,
    sender: str | None = "operator@example.invalid",
    recipients: tuple[str, ...] = ("stakeholder@example.invalid",),
) -> brief.BriefConfig:
    return brief.BriefConfig(
        source_path=_source(tmp_path / "brief.md"),
        generated_dir=tmp_path / "generated",
        state_dir=tmp_path / "state",
        timezone=TZ,
        send=send,
        force=force,
        min_hours_between=23.0,
        sender=sender,
        recipients=recipients,
        cc=("copy@example.invalid",),
        recipient_name="Stakeholder",
        subject="Brief",
        delivery_note=None,
        summary_lines=(),
    )


def _fake_pandoc(_markdown_path: Path, docx_path: Path) -> None:
    docx_path.write_bytes(b"fake-docx")


def _gmail_service(*, profile_email: str = "operator@example.invalid", message_id: str = "msg-1"):
    service = mock.Mock()
    users = service.users.return_value
    users.getProfile.return_value.execute.return_value = {"emailAddress": profile_email}
    users.messages.return_value.send.return_value.execute.return_value = {"id": message_id}
    return service


def test_default_no_send_generates_docx_without_gmail_or_state(tmp_path: Path) -> None:
    config = _config(tmp_path, send=False, recipients=())
    with (
        mock.patch.object(brief, "_run_pandoc", side_effect=_fake_pandoc),
        mock.patch.object(brief, "_build_gmail_service_from_pass") as gmail_mock,
    ):
        result = brief.run(config, now=NOW)

    assert result["sent"] is False
    assert Path(result["generated_markdown"]).exists()
    assert Path(result["docx"]).read_bytes() == b"fake-docx"
    assert not (config.state_dir / "state.json").exists()
    gmail_mock.assert_not_called()


def test_recent_send_skips_before_generation_or_gmail(tmp_path: Path) -> None:
    config = _config(tmp_path, send=True)
    config.state_dir.mkdir(parents=True)
    (config.state_dir / "state.json").write_text(
        json.dumps({"last_sent_at": NOW.isoformat()}),
        encoding="utf-8",
    )

    with (
        mock.patch.object(brief, "_run_pandoc") as pandoc_mock,
        mock.patch.object(brief, "_build_gmail_service_from_pass") as gmail_mock,
    ):
        result = brief.run(config, now=NOW)

    assert result == {
        "skipped": True,
        "reason": "recently_sent",
        "last_sent_at": NOW.isoformat(),
        "min_hours_between": 23.0,
    }
    pandoc_mock.assert_not_called()
    gmail_mock.assert_not_called()


def test_successful_send_writes_state_and_source_frontmatter(tmp_path: Path) -> None:
    config = _config(tmp_path, send=True)
    service = _gmail_service(message_id="gmail-123")

    with (
        mock.patch.object(brief, "_run_pandoc", side_effect=_fake_pandoc),
        mock.patch.object(brief, "_build_gmail_service_from_pass", return_value=service),
    ):
        result = brief.run(config, now=NOW)

    assert result["sent"] is True
    assert result["gmail_message_id"] == "gmail-123"

    state = json.loads((config.state_dir / "state.json").read_text(encoding="utf-8"))
    assert state["last_gmail_message_id"] == "gmail-123"
    assert state["sender"] == "operator@example.invalid"
    assert state["to"] == ["stakeholder@example.invalid"]
    assert Path(state["last_source_snapshot"]).exists()

    source_text = config.source_path.read_text(encoding="utf-8")
    assert "status: sent-to-stakeholder" in source_text
    assert "last_docx_gmail_message_id: gmail-123" in source_text
    assert "last_docx_path: " in source_text

    service.users.return_value.messages.return_value.send.assert_called_once()


def test_gmail_credential_mismatch_fails_closed_without_state_write(tmp_path: Path) -> None:
    config = _config(tmp_path, send=True, sender="operator@example.invalid")
    service = _gmail_service(profile_email="wrong@example.invalid")

    with (
        mock.patch.object(brief, "_run_pandoc", side_effect=_fake_pandoc),
        mock.patch.object(brief, "_build_gmail_service_from_pass", return_value=service),
    ):
        with pytest.raises(RuntimeError, match="Gmail credential is for"):
            brief.run(config, now=NOW)

    assert not (config.state_dir / "state.json").exists()
    service.users.return_value.messages.return_value.send.assert_not_called()
