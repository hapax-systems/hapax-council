"""Nudge panel — actionable nudge summary for the seam layer."""

from __future__ import annotations

from gi.repository import Gtk

from hapax_bar.logos_client import _fetch_json


class NudgePanel(Gtk.Box):
    """Shows top nudges with category and priority."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=1,
            css_classes=["nudge-panel"],
        )
        self._header = Gtk.Label(xalign=0, css_classes=["metrics-row"], use_markup=True)
        self._items = Gtk.Label(xalign=0, css_classes=["stimmung-dims"], use_markup=True)
        self.append(self._header)
        self.append(self._items)

    def refresh(self) -> None:
        data = _fetch_json("/api/nudges")
        if not data or not isinstance(data, list):
            self.set_visible(False)
            return

        count = len(data)
        if count == 0:
            self.set_visible(False)
            return

        self.set_visible(True)
        color = (
            "#fb4934"
            if count >= 11
            else "#fe8019"
            if count >= 6
            else "#fabd2f"
            if count >= 3
            else "#665c54"
        )
        self._header.set_markup(f'Nudges: <span foreground="{color}">{count}</span>')

        # Show top 5 by priority
        sorted_nudges = sorted(data, key=lambda n: n.get("priority_score", 0), reverse=True)
        lines = []
        for n in sorted_nudges[:5]:
            cat = n.get("category", "?")
            title = n.get("title", "?")
            cat_colors = {
                "health": "#fb4934",
                "drift": "#fe8019",
                "knowledge": "#83a598",
                "meta": "#665c54",
            }
            cc = cat_colors.get(cat, "#665c54")
            lines.append(f'  <span foreground="{cc}">{cat}</span>: {title}')

        if count > 5:
            lines.append(f'  <span foreground="#665c54">+{count - 5} more</span>')

        self._items.set_markup("\n".join(lines))
