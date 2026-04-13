"""Album cover + splattribution text overlay.

Reads the IR album cover image from ``/dev/shm/hapax-compositor/album-cover.png``
and the splattribution text from ``music-attribution.txt``. Picks a random PiP
effect per album change. Sits in the lower-left quadrant of the frame.

Phase 3b-final of the compositor unification epic. The per-tick draw logic
lives in :class:`AlbumOverlayCairoSource`, which conforms to the
:class:`CairoSource` protocol. The thread loop and output-surface caching
are owned by :class:`CairoSourceRunner`. The :class:`AlbumOverlay` facade
preserves the original public API (``draw(cr)`` / ``tick()``) so the
existing call sites in :mod:`fx_chain` keep working.
"""

from __future__ import annotations

import logging
import os
import random
from pathlib import Path
from typing import Any

import cairo

from .cairo_source import CairoSource

log = logging.getLogger(__name__)


# --- PiP Cairo effects: content-preserving, randomly selected per video ---


def _pip_fx_vintage(cr: Any, w: int, h: int) -> None:
    """Warm vignette + dense scanlines + sepia wash."""
    cx, cy = w / 2, h / 2
    r = max(w, h) * 0.6
    pat = cairo.RadialGradient(cx, cy, r * 0.2, cx, cy, r)
    pat.add_color_stop_rgba(0, 0, 0, 0, 0)
    pat.add_color_stop_rgba(1, 0, 0, 0, 0.75)
    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Heavy warm tint
    cr.set_source_rgba(0.2, 0.1, 0.0, 0.25)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Dense scanlines
    cr.set_source_rgba(0, 0, 0, 0.18)
    for y in range(0, h, 3):
        cr.rectangle(0, y, w, 1)
    cr.fill()
    # Contrast border
    cr.set_source_rgba(0.6, 0.4, 0.1, 0.4)
    cr.set_line_width(2)
    cr.rectangle(1, 1, w - 2, h - 2)
    cr.stroke()


def _pip_fx_cold(cr: Any, w: int, h: int) -> None:
    """Cold blue tint + heavy vignette + thick horizontal lines."""
    cx, cy = w / 2, h / 2
    r = max(w, h) * 0.55
    pat = cairo.RadialGradient(cx, cy, r * 0.15, cx, cy, r)
    pat.add_color_stop_rgba(0, 0, 0, 0, 0)
    pat.add_color_stop_rgba(1, 0, 0, 0.05, 0.8)
    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Strong blue wash
    cr.set_source_rgba(0.0, 0.08, 0.25, 0.3)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Thick alternating lines
    cr.set_source_rgba(0, 0, 0, 0.2)
    for y in range(0, h, 4):
        cr.rectangle(0, y, w, 2)
    cr.fill()
    # Cold border
    cr.set_source_rgba(0.3, 0.5, 0.8, 0.5)
    cr.set_line_width(2)
    cr.rectangle(1, 1, w - 2, h - 2)
    cr.stroke()


def _pip_fx_neon(cr: Any, w: int, h: int) -> None:
    """Neon glow border + vignette + color wash."""
    cx, cy = w / 2, h / 2
    r = max(w, h) * 0.65
    pat = cairo.RadialGradient(cx, cy, r * 0.3, cx, cy, r)
    pat.add_color_stop_rgba(0, 0, 0, 0, 0)
    pat.add_color_stop_rgba(1, 0, 0, 0, 0.6)
    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Neon glow: multi-layer border
    for width, alpha in [(12, 0.08), (6, 0.15), (3, 0.35), (1.5, 0.6)]:
        cr.set_source_rgba(0.1, 0.7, 1.0, alpha)
        cr.set_line_width(width)
        cr.rectangle(2, 2, w - 4, h - 4)
        cr.stroke()
    # Subtle magenta wash
    cr.set_source_rgba(0.15, 0.0, 0.1, 0.12)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Light scanlines
    cr.set_source_rgba(0, 0, 0, 0.1)
    for y in range(0, h, 3):
        cr.rectangle(0, y, w, 1)
    cr.fill()


def _pip_fx_film(cr: Any, w: int, h: int) -> None:
    """Film print: amber wash + heavy vignette + border scratches."""
    cx, cy = w / 2, h / 2
    r = max(w, h) * 0.6
    pat = cairo.RadialGradient(cx, cy, r * 0.25, cx, cy, r)
    pat.add_color_stop_rgba(0, 0, 0, 0, 0)
    pat.add_color_stop_rgba(1, 0, 0, 0, 0.65)
    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Amber film tint
    cr.set_source_rgba(0.15, 0.08, 0.0, 0.2)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Desaturation overlay
    cr.set_source_rgba(0.12, 0.12, 0.12, 0.15)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Film border
    cr.set_source_rgba(0.8, 0.6, 0.2, 0.4)
    cr.set_line_width(3)
    cr.rectangle(1, 1, w - 2, h - 2)
    cr.stroke()


