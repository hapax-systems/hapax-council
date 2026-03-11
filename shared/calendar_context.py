"""Calendar context query interface for Hapax agents.

Reads synced calendar state — no Google API dependency.
Agents import this to answer scheduling questions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "gcalendar-sync"
STATE_FILE = CACHE_DIR / "state.json"


class CalendarContext:
    """Query interface over synced calendar state."""

    def __init__(self, state=None):
        """Initialize from explicit state or load from disk."""
        if state is not None:
            self._state = state
        else:
            from agents.gcalendar_sync import CalendarSyncState

            if STATE_FILE.exists():
                try:
                    self._state = CalendarSyncState.model_validate_json(STATE_FILE.read_text())
                except Exception:
                    self._state = CalendarSyncState()
            else:
                self._state = CalendarSyncState()

    def _parse_dt(self, dt_str: str) -> datetime | None:
        """Parse ISO datetime string."""
        try:
            return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def next_meeting_with(self, email: str) -> object | None:
        """Find the next upcoming event with a specific attendee."""
        now = datetime.now(UTC)
        candidates = []
        for e in self._state.events.values():
            if email.lower() in [a.lower() for a in e.attendees]:
                dt = self._parse_dt(e.start)
                if dt and dt > now:
                    candidates.append((dt, e))
        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]
        return None

    def meetings_in_range(self, days: int = 7) -> list:
        """Return events within the next N days, sorted by start time."""
        now = datetime.now(UTC)
        cutoff = now + timedelta(days=days)
        result = []
        for e in self._state.events.values():
            dt = self._parse_dt(e.start)
            if dt and now <= dt <= cutoff:
                result.append(e)
        result.sort(key=lambda e: e.start)
        return result

    def meeting_count_today(self) -> int:
        """Count meetings remaining today."""
        now = datetime.now(UTC)
        end_of_day = now.replace(hour=23, minute=59, second=59)
        count = 0
        for e in self._state.events.values():
            dt = self._parse_dt(e.start)
            if dt and now <= dt <= end_of_day:
                count += 1
        return count

    def is_high_meeting_day(self, threshold: int = 3) -> bool:
        """Check if today has more meetings than threshold."""
        return self.meeting_count_today() >= threshold

    def meetings_needing_prep(self, hours: int = 48) -> list:
        """Find meetings within N hours that may need prep.

        Returns meetings with attendees (likely 1:1s or group meetings,
        not focus blocks).
        """
        now = datetime.now(UTC)
        cutoff = now + timedelta(hours=hours)
        result = []
        for e in self._state.events.values():
            dt = self._parse_dt(e.start)
            if dt and now <= dt <= cutoff and e.attendees:
                result.append(e)
        result.sort(key=lambda e: e.start)
        return result
