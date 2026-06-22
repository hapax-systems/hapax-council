"""Screwm migration review status ward.

The migration route needs one always-legible in-frame marker so OBS review
can distinguish "DarkPlaces is live, camera is locked, migration bridge active"
from a stale capture or legacy layout. This source is intentionally direct
Cairo instead of a transitional homage source: it is operational chrome for
the current review profile, not another autonomous homage layer.
"""

from __future__ import annotations

from typing import Any

import cairo

from agents.studio_compositor.cairo_source import CairoSource


class ScrewmQuakeStatusCairoSource(CairoSource):
    """Static high-contrast ward for the Screwm migration profile."""

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        del t, state

        cr.save()
        try:
            # Decorative substrate (full-cell black fill, orange border,
            # cyan left band) retired per operator directive 2026-06-21:
            # the status text floats on the void.
            cr.select_font_face(
                "monospace",
                cairo.FONT_SLANT_NORMAL,
                cairo.FONT_WEIGHT_BOLD,
            )
            cr.set_font_size(19.0)
            cr.set_source_rgba(1.0, 0.70, 0.28, 1.0)
            cr.move_to(18.0, 31.0)
            cr.show_text("SCREWM / MIGRATION")

            cr.set_font_size(14.0)
            cr.set_source_rgba(0.80, 1.0, 0.96, 0.95)
            cr.move_to(18.0, 58.0)
            cr.show_text("DARKPLACES SUBSTRATE  |  CAMERA LOCKED")

            cr.set_source_rgba(0.92, 0.86, 0.72, 0.92)
            cr.move_to(18.0, 82.0)
            cr.show_text("IN-SCROOM WARDS ACTIVE  |  /dev/video52 -> /dev/video42")
        finally:
            cr.restore()


__all__ = ["ScrewmQuakeStatusCairoSource"]
