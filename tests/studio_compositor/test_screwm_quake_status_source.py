from __future__ import annotations

import cairo

from agents.studio_compositor.cairo_sources import get_cairo_source_class
from agents.studio_compositor.screwm_quake_status_source import (
    ScrewmQuakeStatusCairoSource,
)


def test_screwm_quake_status_source_is_registered() -> None:
    assert get_cairo_source_class("ScrewmQuakeStatusCairoSource") is ScrewmQuakeStatusCairoSource


def test_screwm_quake_status_source_renders_opaque_review_anchor() -> None:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 560, 96)
    cr = cairo.Context(surface)

    ScrewmQuakeStatusCairoSource().render(cr, 560, 96, t=0.0, state={})
    surface.flush()

    data = bytes(surface.get_data())
    alpha = data[3::4]

    assert max(alpha) >= 240
    assert sum(1 for value in alpha if value >= 200) > 560 * 96 * 0.70
