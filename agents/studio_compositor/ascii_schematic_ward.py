"""ASCII-schematic research-poster Cairo ward.

Terminal-grid poster surface using character-cell schematics and glyph-as-data.
It shares continuity with the BitchX register while staying redaction-safe and
default-off through ``HAPAX_LORE_RESEARCH_POSTER_ASCII_ENABLED``.
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

SOURCE_ID = "ascii_schematic_ward"
FEATURE_FLAG_ENV = "HAPAX_LORE_RESEARCH_POSTER_ASCII_ENABLED"
DEFAULT_NATURAL_W = 520
DEFAULT_NATURAL_H = 180


def ascii_schematic_lines(snapshot: ResearchPosterState) -> tuple[str, ...]:
    """Return ASCII-only schematic rows for tests and rendering."""

    width = 46

    def row(content: str = "") -> str:
        return f"| {content:<{width - 4}.{width - 4}} |"

    condition = snapshot.condition_label[:24]
    header_label = "+-- research schematic "
    header = header_label + "-" * (width - len(header_label) - 1) + "+"
    footer = "+" + "-" * (width - 2) + "+"
    pass_bar = _bar(snapshot.passing_count, snapshot.claim_count)
    fail_bar = _bar(snapshot.failing_count, snapshot.claim_count)
    unverified_bar = _bar(snapshot.unverified_count, snapshot.claim_count)
    return (
        header,
        row(f"condition: {condition}"),
        row(f"epoch:     {snapshot.epoch or 0}"),
        row(),
        row(f"pass  [{pass_bar}] {snapshot.passing_count:02d}/{snapshot.claim_count:02d}"),
        row(f"fail  [{fail_bar}] {snapshot.failing_count:02d}/{snapshot.claim_count:02d}"),
        row(f"unver [{unverified_bar}] {snapshot.unverified_count:02d}/{snapshot.claim_count:02d}"),
        footer,
    )


def _bar(value: int, total: int, width: int = 20) -> str:
    if total <= 0:
        filled = 0
    else:
        filled = round(width * value / total)
    return "#" * filled + "." * (width - filled)


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


class ASCIISchematicWard(CairoSource):
    """ASCII grid schematic for research condition and claim status."""

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
        ink = _resolve(pkg, "accent_green")
        muted = _resolve(pkg, "muted")
        bg = _resolve(pkg, "background")

        cr.save()
        cr.set_source_rgba(bg[0], bg[1], bg[2], min(bg[3], 0.52))
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()
        cr.set_source_rgba(muted[0], muted[1], muted[2], 0.55)
        cr.set_line_width(1.0)
        for x in range(0, canvas_w, 16):
            cr.move_to(x + 0.5, 0)
            cr.line_to(x + 0.5, canvas_h)
        for y in range(0, canvas_h, 16):
            cr.move_to(0, y + 0.5)
            cr.line_to(canvas_w, y + 0.5)
        cr.stroke()
        cr.restore()

        from agents.studio_compositor.text_render import TextStyle, render_text

        y = 10.0
        for line in ascii_schematic_lines(snapshot):
            render_text(
                cr,
                TextStyle(
                    text=line,
                    font_description="JetBrains Mono Bold 12",
                    color_rgba=ink if "#" in line or line.startswith("+") else muted,
                    max_width_px=max(canvas_w - 18, 40),
                ),
                x=10,
                y=y,
            )
            y += 19.0


__all__ = [
    "DEFAULT_NATURAL_H",
    "DEFAULT_NATURAL_W",
    "FEATURE_FLAG_ENV",
    "SOURCE_ID",
    "ASCIISchematicWard",
    "ascii_schematic_lines",
]
