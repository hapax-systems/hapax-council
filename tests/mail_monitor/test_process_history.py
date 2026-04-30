"""Tests for the Gmail history processing loop."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from agents.mail_monitor import runner


class _Request:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response

    def execute(self) -> dict[str, Any]:
        return self._response


class _History:
    def __init__(self, pages_by_label: dict[str, list[dict[str, Any]]]) -> None:
        self.pages_by_label = pages_by_label
        self.calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> _Request:
        self.calls.append(kwargs)
        label_id = kwargs["labelId"]
        return _Request(self.pages_by_label[label_id].pop(0))


class _Messages:
    def __init__(self, messages: dict[str, dict[str, Any]]) -> None:
        self.messages = messages
        self.get_calls: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> _Request:
        self.get_calls.append(kwargs)
        return _Request(self.messages[kwargs["id"]])


class _Users:
    def __init__(self, history: _History, messages: _Messages) -> None:
        self._history = history
        self._messages = messages

    def history(self) -> _History:
        return self._history

    def messages(self) -> _Messages:
        return self._messages


class _Service:
    def __init__(self, history: _History, messages: _Messages) -> None:
        self.users_resource = _Users(history, messages)

    def users(self) -> _Users:
        return self.users_resource


def _body_data(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _message(
    message_id: str,
    label_id: str,
    *,
    rfc_message_id: str | None = None,
    body: str = "plain body",
    extra_headers: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    headers = [
        {"name": "From", "value": "sender@example.com"},
        {"name": "Subject", "value": "A subject"},
        {"name": "Message-ID", "value": rfc_message_id or f"<{message_id}@example.com>"},
        {"name": "References", "value": "<hapax-thread@example.com>"},
    ]
    if extra_headers:
        headers.extend(extra_headers)
    return {
        "id": message_id,
        "labelIds": [label_id],
        "payload": {
            "mimeType": "text/plain",
            "headers": headers,
            "body": {"data": _body_data(body)},
        },
    }


def _paths(tmp_path: Path) -> dict[str, Path]:
    return {
        "cursor_path": tmp_path / "cursor.json",
        "last_push_path": tmp_path / "last-push.json",
        "seen_set_path": tmp_path / "seen-message-ids.json",
        "pending_actions_path": tmp_path / "pending-actions.jsonl",
        "lock_path": tmp_path / "mail-monitor.lock",
    }


def _write_pending_actions(path: Path, records: list[dict[str, Any] | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for record in records:
            if isinstance(record, str):
                fp.write(record + "\n")
            else:
                fp.write(json.dumps(record) + "\n")


def test_process_history_reads_each_hapax_label_and_dispatches_once(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    cursor_path = paths["cursor_path"]
    cursor_path.write_text(json.dumps({"historyId": "100"}), encoding="utf-8")
    history = _History(
        {
            "L_v": [
                {
                    "history": [
                        {"messagesAdded": [{"message": {"id": "M1"}}]},
                        {"labelsAdded": [{"message": {"id": "M1"}}]},
                    ]
                }
            ],
            "L_o": [{"history": [{"messagesAdded": [{"message": {"id": "M2"}}]}]}],
        }
    )
    messages = _Messages({"M1": _message("M1", "L_v"), "M2": _message("M2", "L_o")})
    service = _Service(history, messages)

    with mock.patch("agents.mail_monitor.runner.dispatch_message") as dispatch:
        processed = runner.process_history(
            service,
            "200",
            label_ids_by_name={"Hapax/Verify": "L_v", "Hapax/Operational": "L_o"},
            **paths,
            now=datetime(2026, 4, 28, 5, 30, tzinfo=UTC),
        )

    assert processed == 2
    assert [call["labelId"] for call in history.calls] == ["L_v", "L_o"]
    assert all(call["startHistoryId"] == "100" for call in history.calls)
    assert all(call["historyTypes"] == ["messageAdded", "labelAdded"] for call in history.calls)
    assert [call["id"] for call in messages.get_calls] == ["M1", "M2"]
    first_enriched = dispatch.call_args_list[0].args[1]
    assert first_enriched["label_names"] == ["Hapax/Verify"]
    assert first_enriched["label_ids_by_name"] == {
        "Hapax/Verify": "L_v",
        "Hapax/Operational": "L_o",
    }
    assert first_enriched["sender"] == "sender@example.com"
    assert first_enriched["subject"] == "A subject"
    assert first_enriched["body_text"] == "plain body"
    assert first_enriched["replies_to_hapax_thread"] is True
    cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
    assert cursor["history_id"] == "200"
    assert cursor["historyId"] == "200"
    assert cursor["last_push_at"] == "2026-04-28T05:30:00+00:00"
    assert json.loads(paths["last_push_path"].read_text(encoding="utf-8")) == {
        "history_id": "200",
        "last_push_at": "2026-04-28T05:30:00+00:00",
    }


def test_process_history_enriches_pending_action_correlation(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths["cursor_path"].write_text(json.dumps({"historyId": "100"}), encoding="utf-8")
    processed_at = datetime(2026, 4, 28, 5, 30, tzinfo=UTC)
    _write_pending_actions(
        paths["pending_actions_path"],
        [
            {
                "sender_domain": "example.com",
                "ts": processed_at.timestamp() - 60,
                "action": "deposit",
                "artefact_id": "pub-001",
            }
        ],
    )
    history = _History({"L_v": [{"history": [{"messagesAdded": [{"message": {"id": "M1"}}]}]}]})
    messages = _Messages(
        {
            "M1": _message(
                "M1",
                "L_v",
                body="Confirm at https://zenodo.org/account/verify?token=abc",
                extra_headers=[
                    {"name": "Return-Path", "value": "<sender@example.com>"},
                    {
                        "name": "Authentication-Results",
                        "value": "mx; dkim=pass; spf=pass; dmarc=pass",
                    },
                ],
            )
        }
    )
    service = _Service(history, messages)

    with mock.patch("agents.mail_monitor.runner.dispatch_message") as dispatch:
        processed = runner.process_history(
            service,
            "200",
            label_ids_by_name={"Hapax/Verify": "L_v"},
            **paths,
            now=processed_at,
        )

    assert processed == 1
    enriched = dispatch.call_args.args[1]
    assert enriched["envelope_from"] == "sender@example.com"
    assert enriched["headers"]["authentication-results"] == "mx; dkim=pass; spf=pass; dmarc=pass"
    assert enriched["outbound_correlation_hit"] is True
    assert enriched["auto_accept_candidate"] is True
    assert enriched["artefact_id"] == "pub-001"


def test_process_history_ignores_expired_and_malformed_pending_actions(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths["cursor_path"].write_text(json.dumps({"historyId": "100"}), encoding="utf-8")
    processed_at = datetime(2026, 4, 28, 5, 30, tzinfo=UTC)
    _write_pending_actions(
        paths["pending_actions_path"],
        [
            "{not-json",
            {
                "sender_domain": "example.com",
                "ts": processed_at.timestamp() - 3600,
                "artefact_id": "expired",
            },
            {
                "sender_domain": "other.example",
                "ts": processed_at.timestamp() - 60,
                "artefact_id": "wrong-domain",
            },
        ],
    )
    history = _History({"L_v": [{"history": [{"messagesAdded": [{"message": {"id": "M1"}}]}]}]})
    messages = _Messages({"M1": _message("M1", "L_v")})
    service = _Service(history, messages)

    with mock.patch("agents.mail_monitor.runner.dispatch_message") as dispatch:
        processed = runner.process_history(
            service,
            "200",
            label_ids_by_name={"Hapax/Verify": "L_v"},
            **paths,
            now=processed_at,
        )

    assert processed == 1
    enriched = dispatch.call_args.args[1]
    assert enriched["outbound_correlation_hit"] is False
    assert enriched["auto_accept_candidate"] is False
    assert "artefact_id" not in enriched


def test_process_history_uses_watch_history_id_without_runtime_cursor(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    history = _History({"L_v": [{"history": []}]})
    messages = _Messages({})
    service = _Service(history, messages)

    with mock.patch(
        "agents.mail_monitor.runner.load_watch_state",
        return_value={"historyId": "250", "expiration": "999"},
    ):
        processed = runner.process_history(
            service,
            "300",
            label_ids_by_name={"Hapax/Verify": "L_v"},
            **paths,
        )

    assert processed == 0
    assert history.calls[0]["startHistoryId"] == "250"


def test_process_history_uses_notification_history_id_as_last_resort(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    history = _History({"L_v": [{"history": []}]})
    messages = _Messages({})
    service = _Service(history, messages)

    with mock.patch("agents.mail_monitor.runner.load_watch_state", return_value=None):
        processed = runner.process_history(
            service,
            "300",
            label_ids_by_name={"Hapax/Verify": "L_v"},
            **paths,
        )

    assert processed == 0
    assert history.calls[0]["startHistoryId"] == "300"


def test_process_history_persists_hashed_seen_set_and_skips_duplicate_message_ids(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    paths["cursor_path"].write_text(json.dumps({"history_id": "100"}), encoding="utf-8")
    shared_rfc_id = "<shared-message@example.com>"
    history = _History(
        {
            "L_v": [{"history": [{"messagesAdded": [{"message": {"id": "M1"}}]}]}],
            "L_o": [{"history": [{"messagesAdded": [{"message": {"id": "M2"}}]}]}],
        }
    )
    messages = _Messages(
        {
            "M1": _message("M1", "L_v", rfc_message_id=shared_rfc_id),
            "M2": _message("M2", "L_o", rfc_message_id=shared_rfc_id),
        }
    )
    service = _Service(history, messages)

    with mock.patch("agents.mail_monitor.runner.dispatch_message") as dispatch:
        processed = runner.process_history(
            service,
            "200",
            label_ids_by_name={"Hapax/Verify": "L_v", "Hapax/Operational": "L_o"},
            **paths,
            now=datetime(2026, 4, 28, 6, 0, tzinfo=UTC),
        )

    digest = hashlib.sha1(shared_rfc_id.encode("utf-8")).hexdigest()
    seen = json.loads(paths["seen_set_path"].read_text(encoding="utf-8"))
    assert processed == 1
    assert dispatch.call_count == 1
    assert seen == {digest: "2026-04-28T06:00:00+00:00"}
    assert shared_rfc_id not in paths["seen_set_path"].read_text(encoding="utf-8")


def test_process_history_respects_cross_process_lock(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    lock_path = paths["lock_path"]
    lock_path.touch()
    entered = threading.Event()
    result: list[int] = []

    def _run() -> None:
        result.append(
            runner.process_history(
                mock.Mock(),
                "200",
                label_ids_by_name={"Hapax/Verify": "L_v"},
                **paths,
            )
        )
        entered.set()

    with mock.patch("agents.mail_monitor.runner._process_history_unlocked", return_value=7):
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            worker = threading.Thread(target=_run)
            worker.start()
            time.sleep(0.05)
            assert entered.is_set() is False
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        worker.join(timeout=2)

    assert entered.is_set() is True
    assert result == [7]
