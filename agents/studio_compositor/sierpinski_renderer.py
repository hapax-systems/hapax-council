"""Sierpinski triangle Cairo renderer for the GStreamer pre-FX cairooverlay.

Draws a 2-level Sierpinski triangle with YouTube videos masked into the 3
corner regions and a waveform in the center void. Renders BEFORE the GL
shader chain so glfeedback effects apply to the triangle.

Phase 3b: the rendering logic lives in :class:`SierpinskiCairoSource`,
which conforms to the :class:`CairoSource` protocol. The thread loop and
output-surface caching are owned by :class:`CairoSourceRunner`. The
:class:`SierpinskiRenderer` facade preserves the original public API
(``start``/``stop``/``draw``/``set_active_slot``/``set_audio_energy``)
so existing call sites in ``fx_chain.py`` and ``overlay.py`` keep working.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cairo

# Drop #42 SIERP-2: hoist `gi.require_version` + `GdkPixbuf` + `Gdk`
# imports to module top. Previously these lived inside `_load_frame`,
# costing ~1 ms/tick via the gi machinery's module-lookup + version
# check path when YT frames were hot. `gi.require_version` is cheap
# once the version is bound for the interpreter's lifetime, so the
# module-level import is effectively free on subsequent calls.
#
# Guarded against CI environments that lack the GdkPixbuf/Gdk typelibs.
# The test runner only exercises the geometry + render-callback paths,
# never touches `_load_frame` — so missing typelibs in CI are harmless
# at runtime, but an unguarded `gi.require_version` raises at module
# import time and blocks the whole test collection. The try/except
# below keeps `GdkPixbuf = None` in that environment and `_load_frame`
# short-circuits via `_HAS_GDK` before touching any gi namespace.
try:
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, GdkPixbuf  # noqa: E402

    _HAS_GDK = True
except (ImportError, ValueError):
    Gdk = None  # type: ignore[assignment]
    GdkPixbuf = None  # type: ignore[assignment]
    _HAS_GDK = False

from .cairo_source import CairoSourceRunner
from .homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    from agents.studio_compositor.budget import BudgetTracker

log = logging.getLogger(__name__)

YT_FRAME_DIR = Path("/dev/shm/hapax-compositor")
RENDER_FPS = 10

# Synthwave palette (neon pink, cyan, purple)
COLORS = [
    (1.0, 0.2, 0.6),  # neon pink
    (0.0, 0.9, 1.0),  # cyan
    (0.7, 0.3, 1.0),  # purple
    (1.0, 0.4, 0.8),  # hot pink
]


class SierpinskiCairoSource(HomageTransitionalSource):
    """HomageTransitionalSource implementation for the Sierpinski overlay.

    Owns the YouTube frame cache, active-slot state, and audio energy
    snapshot. The runner calls ``render_content()`` once per tick on a
    background thread.
    """

    def __init__(self) -> None:
        super().__init__(source_id="sierpinski")
        self._frame_surfaces: dict[int, cairo.ImageSurface | None] = {}
        self._frame_mtimes: dict[int, float] = {}
        self._active_slot = 0
        self._audio_energy = 0.0
        # Drop #42 SIERP-1: cache triangle geometry + inscribed rects
        # keyed on canvas size. Triangle vertices and the 4 inscribed
        # rects (3 corners + 1 center void) are deterministic in
        # canvas_w/canvas_h, so we can compute them once per resize
        # and reuse across ticks. Saves ~0.2 ms/tick.
        self._geom_cache_size: tuple[int, int] | None = None
        self._cached_all_triangles: list[list[tuple[float, float]]] | None = None
        self._cached_corner_rects: list[tuple[float, float, float, float]] | None = None
        self._cached_center_rect: tuple[float, float, float, float] | None = None

    def set_active_slot(self, slot_id: int) -> None:
        self._active_slot = slot_id

    def set_audio_energy(self, energy: float) -> None:
        self._audio_energy = energy

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        # Drop #42 SIERP-1: recompute geometry only on canvas resize.
        if self._geom_cache_size != (canvas_w, canvas_h):
            self._rebuild_geometry_cache(canvas_w, canvas_h)

        assert self._cached_all_triangles is not None
        assert self._cached_corner_rects is not None
        assert self._cached_center_rect is not None

        # Load and draw video frames in corner triangles. Rects are
        # from the geometry cache; triangles are only needed for the
        # line work below, which reads them directly from
        # self._cached_all_triangles.
        for slot_id in range(3):
            frame_surface = self._load_frame(slot_id)
            opacity = 0.9 if slot_id == self._active_slot else 0.4
            rect = self._cached_corner_rects[slot_id]
            self._draw_video_in_triangle(cr, frame_surface, rect, opacity)

        # Waveform in center
        self._draw_waveform(cr, self._cached_center_rect, self._audio_energy, t)

        # Draw line work with audio-reactive width
        line_w = 1.5 + self._audio_energy * 2.0
        self._draw_triangle_lines(cr, self._cached_all_triangles, line_w, t)

    def _rebuild_geometry_cache(self, canvas_w: int, canvas_h: int) -> None:
        """Recompute triangle vertices + inscribed rects for this canvas size.

        Called once per resize (and on first render). All downstream
        ticks reuse the cached geometry. Matches the drop #42 SIERP-1
        optimization.
        """
        fw = float(canvas_w)
        fh = float(canvas_h)

        # Main triangle (75% of height, slightly above center)
        tri = self._get_triangle(fw, fh, scale=0.75, y_offset=-0.02)

        # Level 1 subdivision: 3 corners + center void
        m01 = self._midpoint(tri[0], tri[1])
        m12 = self._midpoint(tri[1], tri[2])
        m02 = self._midpoint(tri[0], tri[2])

        corner_0 = [tri[0], m01, m02]  # top
        corner_1 = [m01, tri[1], m12]  # bottom-left
        corner_2 = [m02, m12, tri[2]]  # bottom-right
        center = [m01, m12, m02]  # center void

        # Level 2 subdivision lines (inside corners)
        all_triangles: list[list[tuple[float, float]]] = [tri, corner_0, corner_1, corner_2, center]
        for corner in (corner_0, corner_1, corner_2):
            cm01 = self._midpoint(corner[0], corner[1])
            cm12 = self._midpoint(corner[1], corner[2])
            cm02 = self._midpoint(corner[0], corner[2])
            all_triangles.extend(
                [
                    [corner[0], cm01, cm02],
                    [cm01, corner[1], cm12],
                    [cm02, cm12, corner[2]],
                    [cm01, cm12, cm02],
                ]
            )

        self._cached_all_triangles = all_triangles
        self._cached_corner_rects = [
            self._inscribed_rect(corner_0),
            self._inscribed_rect(corner_1),
            self._inscribed_rect(corner_2),
        ]
        self._cached_center_rect = self._inscribed_rect(center)
        self._geom_cache_size = (canvas_w, canvas_h)

    def _load_frame(self, slot_id: int) -> cairo.ImageSurface | None:
        """Load a YouTube frame JPEG as a Cairo surface, with mtime caching."""
        if not _HAS_GDK:
            # CI path — GdkPixbuf typelib unavailable. Return whatever's
            # been cached (usually None); the renderer handles None
            # surfaces by skipping the video draw.
            return self._frame_surfaces.get(slot_id)
        path = YT_FRAME_DIR / f"yt-frame-{slot_id}.jpg"
        if not path.exists():
            return self._frame_surfaces.get(slot_id)
        try:
            mtime = path.stat().st_mtime
            if mtime == self._frame_mtimes.get(slot_id, 0):
                return self._frame_surfaces.get(slot_id)
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
            # Convert to Cairo-compatible ARGB surface
            w, h = pixbuf.get_width(), pixbuf.get_height()
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
            cr = cairo.Context(surface)
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
            cr.paint()
            self._frame_surfaces[slot_id] = surface
            self._frame_mtimes[slot_id] = mtime
            return surface
        except Exception:
            return self._frame_surfaces.get(slot_id)

    def _get_triangle(
        self, w: float, h: float, scale: float, y_offset: float
    ) -> list[tuple[float, float]]:
        """Compute main equilateral triangle vertices in pixel coords."""
        tri_h = scale * h * 0.866
        cx = w * 0.5
        cy = h * 0.5 + y_offset * h
        half_base = scale * h * 0.5
        return [
            (cx, cy - tri_h * 0.667),  # top
            (cx - half_base, cy + tri_h * 0.333),  # bottom-left
            (cx + half_base, cy + tri_h * 0.333),  # bottom-right
        ]

    def _midpoint(self, a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
        return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5)

    def _inscribed_rect(self, tri: list[tuple[float, float]]) -> tuple[float, float, float, float]:
        """Compute the largest 16:9 rectangle inscribed in a triangle.

        Returns (x, y, width, height) of the rectangle centered in the triangle.
        The rectangle has one side parallel to the longest edge (base).
        """
        # Find the longest edge to use as the base
        edges = [
            (math.dist(tri[0], tri[1]), 0, 1, 2),
            (math.dist(tri[1], tri[2]), 1, 2, 0),
            (math.dist(tri[2], tri[0]), 2, 0, 1),
        ]
        edges.sort(key=lambda e: e[0], reverse=True)
        _, bi, bj, apex_idx = edges[0]

        base_a = tri[bi]
        base_b = tri[bj]
        apex = tri[apex_idx]

        # Base vector and perpendicular height
        bx = base_b[0] - base_a[0]
        by = base_b[1] - base_a[1]
        base_len = math.sqrt(bx * bx + by * by)
        if base_len < 1.0:
            return (0, 0, 0, 0)

        # Unit base direction and normal
        ux, uy = bx / base_len, by / base_len
        # Normal pointing toward apex
        nx, ny = -uy, ux
        apex_dot = (apex[0] - base_a[0]) * nx + (apex[1] - base_a[1]) * ny
        if apex_dot < 0:
            nx, ny = -nx, -ny
            apex_dot = -apex_dot
        tri_height = apex_dot

        # For a triangle, the largest rectangle with one side on the base:
        # optimal height = tri_height / 2, width = base_len / 2
        # But we want 16:9 aspect ratio, so constrain accordingly.
        aspect = 16.0 / 9.0
        # Max width at a given rect_h from base: w = base_len * (1 - rect_h / tri_height)
        # We want w / rect_h = aspect → base_len * (1 - rect_h/tri_height) = aspect * rect_h
        # → rect_h = base_len / (aspect + base_len / tri_height)
        rect_h = base_len / (aspect + base_len / tri_height)
        rect_w = aspect * rect_h

        # Clamp to triangle dimensions
        if rect_w > base_len * 0.95:
            rect_w = base_len * 0.95
            rect_h = rect_w / aspect
        if rect_h > tri_height * 0.95:
            rect_h = tri_height * 0.95
            rect_w = rect_h * aspect

        # Position: centered on base, offset inward by a small margin
        base_mid_x = (base_a[0] + base_b[0]) * 0.5
        base_mid_y = (base_a[1] + base_b[1]) * 0.5
        # Shift inward from base by a fraction of rect_h to center visually
        inward = rect_h * 0.35
        cx = base_mid_x + nx * inward
        cy = base_mid_y + ny * inward

        # Rectangle top-left corner (axis-aligned approximation)
        rx = cx - rect_w * 0.5
        ry = cy - rect_h * 0.5

        return (rx, ry, rect_w, rect_h)

    def _draw_video_in_triangle(
        self,
        cr: Any,
        surface: cairo.ImageSurface | None,
        rect: tuple[float, float, float, float],
        opacity: float,
    ) -> None:
        """Draw a video frame into a precomputed inscribed rectangle.

        Drop #42 SIERP-1: the inscribed rect is now precomputed at
        geometry-cache-build time (once per canvas resize) and passed
        in directly, rather than recomputed per tick per corner.
        """
        if surface is None or opacity < 0.01:
            return

        rx, ry, rw, rh = rect
        if rw < 1.0 or rh < 1.0:
            return

        cr.save()

        sw = surface.get_width()
        sh = surface.get_height()

        # Scale video to fill the inscribed rectangle (cover, maintain aspect)
        sx = rw / sw
        sy = rh / sh
        s = max(sx, sy)
        # Center within rectangle
        ox = rx + (rw - sw * s) * 0.5
        oy = ry + (rh - sh * s) * 0.5

        cr.rectangle(rx, ry, rw, rh)
        cr.clip()
        cr.translate(ox, oy)
        cr.scale(s, s)
        cr.set_source_surface(surface, 0, 0)
        cr.paint_with_alpha(opacity)

        cr.restore()

    def _draw_triangle_lines(
        self,
        cr: Any,
        triangles: list[list[tuple[float, float]]],
        line_width: float,
        t: float,
    ) -> None:
        """Draw triangle line work with synthwave colors and glow."""
        for i, tri in enumerate(triangles):
            # Color cycles through palette
            color_idx = (i + int(t * 0.5)) % len(COLORS)
            r, g, b = COLORS[color_idx]

            # Glow (wider, semi-transparent)
            cr.set_line_width(line_width * 3.0)
            cr.set_source_rgba(r, g, b, 0.15)
            cr.move_to(*tri[0])
            cr.line_to(*tri[1])
            cr.line_to(*tri[2])
            cr.close_path()
            cr.stroke()

            # Core line
            cr.set_line_width(line_width)
            cr.set_source_rgba(r, g, b, 0.8)
            cr.move_to(*tri[0])
            cr.line_to(*tri[1])
            cr.line_to(*tri[2])
            cr.close_path()
            cr.stroke()

    def _draw_waveform(
        self,
        cr: Any,
        rect: tuple[float, float, float, float],
        energy: float,
        t: float,
    ) -> None:
        """Draw waveform bars inside a precomputed inscribed rectangle.

        Drop #42 SIERP-1 + SIERP-3: rect is precomputed from the
        geometry cache. Phase argument is the ``t`` passed down from
        ``render()`` rather than a fresh ``time.monotonic()`` call,
        so the waveform phase stays consistent with the rest of the
        renderer's animation clock (correctness fix).
        """
        rx, ry, rw, rh = rect
        if rw < 1.0 or rh < 1.0:
            return

        cr.save()

        cy = ry + rh * 0.5

        # 8 bars spanning the full inscribed rectangle width
        bar_count = 8
        gap = rw * 0.03  # small gap between bars
        total_gap = gap * (bar_count - 1)
        bar_w = (rw - total_gap) / bar_count
        start_x = rx

        for i in range(bar_count):
            amp = (energy * 0.5 + 0.1) * (0.5 + 0.5 * math.sin(i * 0.8 + t * 2.0))
            bar_h = amp * rh * 0.85
            x = start_x + i * (bar_w + gap)
            y = cy - bar_h * 0.5

            cr.set_source_rgba(0.0, 0.9, 1.0, 0.9)  # cyan
            cr.rectangle(x, y, bar_w, bar_h)
            cr.fill()

        cr.restore()


class SierpinskiRenderer:
    """Compositor-side facade around the polymorphic Cairo source pipeline.

    Preserves the original public API (``start``/``stop``/``draw``/
    ``set_active_slot``/``set_audio_energy``) so existing call sites in
    ``fx_chain.py`` (instantiation) and ``overlay.py`` (synchronous draw
    callback) continue to work without changes.

    Internally:

    * Holds a :class:`SierpinskiCairoSource` for the per-frame draw logic
    * Holds a :class:`CairoSourceRunner` to drive it on a background
      thread at the configured FPS
    * Forwards ``draw()`` to the runner's cached output surface for the
      sub-millisecond GStreamer streaming-thread blit
    """

    def __init__(self, *, budget_tracker: BudgetTracker | None = None) -> None:
        # A+ Stage 2 audit B2 fix (2026-04-17): canvas dims pulled from
        # config module constants rather than hardcoded 1920x1080. When
        # the canvas drops to 720p, Sierpinski now allocates at the
        # matching resolution instead of rendering 1920x1080 and
        # downscaling — saves the pixel budget Stage 2 was meant to
        # recover.
        from .config import OUTPUT_HEIGHT, OUTPUT_WIDTH

        self._source = SierpinskiCairoSource()
        self._runner = CairoSourceRunner(
            source_id="sierpinski-lines",
            source=self._source,
            canvas_w=OUTPUT_WIDTH,
            canvas_h=OUTPUT_HEIGHT,
            target_fps=RENDER_FPS,
            budget_tracker=budget_tracker,
        )

    def start(self) -> None:
        """Start the background render thread."""
        self._runner.start()
        log.info("SierpinskiRenderer background thread started at %dfps", RENDER_FPS)

    def stop(self) -> None:
        """Stop the background render thread."""
        self._runner.stop()

    def set_active_slot(self, slot_id: int) -> None:
        self._source.set_active_slot(slot_id)

    def set_audio_energy(self, energy: float) -> None:
        self._source.set_audio_energy(energy)

    def draw(self, cr: Any, canvas_w: int, canvas_h: int) -> None:
        """Blit the pre-rendered output surface. Called from on_draw at 30fps.

        This method must be fast (<2ms) — it runs in the GStreamer streaming
        thread. All rendering happens in the background thread.
        """
        # Update canvas size for the runner — picked up on the next tick.
        self._runner.set_canvas_size(canvas_w, canvas_h)

        surface = self._runner.get_output_surface()
        if surface is not None:
            cr.set_source_surface(surface, 0, 0)
            cr.paint()
