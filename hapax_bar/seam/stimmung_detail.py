"""Stimmung detail panel — 10-dimension readout with trends."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Gtk

if TYPE_CHECKING:
    from hapax_bar.stimmung import StimmungState

_TREND_ARROWS = {"rising": "\u25b2", "falling": "\u25bc", "stable": "\u25ac"}
_STALE_THRESHOLD_S = 120


class StimmungDetailPanel(Gtk.Box):
    """Compact stimmung dimension readout."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            css_classes=["stimmung-detail"],
        )
        self._stance_label = Gtk.Label(xalign=0, css_classes=["stimmung-stance"])
        self._dims_label = Gtk.Label(xalign=0, css_classes=["stimmung-dims"])
        self.append(self._stance_label)
        self.append(self._dims_label)

    def update(self, state: StimmungState) -> None:
        self._stance_label.set_label(f"Stance: {state.stance}")

        lines = []
        for name, dim in state.dimensions.items():
            value = dim.get("value", 0.0)
            trend = _TREND_ARROWS.get(dim.get("trend", "stable"), "\u25ac")
            freshness = dim.get("freshness_s", 0.0)
            stale = ""
            if freshness > _STALE_THRESHOLD_S:
                minutes = int(freshness / 60)
                stale = f" (stale {minutes}min)"
            lines.append(f"  {name}: {value:.2f} {trend}{stale}")

        self._dims_label.set_label("\n".join(lines))
