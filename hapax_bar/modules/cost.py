"""LLM cost module — polls Logos API /api/cost."""

from __future__ import annotations

from typing import Any

from gi.repository import Gtk

from hapax_bar.logos_client import fetch_cost, poll_api


class CostModule(Gtk.Box):
    """Displays [llm:$X.XX] with daily spend from LiteLLM cost tracking."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL,
            css_classes=["module", "cost"],
        )
        self._label = Gtk.Label(label="[llm:--]")
        self.append(self._label)

        # Poll every 5 minutes (slow cadence, matches API cache)
        self._poll_id = poll_api(fetch_cost, 300_000, self._update)

    def _update(self, data: dict[str, Any]) -> None:
        today = data.get("today_usd", data.get("daily_usd", 0.0))
        month = data.get("month_usd", data.get("period_usd", 0.0))

        if isinstance(today, (int, float)):
            self._label.set_label(f"[llm:${today:.2f}]")
        else:
            self._label.set_label("[llm:--]")

        # Tooltip with monthly total
        tooltip = f"Today: ${today:.2f}" if isinstance(today, (int, float)) else "Today: --"
        if isinstance(month, (int, float)):
            tooltip += f"\nMonth: ${month:.2f}"
        self.set_tooltip_text(tooltip)

        # Severity: >$5/day = warning, >$15/day = critical
        classes = ["module", "cost"]
        if isinstance(today, (int, float)):
            if today > 15:
                classes.append("critical")
            elif today > 5:
                classes.append("warning")
        self.set_css_classes(classes)
