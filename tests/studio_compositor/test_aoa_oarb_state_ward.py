from __future__ import annotations

from pathlib import Path

import cairo

from agents.studio_compositor.aoa_oarb_state_ward import (
    AoaOarbStateCairoSource,
    load_aoa_oarb_contract,
)
from agents.studio_compositor.cairo_sources import get_cairo_source_class

REPO_ROOT = Path(__file__).parents[2]
CONTRACT_PATH = REPO_ROOT / "config" / "screwm-quake-media-mounts.json"


def _render_source(source: AoaOarbStateCairoSource) -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 540, 180)
    cr = cairo.Context(surface)
    source.render(cr, 540, 180, t=1.5, state={})
    surface.flush()
    return surface


def _visible_luma(surface: cairo.ImageSurface) -> tuple[float, int]:
    width = surface.get_width()
    height = surface.get_height()
    stride = surface.get_stride()
    data = bytes(surface.get_data())
    luma_total = 0.0
    visible_pixels = 0
    for y in range(height):
        row = data[y * stride : y * stride + width * 4]
        for index in range(0, len(row), 4):
            b, g, r, a = row[index : index + 4]
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            luma_total += luma
            if a > 0 and luma > 24.0:
                visible_pixels += 1
    return luma_total / (width * height * 255.0), visible_pixels


def test_aoa_oarb_contract_reads_current_perfect_fit_geometry() -> None:
    contract = load_aoa_oarb_contract(CONTRACT_PATH)

    assert contract.status == "loaded"
    assert contract.geometry_revision == "aoa-regular-tetrix-v7-30pct-larger-perfect-fit-oarb"
    assert contract.inner_void_radius_fill_ratio == 1.0
    assert contract.enclosure_clearance_ratio == 1.0
    assert contract.physical_radius == 344.42
    assert contract.leaf_face_edge_units == 105.46
    assert contract.aoa_parent_edge_units == 1687.0
    assert contract.fractal_face_count == 1024
    assert contract.texture_size == (2048, 1024)
    assert contract.sphere_source_id == "youtube-canary"
    assert contract.atlas_source_id == "aoa-face-control-atlas"


def test_aoa_oarb_state_source_is_registered() -> None:
    cls = get_cairo_source_class("AoaOarbStateCairoSource")
    assert cls is AoaOarbStateCairoSource


def test_aoa_oarb_state_ward_renders_visible_contract_panel() -> None:
    surface = _render_source(AoaOarbStateCairoSource(CONTRACT_PATH))
    mean_luma, visible_pixels = _visible_luma(surface)

    assert mean_luma > 0.055
    assert visible_pixels > 10_000


def test_aoa_oarb_state_ward_degrades_visibly_when_contract_missing(tmp_path: Path) -> None:
    surface = _render_source(AoaOarbStateCairoSource(tmp_path / "missing.json"))
    mean_luma, visible_pixels = _visible_luma(surface)

    assert mean_luma > 0.045
    assert visible_pixels > 9_000
