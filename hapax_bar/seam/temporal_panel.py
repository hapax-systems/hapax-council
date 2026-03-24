"""Temporal panel — session duration + next event for seam layer."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from gi.repository import Gtk


class TemporalPanel(Gtk.Box):
    """Shows session duration and next calendar event."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            css_classes=["temporal-panel"],
        )
        self._start_time = time.monotonic()
        self._label = Gtk.Label(xalign=0, css_classes=["metrics-row"])
        self.append(self._label)

    def update(self) -> None:
        elapsed = time.monotonic() - self._start_time
        hours = int(elapsed / 3600)
        minutes = int((elapsed % 3600) / 60)
        session_str = f"Session: {hours}h {minutes:02d}m"

        event_str = ""
        try:
            from shared.calendar_context import CalendarContext

            ctx = CalendarContext()
            meetings = ctx.meetings_in_range(days=1)
            now = datetime.now(UTC)
            for m in meetings:
                start_str = m.start if isinstance(m.start, str) else str(m.start)
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                delta_min = (start_dt - now).total_seconds() / 60
                if delta_min > 0:
                    name = m.summary or "event"
                    event_str = f"  |  Next: {name} in {int(delta_min)}m"
                    break
        except Exception:
            pass

        self._label.set_label(f"{session_str}{event_str}")

    def refresh(self) -> None:
        self.update()
