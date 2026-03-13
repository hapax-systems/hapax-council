"""Tests for shared calendar context query module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def _make_state():
    """Build a test CalendarSyncState."""
    from agents.gcalendar_sync import CalendarEvent, CalendarSyncState

    now = datetime.now(UTC)
    tomorrow = (now + timedelta(days=1)).isoformat()
    tomorrow_end = (now + timedelta(days=1, minutes=30)).isoformat()
    next_week = (now + timedelta(days=7)).isoformat()
    next_week_end = (now + timedelta(days=7, minutes=60)).isoformat()

    return CalendarSyncState(
        events={
            "1": CalendarEvent(
                event_id="1",
                summary="1:1 with Alice",
                start=tomorrow,
                end=tomorrow_end,
                attendees=["alice@company.com"],
            ),
            "2": CalendarEvent(
                event_id="2",
                summary="Team Standup",
                start=tomorrow,
                end=tomorrow_end,
                attendees=["bob@co.com", "carol@co.com"],
            ),
            "3": CalendarEvent(
                event_id="3",
                summary="Planning",
                start=next_week,
                end=next_week_end,
                attendees=["alice@company.com", "dave@co.com"],
            ),
        },
        last_sync=now.timestamp(),
    )


def test_next_meeting_with(tmp_path):
    from shared.calendar_context import CalendarContext

    state = _make_state()
    ctx = CalendarContext(state)
    meeting = ctx.next_meeting_with("alice@company.com")
    assert meeting is not None
    assert meeting.summary == "1:1 with Alice"


def test_next_meeting_with_unknown(tmp_path):
    from shared.calendar_context import CalendarContext

    state = _make_state()
    ctx = CalendarContext(state)
    assert ctx.next_meeting_with("nobody@example.com") is None


def test_meetings_in_range():
    from shared.calendar_context import CalendarContext

    state = _make_state()
    ctx = CalendarContext(state)
    meetings = ctx.meetings_in_range(days=3)
    assert len(meetings) == 2  # tomorrow's meetings, not next week


def test_meeting_count_today():
    from agents.gcalendar_sync import CalendarEvent, CalendarSyncState
    from shared.calendar_context import CalendarContext

    now = datetime.now(UTC)
    # Ensure the event is both in the future AND before end-of-day UTC, so
    # it counts regardless of when the test runs (the original +1h/+2h
    # approach fails when CI runs near midnight UTC).
    end_of_day = now.replace(hour=23, minute=59, second=59)
    remaining = (end_of_day - now).total_seconds()
    # Place event 1/3 and 2/3 of the way through the remaining day
    today_start = (now + timedelta(seconds=remaining / 3)).isoformat()
    today_end = (now + timedelta(seconds=2 * remaining / 3)).isoformat()
    state = CalendarSyncState(
        events={
            "t1": CalendarEvent(event_id="t1", summary="Today", start=today_start, end=today_end),
        }
    )
    ctx = CalendarContext(state)
    assert ctx.meeting_count_today() >= 1
