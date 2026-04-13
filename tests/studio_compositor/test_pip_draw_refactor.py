"""Phase 3 render-path flip tests — blit_scaled + pip_draw_from_layout.

Parent plan E15 / E16. These tests pin the render contract:

1. ``blit_scaled`` translates + scales a natural-size source to the
   target surface geometry, honoring opacity and blend mode.
2. ``pip_draw_from_layout`` walks ``LayoutState`` in z_order, pulls
   each assignment's source from the registry, and blits it — skipping
   non-rect surfaces (those go through the glvideomixer appsrc path)
   and skipping sources that have no current surface yet.

The render path MUST NOT fall back to the legacy
``compositor._token_pole.draw(cr)`` path when a source is missing —
that is Phase 9 cleanup territory.
"""

from __future__ import annotations

import cairo

from agents.studio_compositor.fx_chain import blit_scaled, pip_draw_from_layout
from agents.studio_compositor.layout_state import LayoutState
from agents.studio_compositor.source_registry import SourceRegistry
from shared.compositor_model import (
    Assignment,
    Layout,
    SourceSchema,
    SurfaceGeometry,
    SurfaceSchema,
)


def _solid_surface(w: int, h: int, rgb: tuple[float, float, float]) -> cairo.ImageSurface:
    """Build a single-colour cairo surface at ``w × h``."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 1.0)
    cr.paint()
    return surface


def _pixel(surface: cairo.ImageSurface, x: int, y: int) -> tuple[int, int, int, int]:
    """Return (R, G, B, A) of the pixel at ``(x, y)``.

    Cairo ``FORMAT_ARGB32`` on little-endian is laid out as BGRA in
    memory. The accessor returns the logical RGBA tuple.
    """
    data = surface.get_data()
    stride = surface.get_stride()
    off = y * stride + x * 4
    return data[off + 2], data[off + 1], data[off + 0], data[off + 3]


def _paint_black(canvas: cairo.ImageSurface) -> cairo.Context:
    cr = cairo.Context(canvas)
    cr.set_source_rgba(0, 0, 0, 1)
    cr.paint()
    return cr


class _CannedBackend:
    """Minimum SourceBackend protocol stub — returns a pre-made surface."""

    def __init__(self, surface: cairo.ImageSurface | None) -> None:
        self._surface = surface

    def get_current_surface(self) -> cairo.ImageSurface | None:
        return self._surface


# ── blit_scaled ─────────────────────────────────────────────────────


def test_blit_scaled_places_source_at_geometry() -> None:
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 100)
    cr = _paint_black(canvas)

    src = _solid_surface(10, 10, (1.0, 0.0, 0.0))
    geom = SurfaceGeometry(kind="rect", x=50, y=30, w=40, h=20)
    blit_scaled(cr, src, geom, opacity=1.0, blend_mode="over")
    canvas.flush()

    # Inside the target rect — red.
    assert _pixel(canvas, 60, 40)[:3] == (0xFF, 0x00, 0x00)
    # Outside the target rect — black.
    assert _pixel(canvas, 10, 10)[:3] == (0x00, 0x00, 0x00)


def test_blit_scaled_skips_non_rect_geometry() -> None:
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
    cr = _paint_black(canvas)
    src = _solid_surface(10, 10, (1.0, 1.0, 1.0))
    geom = SurfaceGeometry(kind="fx_chain_input")
    blit_scaled(cr, src, geom, opacity=1.0, blend_mode="over")
    canvas.flush()
    # Non-rect geometry is a no-op — canvas remains black.
    assert _pixel(canvas, 50, 50)[:3] == (0x00, 0x00, 0x00)


def test_blit_scaled_honors_opacity() -> None:
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
    cr = _paint_black(canvas)
    src = _solid_surface(10, 10, (1.0, 1.0, 1.0))
    geom = SurfaceGeometry(kind="rect", x=0, y=0, w=100, h=100)
    blit_scaled(cr, src, geom, opacity=0.5, blend_mode="over")
    canvas.flush()
    r, g, b, _ = _pixel(canvas, 50, 50)
    # 50% white over black → mid-grey (allow ±2 for rounding).
    assert 126 <= r <= 130
    assert 126 <= g <= 130
    assert 126 <= b <= 130


# ── pip_draw_from_layout ────────────────────────────────────────────


def _layout_with_two_rect_surfaces() -> Layout:
    """Two sources, two overlapping rect surfaces, different z_order."""
    return Layout(
        name="t",
        sources=[
            SourceSchema(
                id="red",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
            SourceSchema(
                id="green",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="low",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=50, h=50),
                z_order=1,
            ),
            SurfaceSchema(
                id="high",
                geometry=SurfaceGeometry(kind="rect", x=20, y=20, w=50, h=50),
                z_order=5,
            ),
        ],
        assignments=[
            Assignment(source="red", surface="low"),
            Assignment(source="green", surface="high"),
        ],
    )


def test_pip_draw_from_layout_walks_assignments_by_z_order() -> None:
    state = LayoutState(_layout_with_two_rect_surfaces())
    registry = SourceRegistry()
    registry.register("red", _CannedBackend(_solid_surface(10, 10, (1.0, 0.0, 0.0))))
    registry.register("green", _CannedBackend(_solid_surface(10, 10, (0.0, 1.0, 0.0))))

    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 200)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)
    canvas.flush()

    # Overlap point (30, 30) — green (z=5) overlays red (z=1).
    assert _pixel(canvas, 30, 30)[:3] == (0x00, 0xFF, 0x00)
    # Red-only point (5, 5) — red (only the low-z surface).
    assert _pixel(canvas, 5, 5)[:3] == (0xFF, 0x00, 0x00)
    # Outside both rects (80, 80) — still the black clear.
    assert _pixel(canvas, 80, 80)[:3] == (0x00, 0x00, 0x00)


def test_pip_draw_skips_non_rect_surfaces() -> None:
    layout = Layout(
        name="t",
        sources=[
            SourceSchema(
                id="red",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="main",
                geometry=SurfaceGeometry(kind="fx_chain_input"),
                z_order=0,
            ),
        ],
        assignments=[Assignment(source="red", surface="main")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    registry.register("red", _CannedBackend(_solid_surface(10, 10, (1.0, 1.0, 1.0))))
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 50, 50)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)
    canvas.flush()
    # Non-rect surface (fx_chain_input) is handled by the glvideomixer
    # appsrc path in Phase H — cairooverlay draw callback skips it.
    assert _pixel(canvas, 25, 25)[:3] == (0x00, 0x00, 0x00)


def test_pip_draw_skips_sources_with_none_surface() -> None:
    """Missing-frame sources are skipped without falling back to legacy."""
    layout = Layout(
        name="t",
        sources=[
            SourceSchema(
                id="sleepy",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="a",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=50, h=50),
            ),
        ],
        assignments=[Assignment(source="sleepy", surface="a")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    registry.register("sleepy", _CannedBackend(None))
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 60)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)
    canvas.flush()
    # No draw, canvas remains black. No exception raised.
    assert _pixel(canvas, 25, 25)[:3] == (0x00, 0x00, 0x00)


def test_pip_draw_skips_unknown_source_ids() -> None:
    """An assignment whose source isn't in the registry is skipped cleanly."""
    layout = Layout(
        name="t",
        sources=[
            SourceSchema(
                id="real",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="a",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=50, h=50),
            ),
        ],
        assignments=[Assignment(source="real", surface="a")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    # Deliberately do NOT register "real".
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 60)
    cr = _paint_black(canvas)
    pip_draw_from_layout(cr, state, registry)
    canvas.flush()
    assert _pixel(canvas, 25, 25)[:3] == (0x00, 0x00, 0x00)
