"""Constructivist research-poster Cairo ward.

The ward translates the JR research-poster scout's Constructivist option into
an instrument surface: diagonal structural axis, large condition anchor, dense
claim block, and red-wedge action geometry. It remains default-off through
``HAPAX_LORE_RESEARCH_POSTER_CONSTRUCTIVIST_ENABLED``.
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

SOURCE_ID = "constructivist_research_poster_ward"
FEATURE_FLAG_ENV = "HAPAX_LORE_RESEARCH_POSTER_CONSTRUCTIVIST_ENABLED"
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


class ConstructivistResearchPosterWard(CairoSource):
    """Diagonal Constructivist density ward for active research state."""

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
        accent = _resolve(pkg, "accent_red")
        bright = _resolve(pkg, "bright")
        muted = _resolve(pkg, "muted")
        bg = _resolve(pkg, "background")

        cr.save()
        cr.set_source_rgba(bg[0], bg[1], bg[2], min(bg[3], 0.62))
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()

        cr.set_source_rgba(*accent)
        cr.move_to(0, canvas_h)
        cr.line_to(canvas_w * 0.42, 0)
        cr.line_to(canvas_w * 0.54, 0)
        cr.line_to(canvas_w * 0.12, canvas_h)
        cr.close_path()
        cr.fill()

        cr.set_source_rgba(muted[0], muted[1], muted[2], 0.72)
        cr.set_line_width(2.0)
        cr.move_to(canvas_w * 0.08, canvas_h * 0.88)
        cr.line_to(canvas_w * 0.92, canvas_h * 0.12)
        cr.stroke()
        cr.restore()

        from agents.studio_compositor.text_render import TextStyle, render_text

        condition = snapshot.condition_label.upper()
        condition = condition[-20:] if len(condition) > 20 else condition
        render_text(
            cr,
            TextStyle(
                text=condition,
                font_description=_font(28, bold=True),
                color_rgba=bright,
                max_width_px=max(canvas_w - 150, 40),
            ),
            x=canvas_w * 0.30,
            y=18,
        )
        render_text(
            cr,
            TextStyle(
                text=(
                    f"CLAIMS {snapshot.claim_count:02d}  "
                    f"PASS {snapshot.passing_count:02d}  "
                    f"FAIL {snapshot.failing_count:02d}  "
                    f"UNVER {snapshot.unverified_count:02d}"
                ),
                font_description=_font(13, bold=True),
                color_rgba=bright,
                max_width_px=max(canvas_w - 36, 40),
            ),
            x=18,
            y=canvas_h - 54,
        )
        render_text(
            cr,
            TextStyle(
                text=f"RESEARCH POSTER / CONSTRUCTIVIST / EPOCH {snapshot.epoch or 0}",
                font_description=_font(11),
                color_rgba=muted,
                max_width_px=max(canvas_w - 36, 40),
            ),
            x=18,
            y=canvas_h - 30,
        )


__all__ = [
    "DEFAULT_NATURAL_H",
    "DEFAULT_NATURAL_W",
    "FEATURE_FLAG_ENV",
    "SOURCE_ID",
    "ConstructivistResearchPosterWard",
]
