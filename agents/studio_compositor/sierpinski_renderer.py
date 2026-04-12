"""Sierpinski triangle Cairo renderer for the GStreamer pre-FX cairooverlay.

Draws a 2-level Sierpinski triangle with YouTube videos masked into the 3
corner regions and a waveform in the center void. Renders BEFORE the GL
shader chain so glfeedback effects apply to the triangle.

Called from overlay.py's on_draw callback at 30fps.
"""

from __future__ import annotations

import logging
import math
import time
from pathlib import Path
from typing import Any

import cairo

log = logging.getLogger(__name__)

YT_FRAME_DIR = Path("/dev/shm/hapax-compositor")

# Synthwave palette (neon pink, cyan, purple)
COLORS = [
    (1.0, 0.2, 0.6),  # neon pink
    (0.0, 0.9, 1.0),  # cyan
    (0.7, 0.3, 1.0),  # purple
    (1.0, 0.4, 0.8),  # hot pink
]


class SierpinskiRenderer:
    """Draws a Sierpinski triangle with video content in the GStreamer cairooverlay."""

    def __init__(self) -> None:
        self._frame_surfaces: dict[int, cairo.ImageSurface | None] = {}
        self._frame_mtimes: dict[int, float] = {}
        self._active_slot = 0
        self._audio_energy = 0.0

    def set_active_slot(self, slot_id: int) -> None:
        self._active_slot = slot_id

    def set_audio_energy(self, energy: float) -> None:
        self._audio_energy = energy

    def _load_frame(self, slot_id: int) -> cairo.ImageSurface | None:
        """Load a YouTube frame JPEG as a Cairo surface, with mtime caching."""
        path = YT_FRAME_DIR / f"yt-frame-{slot_id}.jpg"
        if not path.exists():
            return self._frame_surfaces.get(slot_id)
        try:
            mtime = path.stat().st_mtime
            if mtime == self._frame_mtimes.get(slot_id, 0):
                return self._frame_surfaces.get(slot_id)
            # Load JPEG via GdkPixbuf → Cairo surface
            from gi.repository import GdkPixbuf

            pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
            # Convert to Cairo-compatible ARGB surface
            w, h = pixbuf.get_width(), pixbuf.get_height()
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
            cr = cairo.Context(surface)
            from gi.repository import Gdk

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
        tri: list[tuple[float, float]],
        opacity: float,
    ) -> None:
        """Draw a video frame as the max inscribed rectangle within a triangle."""
        if surface is None or opacity < 0.01:
            return

        rx, ry, rw, rh = self._inscribed_rect(tri)
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

    def _draw_waveform(self, cr: Any, tri: list[tuple[float, float]], energy: float) -> None:
        """Draw waveform bars inside the largest inscribed rect of the center triangle."""
        rx, ry, rw, rh = self._inscribed_rect(tri)
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
            amp = (energy * 0.5 + 0.1) * (0.5 + 0.5 * math.sin(i * 0.8 + time.monotonic() * 2.0))
            bar_h = amp * rh * 0.85
            x = start_x + i * (bar_w + gap)
            y = cy - bar_h * 0.5

            cr.set_source_rgba(0.0, 0.9, 1.0, 0.9)  # cyan
            cr.rectangle(x, y, bar_w, bar_h)
            cr.fill()

        cr.restore()

    def draw(self, cr: Any, canvas_w: int, canvas_h: int) -> None:
        """Main draw entry point — called from on_draw at 30fps."""
        w = float(canvas_w)
        h = float(canvas_h)
        t = time.monotonic()

        # Main triangle (85% of height, slightly above center)
        tri = self._get_triangle(w, h, scale=0.75, y_offset=-0.02)

        # Level 1 subdivision: 3 corners + center void
        m01 = self._midpoint(tri[0], tri[1])
        m12 = self._midpoint(tri[1], tri[2])
        m02 = self._midpoint(tri[0], tri[2])

        corner_0 = [tri[0], m01, m02]  # top
        corner_1 = [m01, tri[1], m12]  # bottom-left
        corner_2 = [m02, m12, tri[2]]  # bottom-right
        center = [m01, m12, m02]  # center void

        # Load and draw video frames in corner triangles
        for slot_id, corner in enumerate([corner_0, corner_1, corner_2]):
            surface = self._load_frame(slot_id)
            opacity = 0.9 if slot_id == self._active_slot else 0.4
            self._draw_video_in_triangle(cr, surface, corner, opacity)

        # Waveform in center
        self._draw_waveform(cr, center, self._audio_energy)

        # Level 2 subdivision lines (inside corners)
        all_triangles = [tri, corner_0, corner_1, corner_2, center]

        # Subdivide corners for level 2 line detail
        for corner in [corner_0, corner_1, corner_2]:
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

        # Draw line work with audio-reactive width
        line_w = 1.5 + self._audio_energy * 2.0
        self._draw_triangle_lines(cr, all_triangles, line_w, t)
