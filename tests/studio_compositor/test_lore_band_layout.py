"""Pin the ytb-LORE-EXT lore-band wiring on the default layout.

The cc-task ``ward-family-compositor-layout-integration`` adds three
mid-band lore wards (precedent_ticker, programme_history,
research_instrument_dashboard) to the default compositor layout.
These tests pin:

* All three sources are present and bound to a registered
  ``CairoSource`` subclass.
* The three surfaces are non-overlapping rectangles inside the
  1920×1080 design canvas.
* All three live at the same y-coordinate (y=380), spaced
  side-by-side as the cc-task spec describes.
* Each source has a 0.5 Hz rate (cadence harmony — the lore band
  shares one beat).
* The source/surface assignment pairs match.

Sister fallback in ``compositor._FALLBACK_LAYOUT`` mirrors all of the
above; the existing ``test_fallback_layout_parses_to_same_shape_as_default_json``
in ``test_default_layout_loading.py`` covers that mirror invariant.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.compositor_model import Layout

DEFAULT_JSON = Path(__file__).parents[2] / "config" / "compositor-layouts" / "default.json"
LORE_SOURCE_IDS = (
    "precedent_ticker",
    "programme_history",
    "research_instrument_dashboard",
)
LORE_SURFACE_IDS = (
    "lore-precedent-ticker",
    "lore-programme-history",
    "lore-research-instrument-dashboard",
)


def _layout() -> Layout:
    return Layout.model_validate(json.loads(DEFAULT_JSON.read_text()))


def test_three_lore_sources_present() -> None:
    layout = _layout()
    by_id = {s.id: s for s in layout.sources}
    for sid in LORE_SOURCE_IDS:
        assert sid in by_id, f"missing lore source: {sid}"


def test_each_lore_source_class_is_registered() -> None:
    """Cairo class_name must resolve in the cairo_sources registry —
    otherwise the compositor crashes at startup."""
    from agents.studio_compositor.cairo_sources import get_cairo_source_class

    layout = _layout()
    by_id = {s.id: s for s in layout.sources}
    for sid in LORE_SOURCE_IDS:
        cn = by_id[sid].params.get("class_name")
        assert cn is not None
        cls = get_cairo_source_class(cn)
        assert cls.__name__ == cn


def test_lore_band_cadence_is_half_hz() -> None:
    """Cadence harmony per cc-task: each lore-band ward updates at
    0.5 Hz so they share the same slow beat."""
    layout = _layout()
    by_id = {s.id: s for s in layout.sources}
    for sid in LORE_SOURCE_IDS:
        source = by_id[sid]
        assert source.update_cadence == "rate", f"{sid}: cadence must be 'rate'"
        assert source.rate_hz == 0.5, f"{sid}: rate_hz must be 0.5 for lore-band cadence harmony"


def test_three_lore_surfaces_present_at_y_380() -> None:
    """Side-by-side rendering: all three surfaces share y=380 so the
    lore band reads as a single composed strip."""
    layout = _layout()
    by_id = {s.id: s for s in layout.surfaces}
    for sid in LORE_SURFACE_IDS:
        assert sid in by_id, f"missing lore surface: {sid}"
        geom = by_id[sid].geometry
        assert geom.kind == "rect"
        assert geom.y == 380, f"{sid}: lore band lives at y=380"


def test_lore_surfaces_non_overlapping_within_canvas() -> None:
    """Pin geometric non-overlap. If a future revision shifts a slot
    onto a sibling, this test fires."""
    layout = _layout()
    rects = []
    for sid in LORE_SURFACE_IDS:
        s = next(s for s in layout.surfaces if s.id == sid)
        g = s.geometry
        assert (g.x or 0) >= 0
        assert (g.y or 0) >= 0
        assert (g.x or 0) + (g.w or 0) <= 1920, f"{sid} extends past x=1920"
        assert (g.y or 0) + (g.h or 0) <= 1080, f"{sid} extends past y=1080"
        rects.append((sid, g.x, g.y, g.w, g.h))

    # Pairwise overlap check.
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            id_a, ax, ay, aw, ah = rects[i]
            id_b, bx, by, bw, bh = rects[j]
            overlap_x = ax < bx + bw and bx < ax + aw
            overlap_y = ay < by + bh and by < ay + ah
            assert not (overlap_x and overlap_y), f"{id_a} overlaps {id_b}"


def test_lore_assignments_pair_source_to_surface() -> None:
    layout = _layout()
    pairs = {(a.source, a.surface) for a in layout.assignments}
    for sid, surf_id in zip(LORE_SOURCE_IDS, LORE_SURFACE_IDS, strict=True):
        assert (sid, surf_id) in pairs, f"missing assignment: {sid} → {surf_id}"


def test_lore_band_z_order_above_pip_quadrants() -> None:
    """Lore band z=22 is below activity-header (30) and gem (30) —
    correct: the lore strip is supporting context, not headline.
    Pinned so a future revision raising z-order doesn't accidentally
    occlude the headline wards."""
    layout = _layout()
    for sid in LORE_SURFACE_IDS:
        s = next(s for s in layout.surfaces if s.id == sid)
        assert 10 <= s.z_order <= 25, f"{sid}: z_order out of supporting band"
