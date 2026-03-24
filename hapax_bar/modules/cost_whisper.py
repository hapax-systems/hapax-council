"""Cost whisper — budget-remaining fill bar."""

from __future__ import annotations

import cairo  # noqa: TC002
from gi.repository import Gtk

from hapax_bar.logos_client import fetch_cost, poll_api


class CostWhisper(Gtk.DrawingArea):
    """Tiny vertical fill bar showing LLM budget remaining.

    Green = plenty, amber = elevated, red = near limit.
    No numbers in ambient view. Tooltip shows detail.
    """

    def __init__(self) -> None:
        super().__init__(css_classes=["module", "cost-whisper"])
        self.set_content_width(12)
        self.set_content_height(24)

        self._budget_remaining_pct: float = 100.0
        self._spend_today: float = 0.0
        self._daily_budget: float = 50.0  # default assumption

        self.set_draw_func(self._draw, None)
        self._poll_id = poll_api(fetch_cost, 300_000, self._update)

    def _update(self, data: dict) -> None:
        spend = data.get("total_cost_today", data.get("cost_today", 0.0))
        budget = data.get("daily_budget", self._daily_budget)
        if isinstance(spend, (int, float)) and budget > 0:
            self._spend_today = float(spend)
            self._daily_budget = float(budget)
            self._budget_remaining_pct = max(0, 100 * (1 - spend / budget))
        self.set_tooltip_text(
            f"${self._spend_today:.2f} today — {self._budget_remaining_pct:.0f}% budget remaining"
        )
        self.queue_draw()

    def _draw(
        self, _area: Gtk.DrawingArea, cr: cairo.Context, w: int, h: int, _data: object
    ) -> None:
        pct = self._budget_remaining_pct / 100.0

        # Background
        cr.set_source_rgba(0.15, 0.14, 0.13, 0.3)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        # Fill from bottom
        fill_h = h * pct
        if pct > 0.75:
            r, g, b = 0.72, 0.73, 0.15  # green-400
        elif pct > 0.50:
            r, g, b = 0.60, 0.55, 0.30  # neutral
        elif pct > 0.25:
            r, g, b = 0.98, 0.74, 0.18  # yellow-400
        else:
            r, g, b = 0.98, 0.29, 0.20  # red-400

        cr.set_source_rgba(r, g, b, 0.5)
        cr.rectangle(0, h - fill_h, w, fill_h)
        cr.fill()
