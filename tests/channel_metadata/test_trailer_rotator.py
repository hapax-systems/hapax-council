"""Tests for ``agents.channel_metadata.trailer_rotator``."""

from __future__ import annotations

import json
from unittest import mock

from prometheus_client import CollectorRegistry

from agents.channel_metadata.trailer_rotator import (
    EVENT_TYPE,
    QUOTA_COST_HINT,
    TrailerRotator,
)


def _write_events(path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")


def _make_rotator(
    *,
    event_path,
    cursor_path,
    client=None,
    dry_run: bool = False,
) -> tuple[TrailerRotator, mock.Mock]:
    if client is None:
        client = mock.Mock()
        client.enabled = True
        client.execute.return_value = {"id": "UC-test"}
    rotator = TrailerRotator(
        client=client,
        event_path=event_path,
        cursor_path=cursor_path,
        registry=CollectorRegistry(),
        dry_run=dry_run,
    )
    return rotator, client


# ── Cursor + tail behaviour ──────────────────────────────────────────


class TestCursor:
    def test_missing_event_file_handles_cleanly(self, tmp_path):
        rotator, _ = _make_rotator(
            event_path=tmp_path / "absent.jsonl",
            cursor_path=tmp_path / "cursor.txt",
        )
        assert rotator.run_once() == 0

    def test_empty_event_file_handles_cleanly(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        bus.write_text("", encoding="utf-8")
        rotator, _ = _make_rotator(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
        )
        assert rotator.run_once() == 0

    def test_persists_cursor_after_processing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC-test")
        bus = tmp_path / "events.jsonl"
        cursor = tmp_path / "cursor.txt"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-1"}])

        rotator, _ = _make_rotator(event_path=bus, cursor_path=cursor)
        rotator.run_once()
        assert cursor.exists()
        offset = int(cursor.read_text())
        # cursor should be at end-of-file after consuming the only line
        assert offset == bus.stat().st_size

    def test_cursor_resume_skips_already_processed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC-test")
        bus = tmp_path / "events.jsonl"
        cursor = tmp_path / "cursor.txt"
        _write_events(
            bus,
            [
                {"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-1"},
                {"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-2"},
            ],
        )

        rotator, client = _make_rotator(event_path=bus, cursor_path=cursor)
        rotator.run_once()  # processes both
        assert client.execute.call_count == 2

        # Subsequent run_once with no new events should be a no-op.
        rotator.run_once()
        assert client.execute.call_count == 2

    def test_malformed_event_line_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC-test")
        bus = tmp_path / "events.jsonl"
        bus.write_text(
            "not-json\n"
            + json.dumps({"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-1"})
            + "\n",
            encoding="utf-8",
        )
        rotator, client = _make_rotator(event_path=bus, cursor_path=tmp_path / "cursor.txt")
        rotator.run_once()
        # Should still process the well-formed line.
        assert client.execute.call_count == 1


# ── Event filtering + apply ──────────────────────────────────────────


class TestApply:
    def test_skips_non_broadcast_rotated_events(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC-test")
        bus = tmp_path / "events.jsonl"
        _write_events(
            bus,
            [
                {"event_type": "stream_started"},
                {"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-1"},
                {"event_type": "rotation_failed"},
            ],
        )
        rotator, client = _make_rotator(event_path=bus, cursor_path=tmp_path / "cursor.txt")
        rotator.run_once()
        assert client.execute.call_count == 1

    def test_skips_event_missing_incoming_broadcast_id(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE}])
        rotator, client = _make_rotator(event_path=bus, cursor_path=tmp_path / "cursor.txt")
        rotator.run_once()
        client.execute.assert_not_called()

    def test_disabled_client_does_not_call(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC-test")
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-1"}])
        client = mock.Mock()
        client.enabled = False
        rotator, _ = _make_rotator(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client=client,
        )
        rotator.run_once()
        client.execute.assert_not_called()


# ── Dry-run safety ───────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_does_not_call_execute(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-1"}])
        rotator, client = _make_rotator(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            dry_run=True,
        )
        rotator.run_once()
        client.execute.assert_not_called()

    def test_dry_run_still_advances_cursor(self, tmp_path):
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-1"}])
        cursor = tmp_path / "cursor.txt"
        rotator, _ = _make_rotator(event_path=bus, cursor_path=cursor, dry_run=True)
        rotator.run_once()
        assert cursor.exists()
        assert int(cursor.read_text()) == bus.stat().st_size


# ── Allowlist gate ───────────────────────────────────────────────────


class TestAllowlist:
    def test_allowlist_deny_short_circuits_call(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC-test")
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-1"}])
        rotator, client = _make_rotator(event_path=bus, cursor_path=tmp_path / "cursor.txt")

        # Patch the allowlist module the rotator imported to force DENY
        # without touching the real contracts directory.
        from agents.channel_metadata import trailer_rotator as mod

        denied = mock.Mock()
        denied.decision = "deny"
        denied.reason = "test override"
        with mock.patch.object(mod, "allowlist_check", return_value=denied):
            rotator.run_once()
        client.execute.assert_not_called()


# ── Real API call shape ──────────────────────────────────────────────


class TestApiCall:
    def test_calls_channels_update_with_correct_body(self, tmp_path, monkeypatch):
        monkeypatch.setenv("YOUTUBE_CHANNEL_ID", "UC-real-channel")
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])

        client = mock.Mock()
        client.enabled = True
        # client.yt is what `.channels()` is called on.
        update_request = mock.Mock()
        client.yt.channels.return_value.update.return_value = update_request
        client.execute.return_value = {"id": "UC-real-channel"}

        rotator, _ = _make_rotator(
            event_path=bus,
            cursor_path=tmp_path / "cursor.txt",
            client=client,
        )
        rotator.run_once()

        client.yt.channels.assert_called_once()
        client.yt.channels.return_value.update.assert_called_once_with(
            part="brandingSettings",
            body={
                "id": "UC-real-channel",
                "brandingSettings": {"channel": {"unsubscribedTrailer": "vid-A"}},
            },
        )
        client.execute.assert_called_once_with(
            update_request,
            endpoint="channels.update.brandingSettings",
            quota_cost_hint=QUOTA_COST_HINT,
        )

    def test_missing_channel_id_env_raises(self, tmp_path, monkeypatch):
        monkeypatch.delenv("YOUTUBE_CHANNEL_ID", raising=False)
        bus = tmp_path / "events.jsonl"
        _write_events(bus, [{"event_type": EVENT_TYPE, "incoming_broadcast_id": "vid-A"}])
        rotator, client = _make_rotator(event_path=bus, cursor_path=tmp_path / "cursor.txt")

        # The exception is caught inside _call_channels_update and
        # logged; the rotator returns the "error" result label rather
        # than crashing the daemon loop.
        rotator.run_once()
        assert client.execute.call_count == 0
