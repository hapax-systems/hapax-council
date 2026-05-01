"""Tests for shared.calendar_context.CalendarContext.

99-LOC query interface over synced calendar state. Untested before
this commit. Tests construct CalendarSyncState explicitly and pass
it via the ``state=`` parameter so the operator's real
~/.cache/gcalendar-sync/state.json is never read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from agents.gcalendar_sync import CalendarEvent, CalendarSyncState
from shared.calendar_context import CalendarContext


def _event(
    event_id: str,
    start: datetime,
    *,
    duration_min: int = 30,
    attendees: list[str] | None = None,
    summary: str = "test event",
) -> CalendarEvent:
    end = start + timedelta(minutes=duration_min)
    return CalendarEvent(
        event_id=event_id,
        summary=summary,
        start=start.isoformat(),
        end=end.isoformat(),
        attendees=attendees or [],
    )


def _state_with(events: list[CalendarEvent]) -> CalendarSyncState:
    return CalendarSyncState(events={e.event_id: e for e in events})


# ── Construction ───────────────────────────────────────────────────


class TestConstruction:
    def test_explicit_state_used(self) -> None:
        state = _state_with([])
        ctx = CalendarContext(state=state)
        assert ctx._state is state


# ── next_meeting_with ──────────────────────────────────────────────


class TestNextMeetingWith:
    def test_returns_soonest_upcoming(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with(
                [
                    _event(
                        "e1",
                        datetime(2026, 5, 2, 14, 0, tzinfo=UTC),
                        attendees=["alice@example.com"],
                    ),
                    _event(
                        "e2",
                        datetime(2026, 5, 1, 14, 0, tzinfo=UTC),
                        attendees=["alice@example.com"],
                    ),
                    _event(
                        "e3",
                        datetime(2026, 5, 3, 14, 0, tzinfo=UTC),
                        attendees=["alice@example.com"],
                    ),
                ]
            )
            result = CalendarContext(state=state).next_meeting_with("alice@example.com")
            assert result is not None
            assert result.event_id == "e2"

    def test_returns_none_when_no_match(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with(
                [
                    _event(
                        "e1",
                        datetime(2026, 5, 2, 14, 0, tzinfo=UTC),
                        attendees=["bob@example.com"],
                    ),
                ]
            )
            assert CalendarContext(state=state).next_meeting_with("alice@example.com") is None

    def test_email_match_is_case_insensitive(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with(
                [
                    _event(
                        "e1",
                        datetime(2026, 5, 2, 14, 0, tzinfo=UTC),
                        attendees=["Alice@Example.COM"],
                    ),
                ]
            )
            result = CalendarContext(state=state).next_meeting_with("alice@example.com")
            assert result is not None

    def test_past_meetings_excluded(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with(
                [
                    _event(
                        "past",
                        datetime(2026, 4, 30, 14, 0, tzinfo=UTC),
                        attendees=["alice@example.com"],
                    ),
                ]
            )
            assert CalendarContext(state=state).next_meeting_with("alice@example.com") is None


# ── meetings_in_range ──────────────────────────────────────────────


class TestMeetingsInRange:
    def test_default_window_seven_days(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with(
                [
                    _event("near", datetime(2026, 5, 3, 12, 0, tzinfo=UTC)),
                    _event("far", datetime(2026, 5, 20, 12, 0, tzinfo=UTC)),
                    _event("past", datetime(2026, 4, 28, 12, 0, tzinfo=UTC)),
                ]
            )
            results = CalendarContext(state=state).meetings_in_range()
            ids = {e.event_id for e in results}
            assert ids == {"near"}

    def test_custom_window(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with(
                [
                    _event("d1", datetime(2026, 5, 2, 12, 0, tzinfo=UTC)),
                    _event("d10", datetime(2026, 5, 11, 12, 0, tzinfo=UTC)),
                ]
            )
            results = CalendarContext(state=state).meetings_in_range(days=14)
            ids = {e.event_id for e in results}
            assert ids == {"d1", "d10"}

    def test_results_sorted_by_start(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with(
                [
                    _event("late", datetime(2026, 5, 5, 12, 0, tzinfo=UTC)),
                    _event("early", datetime(2026, 5, 2, 12, 0, tzinfo=UTC)),
                    _event("mid", datetime(2026, 5, 3, 12, 0, tzinfo=UTC)),
                ]
            )
            results = CalendarContext(state=state).meetings_in_range()
            ids = [e.event_id for e in results]
            assert ids == ["early", "mid", "late"]


# ── meeting_count_today + is_high_meeting_day ─────────────────────


class TestMeetingCountToday:
    def test_counts_only_today_remaining(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with(
                [
                    _event("today_rem", now + timedelta(hours=2)),
                    _event("today_late", now + timedelta(hours=8)),
                    _event("today_past", now - timedelta(hours=2)),
                    _event("tomorrow", now + timedelta(days=1)),
                ]
            )
            assert CalendarContext(state=state).meeting_count_today() == 2

    def test_high_day_threshold(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with([_event(f"e{i}", now + timedelta(hours=i)) for i in range(1, 5)])
            ctx = CalendarContext(state=state)
            assert ctx.is_high_meeting_day(threshold=3)
            assert not ctx.is_high_meeting_day(threshold=10)


# ── meetings_needing_prep ──────────────────────────────────────────


class TestMeetingsNeedingPrep:
    def test_returns_meetings_with_attendees_in_window(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with(
                [
                    _event(
                        "1on1",
                        now + timedelta(hours=12),
                        attendees=["a@x.com"],
                    ),
                    _event("focus_block", now + timedelta(hours=24)),
                ]
            )
            results = CalendarContext(state=state).meetings_needing_prep(hours=48)
            ids = {e.event_id for e in results}
            assert ids == {"1on1"}

    def test_outside_window_excluded(self) -> None:
        with patch("shared.calendar_context.datetime") as mock_dt:
            now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            state = _state_with(
                [
                    _event("far", now + timedelta(hours=72), attendees=["a@x.com"]),
                ]
            )
            assert CalendarContext(state=state).meetings_needing_prep(hours=48) == []
