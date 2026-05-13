"""Tests for ``render_stage`` filter on ``pip_draw_from_layout``.

FINDING-W (ef7b-179, 2026-04-24). Pins:

- ``Assignment.render_stage`` defaults to ``"post_fx"`` (back-compat).
- ``pip_draw_from_layout(..., stage=None)`` (default) renders every
  assignment — matches pre-FINDING-W behavior.
- ``stage="post_fx"`` blits only assignments whose ``render_stage``
  matches (or is absent — back-compat).
- ``stage="pre_fx"`` blits only assignments tagged ``pre_fx``.
- The two stages together cover every assignment exactly once.

Spec reference: cc-task `ef7b-179-finding-w-fix-post-fx-cairooverlay-for-chrome-ward.md`.
"""

from __future__ import annotations

import cairo

from agents.studio_compositor.fx_chain import pip_draw_from_layout
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
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    cr.set_source_rgba(rgb[0], rgb[1], rgb[2], 1.0)
    cr.paint()
    return surface


def _pixel(surface: cairo.ImageSurface, x: int, y: int) -> tuple[int, int, int, int]:
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
    def __init__(self, surface: cairo.ImageSurface | None) -> None:
        self._surface = surface

    def get_current_surface(self) -> cairo.ImageSurface | None:
        return self._surface


def _stage_demo_layout() -> Layout:
    """One pre_fx (red, disjoint rect) + one post_fx (green, disjoint rect)."""
    return Layout(
        name="stage-demo",
        sources=[
            SourceSchema(id="red", kind="cairo", backend="cairo", params={"class_name": "Stub"}),
            SourceSchema(id="green", kind="cairo", backend="cairo", params={"class_name": "Stub"}),
        ],
        surfaces=[
            SurfaceSchema(
                id="a",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=40, h=40),
                z_order=1,
            ),
            SurfaceSchema(
                id="b",
                geometry=SurfaceGeometry(kind="rect", x=60, y=0, w=40, h=40),
                z_order=2,
            ),
        ],
        assignments=[
            Assignment(source="red", surface="a", render_stage="pre_fx"),
            Assignment(source="green", surface="b", render_stage="post_fx"),
        ],
    )


def _registry_with_red_green() -> SourceRegistry:
    registry = SourceRegistry()
    registry.register("red", _CannedBackend(_solid_surface(10, 10, (1.0, 0.0, 0.0))))
    registry.register("green", _CannedBackend(_solid_surface(10, 10, (0.0, 1.0, 0.0))))
    return registry


# ── schema back-compat ───────────────────────────────────────────────


def test_assignment_default_render_stage_is_post_fx() -> None:
    """Every existing layout JSON must read back with the post_fx default."""
    a = Assignment(source="red", surface="a")
    assert a.render_stage == "post_fx"


def test_assignment_accepts_pre_fx() -> None:
    a = Assignment(source="red", surface="a", render_stage="pre_fx")
    assert a.render_stage == "pre_fx"


def test_assignment_rejects_unknown_stage() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Assignment(source="red", surface="a", render_stage="mid_fx")  # type: ignore[arg-type]


# ── stage filter behaviour ───────────────────────────────────────────


def test_stage_none_renders_everything_backcompat() -> None:
    """stage=None (default) keeps the old behaviour — both assignments blit."""
    state = LayoutState(_stage_demo_layout())
    registry = _registry_with_red_green()
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 50)
    cr = _paint_black(canvas)

    pip_draw_from_layout(cr, state, registry)
    canvas.flush()

    # Red rect centre (20, 20) dominant red.
    r, g, _b, _a = _pixel(canvas, 20, 20)
    assert r >= 240 and g <= 12
    # Green rect centre (80, 20) dominant green.
    r, g, _b, _a = _pixel(canvas, 80, 20)
    assert g >= 240 and r <= 12


