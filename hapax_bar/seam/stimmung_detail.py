"""Stimmung detail panel — 10-dimension readout with severity coloring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from gi.repository import Gtk

if TYPE_CHECKING:
    from hapax_bar.stimmung import StimmungState

_TREND_ARROWS = {"rising": "\u25b2", "falling": "\u25bc", "stable": "\u25ac"}
_TREND_COLORS = {"rising": "#fb4934", "falling": "#83a598", "stable": "#665c54"}
_STALE_THRESHOLD_S = 120


def _dim_color(value: float) -> str:
    if value >= 0.7:
        return "#fb4934"
    if value >= 0.4:
        return "#fe8019"
    if value >= 0.15:
        return "#fabd2f"
    return "#665c54"


def _stance_color(stance: str) -> str:
    if stance == "nominal":
        return "#b8bb26"
    if stance == "cautious":
        return "#fabd2f"
    if stance == "degraded":
        return "#fe8019"
    if stance == "critical":
        return "#fb4934"
    return "#665c54"


class StimmungDetailPanel(Gtk.Box):
    """Compact stimmung dimension readout with severity coloring."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=2,
            css_classes=["stimmung-detail"],
        )
        self._stance_label = Gtk.Label(xalign=0, css_classes=["stimmung-stance"], use_markup=True)
        self._dims_label = Gtk.Label(xalign=0, css_classes=["stimmung-dims"], use_markup=True)
        self.append(self._stance_label)
        self.append(self._dims_label)

    def update(self, state: StimmungState) -> None:
        sc = _stance_color(state.stance)
        self._stance_label.set_markup(f'Stance: <span foreground="{sc}">{state.stance}</span>')

        lines = []
        for name, dim in state.dimensions.items():
            value = dim.get("value", 0.0)
            trend = dim.get("trend", "stable")
            arrow = _TREND_ARROWS.get(trend, "\u25ac")
            arrow_color = _TREND_COLORS.get(trend, "#665c54")
            freshness = dim.get("freshness_s", 0.0)

            vc = _dim_color(value)
            val_str = f'<span foreground="{vc}">{value:.2f}</span>'
            arrow_str = f'<span foreground="{arrow_color}">{arrow}</span>'

            stale = ""
            if freshness > _STALE_THRESHOLD_S:
                minutes = int(freshness / 60)
                stale = f' <span foreground="#665c54">({minutes}m)</span>'

            lines.append(f"  {name}: {val_str} {arrow_str}{stale}")

        self._dims_label.set_markup("\n".join(lines))
