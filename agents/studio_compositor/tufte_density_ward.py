"""Tufte-density research-poster Cairo ward.

Quiet small multiples over transparent background. Data ink is reserved for
claim-density marks and a single anomaly accent. Default-off through
``HAPAX_LORE_RESEARCH_POSTER_TUFTE_ENABLED``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.cairo_source import CairoSource
from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.research_poster_data import (
    ResearchPosterState,
    read_research_poster_state,
    research_poster_feature_enabled,
)
from shared.homage_package import HomagePackage

if TYPE_CHECKING:
    import cairo

SOURCE_ID = "tufte_density_ward"
FEATURE_FLAG_ENV = "HAPAX_LORE_RESEARCH_POSTER_TUFTE_ENABLED"
DEFAULT_NATURAL_W = 520
DEFAULT_NATURAL_H = 180


def _fallback_package() -> HomagePackage:
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _package() -> HomagePackage:
    return get_active_package() or _fallback_package()


def _resolve(pkg: HomagePackage, role: str) -> tuple[float, float, float, float]:
    try:
        return pkg.resolve_colour(role)
    except Exception:
        return pkg.resolve_colour("muted")


def _font(size: int, *, bold: bool = False) -> str:
    weight = " Bold" if bold else ""
    return f"JetBrains Mono{weight} {size}"


class TufteDensityWard(CairoSource):
    """Minimalist small-multiple ward for research claim density."""

    source_id = SOURCE_ID

    def __init__(
        self,
        state_reader: Callable[[], ResearchPosterState] = read_research_poster_state,
    ) -> None:
        self._state_reader = state_reader

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        if not research_poster_feature_enabled(FEATURE_FLAG_ENV):
            return
        snapshot = self._state_reader()
        pkg = _package()
        ink = _resolve(pkg, "bright")
        muted = _resolve(pkg, "muted")
        anomaly = _resolve(pkg, "accent_red")

        values = snapshot.density_values
        left = 18.0
        top = 24.0
        width = max(canvas_w - 36.0, 1.0)
        height = max(canvas_h - 62.0, 1.0)
        row_count = 4
        col_count = 6
        cell_w = width / col_count
        cell_h = height / row_count

        cr.save()
        cr.set_line_width(0.8)
        for idx in range(row_count * col_count):
            value = values[idx % len(values)]
            col = idx % col_count
            row = idx // col_count
            x = left + col * cell_w + 5.0
            y = top + row * cell_h + 4.0
            self._draw_sparkline(
                cr,
                x=x,
                y=y,
                w=max(cell_w - 10.0, 12.0),
                h=max(cell_h - 10.0, 12.0),
                seed_value=value,
                ink=ink,
                muted=muted,
                anomaly=anomaly,
                anomaly_on=snapshot.failing_count > 0 and idx == 0,
            )
        cr.restore()

        from agents.studio_compositor.text_render import TextStyle, render_text

        render_text(
            cr,
            TextStyle(
                text=f"{snapshot.condition_label}   n={snapshot.claim_count}   pass={snapshot.passing_ratio:.2f}",
                font_description=_font(11),
                color_rgba=muted,
                max_width_px=max(canvas_w - 30, 40),
            ),
            x=15,
            y=canvas_h - 26,
        )

    def _draw_sparkline(
        self,
        cr: cairo.Context,
        *,
        x: float,
        y: float,
        w: float,
        h: float,
        seed_value: float,
        ink: tuple[float, float, float, float],
        muted: tuple[float, float, float, float],
        anomaly: tuple[float, float, float, float],
        anomaly_on: bool,
    ) -> None:
        cr.set_source_rgba(muted[0], muted[1], muted[2], 0.30)
        cr.move_to(x, y + h * 0.74)
        cr.line_to(x + w, y + h * 0.74)
        cr.stroke()

        points = []
        for i in range(8):
            drift = ((i % 3) - 1) * 0.08
            v = min(0.96, max(0.04, seed_value + drift))
            px = x + (w * i / 7.0)
            py = y + h - (v * h)
            points.append((px, py))
        cr.set_source_rgba(ink[0], ink[1], ink[2], 0.78)
        cr.set_line_width(1.0)
        cr.move_to(*points[0])
        for point in points[1:]:
            cr.line_to(*point)
        cr.stroke()

        dot = points[-1]
        cr.set_source_rgba(*(anomaly if anomaly_on else ink))
        cr.arc(dot[0], dot[1], 2.0 if anomaly_on else 1.4, 0, 6.28318)
        cr.fill()


__all__ = [
    "DEFAULT_NATURAL_H",
    "DEFAULT_NATURAL_W",
    "FEATURE_FLAG_ENV",
    "SOURCE_ID",
    "TufteDensityWard",
]
