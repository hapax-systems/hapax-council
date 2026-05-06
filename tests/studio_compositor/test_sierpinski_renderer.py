"""Tests for the extended Sierpinski geometry cache (GEAL Phase 0 Task 0.2).

Covers `SierpinskiCairoSource.geometry_cache(target_depth=N)` which returns
a :class:`GeometryCache` structure with:

- ``all_triangles`` — all solid sub-triangles from L0 through ``target_depth``
  (voids are represented separately; only non-void Sierpinski sub-triangles
  are counted here).
- ``corner_slivers`` — per-corner list of 3 polygons (corner L2 minus the
  inscribed 16:9 rect, split into apex/left/right slivers). L3/L4 edge work
  renders here only.
- ``vertex_halo_centers`` — 3 primary L0 apices (for V2 halos, G6 markers).
- ``edge_polylines`` — keyed by path like ``"L0.top"`` for G1 wavefront
  propagation along recursion-tree edges.
- ``center_void`` — the L1 centre triangle (hosts the centre-void field).
- ``inscribed_rects`` — the 3 corner 16:9 rects (hosts YT video).

The test uses the canvas size constants from the compositor config so any
resolution change cascades through naturally.
"""

from __future__ import annotations

import pytest

from agents.studio_compositor.sierpinski_renderer import SierpinskiCairoSource


@pytest.fixture()
def renderer() -> SierpinskiCairoSource:
    return SierpinskiCairoSource()


def test_audio_line_width_has_bounded_attack_lift(renderer: SierpinskiCairoSource) -> None:
    from agents.studio_compositor.sierpinski_renderer import (
        AUDIO_LINE_WIDTH_BASE_PX,
        AUDIO_LINE_WIDTH_MAX_PX,
        AUDIO_LINE_WIDTH_SCALE_PX,
    )

    renderer.set_audio_energy(0.0)
    assert renderer._audio_line_width() == pytest.approx(AUDIO_LINE_WIDTH_BASE_PX)  # noqa: SLF001

    renderer.set_audio_energy(1.0)
    smoothed_only_width = (
        AUDIO_LINE_WIDTH_BASE_PX + renderer._audio_energy_smoothed * AUDIO_LINE_WIDTH_SCALE_PX  # noqa: SLF001
    )
    attack_width = renderer._audio_line_width()  # noqa: SLF001

    assert attack_width > smoothed_only_width
    assert attack_width < AUDIO_LINE_WIDTH_MAX_PX


def test_audio_line_width_keeps_existing_max_footprint(renderer: SierpinskiCairoSource) -> None:
    from agents.studio_compositor.sierpinski_renderer import AUDIO_LINE_WIDTH_MAX_PX

    renderer._audio_energy = 9.0  # noqa: SLF001
    renderer._audio_energy_smoothed = 9.0  # noqa: SLF001

    assert renderer._audio_line_width() == pytest.approx(AUDIO_LINE_WIDTH_MAX_PX)  # noqa: SLF001


def test_geometry_cache_l2_default(renderer: SierpinskiCairoSource) -> None:
    geom = renderer.geometry_cache(target_depth=2, canvas_w=1280, canvas_h=720)
    # L0 + L1 corners + L2 corners = 1 + 3 + 9 = 13
    assert len(geom.all_triangles) == 13


def test_geometry_cache_supports_l3(renderer: SierpinskiCairoSource) -> None:
    geom = renderer.geometry_cache(target_depth=3, canvas_w=1280, canvas_h=720)
    assert len(geom.all_triangles) == 40  # 1 + 3 + 9 + 27


def test_geometry_cache_supports_l4(renderer: SierpinskiCairoSource) -> None:
    geom = renderer.geometry_cache(target_depth=4, canvas_w=1280, canvas_h=720)
    assert len(geom.all_triangles) == 121  # 1 + 3 + 9 + 27 + 81


def test_corner_slivers_computed(renderer: SierpinskiCairoSource) -> None:
    geom = renderer.geometry_cache(target_depth=2, canvas_w=1280, canvas_h=720)
    assert len(geom.corner_slivers) == 3  # one triad per corner
    for triad in geom.corner_slivers:
        assert len(triad) == 3  # apex, left, right slivers


def test_vertex_halo_centers(renderer: SierpinskiCairoSource) -> None:
    geom = renderer.geometry_cache(target_depth=2, canvas_w=1280, canvas_h=720)
    assert len(geom.vertex_halo_centers) == 3
    for pt in geom.vertex_halo_centers:
        assert len(pt) == 2
        assert all(isinstance(c, float) for c in pt)


def test_edge_polylines_per_path(renderer: SierpinskiCairoSource) -> None:
    geom = renderer.geometry_cache(target_depth=3, canvas_w=1280, canvas_h=720)
    assert "L0.top" in geom.edge_polylines
    assert "L0.left" in geom.edge_polylines
    assert "L0.right" in geom.edge_polylines
    # Root edges should be simple two-point polylines.
    for key in ("L0.top", "L0.left", "L0.right"):
        polyline = geom.edge_polylines[key]
        assert len(polyline) >= 2


def test_geometry_cache_deterministic(renderer: SierpinskiCairoSource) -> None:
    """Same canvas+depth returns identical geometry (for caching)."""
    a = renderer.geometry_cache(target_depth=3, canvas_w=1280, canvas_h=720)
    b = renderer.geometry_cache(target_depth=3, canvas_w=1280, canvas_h=720)
    assert a.all_triangles == b.all_triangles
    assert a.vertex_halo_centers == b.vertex_halo_centers


def test_per_level_stroke_alpha_table(renderer: SierpinskiCairoSource) -> None:
    """Spec §4.2 — per-level stroke/alpha table, L0..L4."""
    from agents.studio_compositor.sierpinski_renderer import LEVEL_STROKE_ALPHA

    assert LEVEL_STROKE_ALPHA[0] == (2.0, 6.0, 0.80, 0.15)
    assert LEVEL_STROKE_ALPHA[1] == (1.5, 4.5, 0.80, 0.15)
    assert LEVEL_STROKE_ALPHA[2] == (1.25, 3.0, 0.70, 0.10)
    assert LEVEL_STROKE_ALPHA[3] == (1.0, 1.8, 0.55, 0.06)
    # L4 has no glow stroke — represented as 0.0 glow stroke + 0.0 glow alpha.
    assert LEVEL_STROKE_ALPHA[4] == (0.75, 0.0, 0.35, 0.0)
