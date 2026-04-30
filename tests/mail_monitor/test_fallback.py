"""Tests for the mail-monitor Pub/Sub outage fallback runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from agents.mail_monitor import fallback


def _write_last_push(path: Path, at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"history_id": "123", "last_push_at": at.isoformat()}),
        encoding="utf-8",
    )


def test_fallback_noops_when_pubsub_push_is_fresh(tmp_path: Path) -> None:
    now = datetime(2026, 4, 30, 11, 30, tzinfo=UTC)
    last_push = tmp_path / "last-push.json"
    _write_last_push(last_push, now - timedelta(minutes=30))

    with (
        mock.patch.object(fallback, "load_credentials") as load_credentials,
        mock.patch.object(fallback, "process_history") as process_history,
    ):
        result = fallback.run_once(last_push_path=last_push, now=now)

    assert result == fallback.FallbackRun(result="fresh", reason="fresh")
    load_credentials.assert_not_called()
    process_history.assert_not_called()


def test_fallback_missing_marker_skips_cleanly_without_credentials(tmp_path: Path) -> None:
    with mock.patch.object(fallback, "load_credentials", return_value=None):
        result = fallback.run_once(
            last_push_path=tmp_path / "missing-last-push.json",
            now=datetime(2026, 4, 30, 11, 30, tzinfo=UTC),
        )

    assert result == fallback.FallbackRun(
        result="no_credentials",
        reason="missing_last_push",
    )


def test_fallback_polls_stale_push_with_current_history_id_and_hapax_labels(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 4, 30, 11, 30, tzinfo=UTC)
    last_push = tmp_path / "last-push.json"
    cursor = tmp_path / "cursor.json"
    seen = tmp_path / "seen.json"
    pending = tmp_path / "pending.jsonl"
    lock = tmp_path / "mail-monitor.lock"
    _write_last_push(last_push, now - timedelta(minutes=61))

    service = mock.Mock()
    service.users.return_value.getProfile.return_value.execute.return_value = {
        "historyId": "777",
    }
    label_ids = {"Hapax/Verify": "L_verify", "Hapax/Suppress": "L_suppress"}

    with (
        mock.patch.object(fallback, "load_credentials", return_value=mock.Mock()) as load,
        mock.patch.object(fallback, "build_gmail_service", return_value=service) as build,
        mock.patch.object(fallback, "bootstrap_labels", return_value=label_ids) as labels,
        mock.patch.object(fallback, "process_history", return_value=3) as process_history,
    ):
        result = fallback.run_once(
            last_push_path=last_push,
            cursor_path=cursor,
            seen_set_path=seen,
            pending_actions_path=pending,
            lock_path=lock,
            now=now,
        )

    assert result == fallback.FallbackRun(
        result="stale_processed",
        reason="stale_last_push",
        processed=3,
    )
    load.assert_called_once_with()
    build.assert_called_once()
    labels.assert_called_once_with(service)
    process_history.assert_called_once_with(
        service,
        "777",
        label_ids_by_name=label_ids,
        cursor_path=cursor,
        last_push_path=last_push,
        seen_set_path=seen,
        pending_actions_path=pending,
        lock_path=lock,
        now=now,
        record_last_push=False,
    )


def test_fallback_treats_malformed_last_push_as_poll_needed(tmp_path: Path) -> None:
    last_push = tmp_path / "last-push.json"
    last_push.write_text("{not-json", encoding="utf-8")

    assert (
        fallback.fallback_poll_reason(
            last_push_path=last_push,
            now=datetime(2026, 4, 30, 11, 30, tzinfo=UTC),
        )
        == "malformed_last_push"
    )