def _pip_fx_phosphor(cr: Any, w: int, h: int) -> None:
    """CRT phosphor: green tint + heavy scanlines + deep vignette + flicker."""
    cx, cy = w / 2, h / 2
    r = max(w, h) * 0.55
    pat = cairo.RadialGradient(cx, cy, r * 0.15, cx, cy, r)
    pat.add_color_stop_rgba(0, 0, 0, 0, 0)
    pat.add_color_stop_rgba(1, 0, 0, 0, 0.75)
    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Strong green phosphor tint
    cr.set_source_rgba(0.0, 0.18, 0.05, 0.25)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Heavy scanlines (every 2px)
    cr.set_source_rgba(0, 0, 0, 0.22)
    for y in range(0, h, 3):
        cr.rectangle(0, y, w, 1)
    cr.fill()
    # Phosphor border glow
    cr.set_source_rgba(0.1, 0.8, 0.2, 0.35)
    cr.set_line_width(2)
    cr.rectangle(1, 1, w - 2, h - 2)
    cr.stroke()


PIP_EFFECTS = {
    "vintage": _pip_fx_vintage,
    "cold_surveillance": _pip_fx_cold,
    "neon": _pip_fx_neon,
    "film_print": _pip_fx_film,
    "phosphor": _pip_fx_phosphor,
}


# Canvas layout for the CairoSource surface. The cover itself is SIZE x SIZE;
# the text buffer above it reserves room for the attribution markup so the
# facade can blit the whole thing as a single surface.
SIZE = 300
TEXT_BUFFER = 150
CANVAS_W = SIZE
CANVAS_H = SIZE + TEXT_BUFFER

COVER_PATH = "/dev/shm/hapax-compositor/album-cover.png"
ATTRIB_PATH = "/dev/shm/hapax-compositor/music-attribution.txt"
ALPHA = 0.85
RENDER_FPS = 10


class AlbumOverlayCairoSource(CairoSource):
    """Phase 3b CairoSource implementation for the album cover overlay.

    Owns the cached album cover surface, the splattribution text and the
    currently-selected PiP effect. The render method draws everything into
    a local coordinate space whose origin corresponds to the upper-left
    corner of the *text* area — the cover sits at (0, TEXT_BUFFER) within
    the canvas.
    """

    def __init__(self) -> None:
        self._surface: cairo.ImageSurface | None = None
        self._surface_mtime: float = 0.0
        self._attrib_text: str = ""
        self._attrib_mtime: float = 0.0
        self._fx_func: Any = None
        self._fx_name: str = ""

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        self._refresh_cover()
        self._refresh_attribution()

        if self._surface is None:
            return

        # Position the cover TEXT_BUFFER pixels down from the canvas top so
        # the attribution text above the cover fits within the surface.
        cr.save()
        cr.translate(0, TEXT_BUFFER)

        if self._attrib_text:
            self._draw_attrib(cr)

        sw = self._surface.get_width()
        sh = self._surface.get_height()
        if sw > 0 and sh > 0:
            scale = SIZE / max(sw, sh)
            cr.save()
            cr.scale(scale, scale)
            cr.set_source_surface(self._surface, 0, 0)
            cr.paint_with_alpha(ALPHA)
            cr.restore()

            if self._fx_func is not None:
                self._fx_func(cr, SIZE, SIZE)

        cr.restore()

    def _refresh_cover(self) -> None:
        try:
            if not os.path.exists(COVER_PATH):
                return
            mtime = os.path.getmtime(COVER_PATH)
        except OSError:
            return
        if mtime == self._surface_mtime:
            return

        from .image_loader import get_image_loader

        self._surface = get_image_loader().load(COVER_PATH)
        self._surface_mtime = mtime
        # Pick a new random PiP effect on every album change so consecutive
        # tracks don't all wear the same filter.
        self._fx_name, self._fx_func = random.choice(list(PIP_EFFECTS.items()))
        if self._surface is not None:
            log.info(
                "Album cover loaded (%dx%d) fx=%s",
                self._surface.get_width(),
                self._surface.get_height(),
                self._fx_name,
            )
        else:
            log.warning("Album cover load failed: %s", COVER_PATH)

    def _refresh_attribution(self) -> None:
        try:
            if not os.path.exists(ATTRIB_PATH):
                return
            mtime = os.path.getmtime(ATTRIB_PATH)
        except OSError:
            return
        if mtime == self._attrib_mtime:
            return
        try:
            self._attrib_text = Path(ATTRIB_PATH).read_text().strip()
        except OSError:
            return
        self._attrib_mtime = mtime

    def _draw_attrib(self, cr: cairo.Context) -> None:
        """Draw splattribution text above the album cover.

        Phase 3c: delegates to the shared text_render helper. The text is
        measured first so we can position it above the cover origin.
        """
        from .text_render import OUTLINE_OFFSETS_4, TextStyle, measure_text, render_text

        escaped = self._attrib_text.replace("&", "&amp;").replace("<", "&lt;")
        style = TextStyle(
            text=escaped,
            font_description="JetBrains Mono Bold 10",
            color_rgba=(1.0, 0.97, 0.90, 1.0),
            outline_color_rgba=(0.0, 0.0, 0.0, 0.85),
            outline_offsets=OUTLINE_OFFSETS_4,
            max_width_px=SIZE,
            wrap="word_char",
            markup_mode=True,
        )
        _w, h = measure_text(cr, style)
        render_text(cr, style, x=0, y=-h - 5)


# The pre-Phase-9 ``AlbumOverlay`` facade was removed in Phase 9 Task 29.
# Rendering now flows through ``AlbumOverlayCairoSource`` + the
# SourceRegistry + ``fx_chain.pip_draw_from_layout``.