def test_stage_post_fx_skips_pre_fx_assignments() -> None:
    state = LayoutState(_stage_demo_layout())
    registry = _registry_with_red_green()
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 50)
    cr = _paint_black(canvas)

    pip_draw_from_layout(cr, state, registry, stage="post_fx")
    canvas.flush()

    # Red rect (pre_fx) should remain black.
    assert _pixel(canvas, 20, 20)[:3] == (0, 0, 0)
    # Green rect (post_fx) should be visible.
    r, g, _b, _a = _pixel(canvas, 80, 20)
    assert g >= 240 and r <= 12


def test_stage_pre_fx_skips_post_fx_assignments() -> None:
    state = LayoutState(_stage_demo_layout())
    registry = _registry_with_red_green()
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 50)
    cr = _paint_black(canvas)

    pip_draw_from_layout(cr, state, registry, stage="pre_fx")
    canvas.flush()

    # Red rect (pre_fx) should be visible.
    r, g, _b, _a = _pixel(canvas, 20, 20)
    assert r >= 240 and g <= 12
    # Green rect (post_fx) should remain black.
    assert _pixel(canvas, 80, 20)[:3] == (0, 0, 0)


def test_sierpinski_assignment_respects_base_overlay_gate(
    monkeypatch,
) -> None:
    layout = Layout(
        name="sierpinski-gated",
        sources=[
            SourceSchema(
                id="sierpinski",
                kind="cairo",
                backend="cairo",
                params={"class_name": "Stub"},
            ),
        ],
        surfaces=[
            SurfaceSchema(
                id="full",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=40, h=40),
                z_order=1,
            ),
        ],
        assignments=[Assignment(source="sierpinski", surface="full", render_stage="pre_fx")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    registry.register("sierpinski", _CannedBackend(_solid_surface(10, 10, (1.0, 0.0, 0.0))))
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 50, 50)
    cr = _paint_black(canvas)
    monkeypatch.setenv("HAPAX_SIERPINSKI_BASE_OVERLAY_ENABLED", "0")

    pip_draw_from_layout(cr, state, registry, stage="pre_fx")
    canvas.flush()

    assert _pixel(canvas, 20, 20)[:3] == (0, 0, 0)


def test_stage_post_fx_includes_untagged_assignments() -> None:
    """Legacy layouts with no render_stage tag must still render under post_fx.

    getattr fallback in the filter guards against older hand-assembled
    Assignment objects that pre-date this field.
    """
    layout = Layout(
        name="untagged",
        sources=[
            SourceSchema(id="red", kind="cairo", backend="cairo", params={"class_name": "Stub"}),
        ],
        surfaces=[
            SurfaceSchema(
                id="only",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=40, h=40),
                z_order=1,
            ),
        ],
        assignments=[Assignment(source="red", surface="only")],  # no render_stage
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    registry.register("red", _CannedBackend(_solid_surface(10, 10, (1.0, 0.0, 0.0))))
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 50, 50)
    cr = _paint_black(canvas)

    pip_draw_from_layout(cr, state, registry, stage="post_fx")
    canvas.flush()

    # Default stage on untagged assignment is post_fx — blit visible.
    r, g, _b, _a = _pixel(canvas, 20, 20)
    assert r >= 240 and g <= 12


def test_stage_pre_fx_skips_untagged_assignments() -> None:
    """Default of post_fx means untagged assignments do NOT render pre_fx.

    This is the invariant: two stage walks, post_fx + pre_fx, cover every
    assignment exactly once (no double-blit, no missed blit) under the
    default untagged layouts.
    """
    layout = Layout(
        name="untagged",
        sources=[
            SourceSchema(id="red", kind="cairo", backend="cairo", params={"class_name": "Stub"}),
        ],
        surfaces=[
            SurfaceSchema(
                id="only",
                geometry=SurfaceGeometry(kind="rect", x=0, y=0, w=40, h=40),
                z_order=1,
            ),
        ],
        assignments=[Assignment(source="red", surface="only")],
    )
    state = LayoutState(layout)
    registry = SourceRegistry()
    registry.register("red", _CannedBackend(_solid_surface(10, 10, (1.0, 0.0, 0.0))))
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 50, 50)
    cr = _paint_black(canvas)

    pip_draw_from_layout(cr, state, registry, stage="pre_fx")
    canvas.flush()

    assert _pixel(canvas, 20, 20)[:3] == (0, 0, 0)
