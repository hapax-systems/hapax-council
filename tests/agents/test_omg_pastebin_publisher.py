"""Tests for agents/omg_pastebin_publisher — ytb-OMG6 Phase A."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest  # noqa: TC002

from agents.omg_pastebin_publisher.publisher import (
    PastebinArtifactPublisher,
    build_chronicle_digest,
    build_chronicle_slug,
)


def _event(
    ts: str, *, salience: float = 0.8, summary: str = "something", source: str = "dir"
) -> dict:
    return {"ts": ts, "salience": salience, "summary": summary, "source": source}


class TestBuildChronicleSlug:
    def test_slug_is_deterministic_per_iso_week(self) -> None:
        a = build_chronicle_slug(date(2026, 4, 20))
        b = build_chronicle_slug(date(2026, 4, 20))
        assert a == b

    def test_slug_shape(self) -> None:
        slug = build_chronicle_slug(date(2026, 4, 20))
        # ISO week 17 of 2026 (Monday 2026-04-20).
        assert slug.startswith("chronicle-2026-w")
        assert "17" in slug

    def test_adjacent_weeks_have_different_slugs(self) -> None:
        a = build_chronicle_slug(date(2026, 4, 20))  # ISO week 17
        b = build_chronicle_slug(date(2026, 4, 27))  # ISO week 18
        assert a != b


class TestBuildChronicleDigest:
    def test_empty_events_returns_empty_string(self) -> None:
        result = build_chronicle_digest(events=[], week_start=date(2026, 4, 20))
        assert result == ""

    def test_includes_in_window_high_salience(self) -> None:
        events = [
            _event("2026-04-20T10:00:00Z", salience=0.9, summary="within window high-sal"),
            _event("2026-04-21T14:30:00Z", salience=0.85, summary="also within"),
            _event("2026-04-27T01:00:00Z", salience=0.95, summary="next week (excluded)"),
        ]
        result = build_chronicle_digest(events=events, week_start=date(2026, 4, 20))
        assert "within window" in result
        assert "also within" in result
        assert "next week" not in result

    def test_excludes_below_salience(self) -> None:
        events = [
            _event("2026-04-20T10:00:00Z", salience=0.3, summary="low salience"),
            _event("2026-04-21T10:00:00Z", salience=0.9, summary="high salience"),
        ]
        result = build_chronicle_digest(
            events=events, week_start=date(2026, 4, 20), min_salience=0.7
        )
        assert "high salience" in result
        assert "low salience" not in result

    def test_sorted_chronologically(self) -> None:
        events = [
            _event("2026-04-21T14:00:00Z", summary="second"),
            _event("2026-04-20T10:00:00Z", summary="first"),
            _event("2026-04-22T08:00:00Z", summary="third"),
        ]
        result = build_chronicle_digest(events=events, week_start=date(2026, 4, 20))
        idx_first = result.index("first")
        idx_second = result.index("second")
        idx_third = result.index("third")
        assert idx_first < idx_second < idx_third

    def test_malformed_ts_skipped(self) -> None:
        events = [
            _event("not-a-date", summary="bogus"),
            _event("2026-04-20T10:00:00Z", summary="valid"),
        ]
        result = build_chronicle_digest(events=events, week_start=date(2026, 4, 20))
        assert "valid" in result
        assert "bogus" not in result

    def test_header_includes_week_identifier(self) -> None:
        result = build_chronicle_digest(
            events=[_event("2026-04-20T10:00:00Z")],
            week_start=date(2026, 4, 20),
        )
        assert "2026" in result
        assert "week 17" in result


class TestPublisher:
    def _client(self) -> MagicMock:
        c = MagicMock()
        c.enabled = True
        c.set_paste.return_value = {"request": {"statusCode": 200}, "response": {"slug": "x"}}
        return c

    def _events_with_content(self) -> list[dict]:
        return [_event("2026-04-20T10:00:00Z", salience=0.9, summary="a moment")]

    def test_publish_current_week_calls_set_paste(self, tmp_path: Path) -> None:
        client = self._client()
        publisher = PastebinArtifactPublisher(
            client=client,
            state_file=tmp_path / "state.json",
            read_events=self._events_with_content,
            now_fn=lambda: datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        )
        outcome = publisher.publish_current_week()
        assert outcome == "published"
        client.set_paste.assert_called_once()
        call = client.set_paste.call_args
        assert call.kwargs["title"].startswith("chronicle-2026-w")
        assert call.kwargs["listed"] is True

    def test_hash_dedup_second_run_returns_unchanged(self, tmp_path: Path) -> None:
        client = self._client()
        publisher = PastebinArtifactPublisher(
            client=client,
            state_file=tmp_path / "state.json",
            read_events=self._events_with_content,
            now_fn=lambda: datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        )
        publisher.publish_current_week()
        second = publisher.publish_current_week()
        assert second == "unchanged"
        assert client.set_paste.call_count == 1

    def test_empty_events_returns_empty(self, tmp_path: Path) -> None:
        client = self._client()
        publisher = PastebinArtifactPublisher(
            client=client,
            state_file=tmp_path / "state.json",
            read_events=lambda: [],
            now_fn=lambda: datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        )
        outcome = publisher.publish_current_week()
        assert outcome == "empty"
        client.set_paste.assert_not_called()

    def test_dry_run_does_not_call_client(self, tmp_path: Path) -> None:
        client = self._client()
        publisher = PastebinArtifactPublisher(
            client=client,
            state_file=tmp_path / "state.json",
            read_events=self._events_with_content,
            now_fn=lambda: datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        )
        outcome = publisher.publish_current_week(dry_run=True)
        assert outcome == "dry-run"
        client.set_paste.assert_not_called()

    def test_disabled_client_skips(self, tmp_path: Path) -> None:
        client = MagicMock()
        client.enabled = False
        publisher = PastebinArtifactPublisher(
            client=client,
            state_file=tmp_path / "state.json",
            read_events=self._events_with_content,
            now_fn=lambda: datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        )
        outcome = publisher.publish_current_week()
        assert outcome == "client-disabled"

    def test_allowlist_deny_short_circuits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from agents.omg_pastebin_publisher import publisher as pub_mod

        def _deny(*a, **kw):
            from shared.governance.publication_allowlist import AllowlistResult

            return AllowlistResult(decision="deny", payload={}, reason="stub")

        monkeypatch.setattr(pub_mod, "allowlist_check", _deny)

        client = self._client()
        publisher = PastebinArtifactPublisher(
            client=client,
            state_file=tmp_path / "state.json",
            read_events=self._events_with_content,
            now_fn=lambda: datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        )
        outcome = publisher.publish_current_week()
        assert outcome == "allowlist-denied"
        client.set_paste.assert_not_called()

    def test_failed_post_returns_failed(self, tmp_path: Path) -> None:
        client = self._client()
        client.set_paste.return_value = None
        publisher = PastebinArtifactPublisher(
            client=client,
            state_file=tmp_path / "state.json",
            read_events=self._events_with_content,
            now_fn=lambda: datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        )
        outcome = publisher.publish_current_week()
        assert outcome == "failed"

    def test_content_change_triggers_republish(self, tmp_path: Path) -> None:
        client = self._client()
        events_ref = {"events": self._events_with_content()}
        publisher = PastebinArtifactPublisher(
            client=client,
            state_file=tmp_path / "state.json",
            read_events=lambda: events_ref["events"],
            now_fn=lambda: datetime(2026, 4, 20, 12, 0, 0, tzinfo=UTC),
        )
        publisher.publish_current_week()
        # Add another event in-window → content hash changes → republish.
        events_ref["events"].append(
            _event("2026-04-22T10:00:00Z", salience=0.85, summary="new moment")
        )
        second = publisher.publish_current_week()
        assert second == "published"
        assert client.set_paste.call_count == 2
