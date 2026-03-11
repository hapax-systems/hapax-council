"""Tests for gcalendar_sync — schemas, event formatting, profiler facts."""

from __future__ import annotations


def test_calendar_event_defaults():
    from agents.gcalendar_sync import CalendarEvent

    e = CalendarEvent(
        event_id="abc",
        summary="Standup",
        start="2026-03-10T09:00:00Z",
        end="2026-03-10T09:30:00Z",
    )
    assert e.attendees == []
    assert e.recurring is False
    assert e.location == ""


def test_calendar_sync_state_empty():
    from agents.gcalendar_sync import CalendarSyncState

    s = CalendarSyncState()
    assert s.sync_token == ""
    assert s.events == {}


def test_event_duration_minutes():
    from agents.gcalendar_sync import CalendarEvent

    e = CalendarEvent(
        event_id="abc",
        summary="Meeting",
        start="2026-03-10T09:00:00Z",
        end="2026-03-10T10:30:00Z",
    )
    assert e.duration_minutes == 90


def test_event_duration_all_day():
    from agents.gcalendar_sync import CalendarEvent

    e = CalendarEvent(
        event_id="abc",
        summary="Holiday",
        start="2026-03-10",
        end="2026-03-11",
        all_day=True,
    )
    assert e.duration_minutes == 0


def test_format_event_markdown():
    from agents.gcalendar_sync import CalendarEvent, _format_event_markdown

    e = CalendarEvent(
        event_id="ev123",
        summary="1:1 with Alice",
        start="2026-03-10T09:00:00Z",
        end="2026-03-10T09:30:00Z",
        attendees=["alice@company.com"],
        location="Google Meet",
        recurring=True,
        recurrence_rule="RRULE:FREQ=WEEKLY;BYDAY=MO",
    )
    md = _format_event_markdown(e)
    assert "platform: google" in md
    assert "service: calendar" in md
    assert "source_service: gcalendar" in md
    assert "people: [alice@company.com]" in md
    assert "duration_minutes: 30" in md
    assert "1:1 with Alice" in md
    assert "Google Meet" in md


def test_format_event_no_attendees():
    from agents.gcalendar_sync import CalendarEvent, _format_event_markdown

    e = CalendarEvent(
        event_id="ev456",
        summary="Focus Time",
        start="2026-03-10T14:00:00Z",
        end="2026-03-10T16:00:00Z",
    )
    md = _format_event_markdown(e)
    assert "people: []" in md
    assert "Focus Time" in md
    assert "duration_minutes: 120" in md


def test_generate_calendar_profile_facts():
    from agents.gcalendar_sync import (
        CalendarEvent,
        CalendarSyncState,
        _generate_profile_facts,
    )

    state = CalendarSyncState()
    state.events = {
        "1": CalendarEvent(
            event_id="1",
            summary="1:1 with Alice",
            start="2026-03-10T09:00:00Z",
            end="2026-03-10T09:30:00Z",
            attendees=["alice@company.com"],
            recurring=True,
        ),
        "2": CalendarEvent(
            event_id="2",
            summary="Standup",
            start="2026-03-10T10:00:00Z",
            end="2026-03-10T10:15:00Z",
            attendees=["bob@co.com", "carol@co.com"],
            recurring=True,
        ),
        "3": CalendarEvent(
            event_id="3",
            summary="Focus Time",
            start="2026-03-10T14:00:00Z",
            end="2026-03-10T16:00:00Z",
        ),
    }
    facts = _generate_profile_facts(state)
    assert len(facts) > 0
    dims = {f["dimension"] for f in facts}
    assert "work_patterns" in dims
    assert "communication_patterns" in dims
    assert all(f["confidence"] == 0.95 for f in facts)
