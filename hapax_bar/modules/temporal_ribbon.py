"""Temporal ribbon — circadian gradient, session duration, calendar countdown."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import cairo  # noqa: TC002
from gi.repository import GLib, Gtk


class TemporalRibbon(Gtk.DrawingArea):
    """Replaces clock with richer temporal encoding.

    Shows circadian color gradient + session duration fill + event countdown.
    Clock time available at the right end.
    """

    def __init__(self) -> None:
        super().__init__(css_classes=["module", "temporal-ribbon"])
        self.set_content_width(80)
        self.set_content_height(24)

        self._start_time = time.monotonic()
        self._next_event_minutes: float | None = None
        self._next_event_name: str = ""
        self._use_short_format = True

        self.set_draw_func(self._draw)

        # Redraw every 30s (temporal changes slowly)
        GLib.timeout_add(30_000, self._tick)
        # Poll calendar every 60s
        GLib.timeout_add(60_000, self._poll_calendar)
        self._poll_calendar()

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_click)
        self.add_controller(click)

    def _tick(self, *_a: object) -> bool:
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _poll_calendar(self, *_a: object) -> bool:
        """Try to read next event from CalendarContext."""
        try:
            from shared.calendar_context import CalendarContext

            ctx = CalendarContext()
            meetings = ctx.meetings_in_range(days=1)
            now = datetime.now(UTC)
            for m in meetings:
                start_str = m.start if isinstance(m.start, str) else str(m.start)
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                delta = (start_dt - now).total_seconds() / 60
                if delta > 0:
                    self._next_event_minutes = delta
                    self._next_event_name = m.summary or "event"
                    return GLib.SOURCE_CONTINUE
            self._next_event_minutes = None
        except Exception:
            self._next_event_minutes = None
        return GLib.SOURCE_CONTINUE

    def _draw(
        self, _area: Gtk.DrawingArea, cr: cairo.Context, w: int, h: int, _data: object
    ) -> None:
        now = datetime.now()
        hour = now.hour + now.minute / 60.0

        # Circadian gradient: cool morning → warm afternoon → dim evening
        # Map 0-24h to color temperature
        if hour < 6:
            r, g, b = 0.08, 0.06, 0.15  # deep night
        elif hour < 10:
            t = (hour - 6) / 4
            r = 0.08 + t * 0.05
            g = 0.06 + t * 0.04
            b = 0.15 + t * 0.02
        elif hour < 14:
            r, g, b = 0.13, 0.10, 0.08  # warm midday
        elif hour < 18:
            t = (hour - 14) / 4
            r = 0.13 + t * 0.04
            g = 0.10 - t * 0.02
            b = 0.08 + t * 0.03
        elif hour < 22:
            t = (hour - 18) / 4
            r = 0.17 - t * 0.09
            g = 0.08 - t * 0.02
            b = 0.11 + t * 0.04
        else:
            r, g, b = 0.08, 0.06, 0.15

        # Draw circadian background
        pat = cairo.LinearGradient(0, 0, w, 0)
        pat.add_color_stop_rgba(0, r * 0.7, g * 0.7, b * 0.7, 0.6)
        pat.add_color_stop_rgba(1, r, g, b, 0.6)
        cr.set_source(pat)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        # Session duration fill (faint, from left)
        session_hours = (time.monotonic() - self._start_time) / 3600
        fill_pct = min(session_hours / 8, 1.0)  # Full at 8 hours
        cr.set_source_rgba(0.5, 0.4, 0.2, 0.15)
        cr.rectangle(0, 0, w * fill_pct, h)
        cr.fill()

        # Event countdown (contracting element from right)
        if self._next_event_minutes is not None and self._next_event_minutes < 60:
            event_pct = self._next_event_minutes / 60
            event_w = w * 0.4 * event_pct
            cr.set_source_rgba(0.51, 0.65, 0.60, 0.4)  # blue-400
            cr.rectangle(w - event_w, 0, event_w, h)
            cr.fill()
            # Event name if close
            if self._next_event_minutes < 30:
                cr.set_source_rgba(0.51, 0.65, 0.60, 0.7)
                cr.select_font_face(
                    "JetBrains Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL
                )
                cr.set_font_size(9)
                text = f"{int(self._next_event_minutes)}m"
                cr.move_to(w - event_w + 3, h - 5)
                cr.show_text(text)

        # Clock text at right edge
        if self._use_short_format:
            clock_text = now.strftime("%H:%M")
        else:
            clock_text = now.strftime("%Y-%m-%d %H:%M")
        cr.set_source_rgba(0.92, 0.86, 0.70, 0.8)
        cr.select_font_face("JetBrains Mono", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(11)
        extents = cr.text_extents(clock_text)
        cr.move_to(w - extents.width - 4, h / 2 + extents.height / 2)
        cr.show_text(clock_text)

    def _on_click(self, *_a: object) -> None:
        self._use_short_format = not self._use_short_format
        self.queue_draw()
