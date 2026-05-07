"""2026-04-23 Gemini-reapproach Plan B Phase B1 regression pin.

Operator reported in session 2 (2026-04-23 06:34 → 13:01 UTC) that
HOMAGE wards were overlapping each other. This test enforces that no
two HOMAGE / legibility / hothouse surfaces geometrically overlap in
the default layout. Axis-aligned rectangle intersection check; surfaces
are non-overlapping iff one's right-edge is left-of or equal-to the
other's left-edge OR one's bottom-edge is above or equal-to the other's
top-edge.

Only overlay surfaces are checked — `pip-*` quadrant surfaces host
multiple assigned sources and intentionally overlap with their own
content, and `video_out_*` surfaces are output sinks outside the
1920×1080 rendering canvas.

HARDM was retired 2026-04-23 (GEAL spec §12); the dot-matrix surface and
its spatial-separation pins are no longer part of this check.
"""

from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_JSON = Path(__file__).parents[2] / "config" / "compositor-layouts" / "default.json"

# Surfaces to check for overlap. Upper-band (y < 400) overlay surfaces
# must not collide with each other; lower-band legibility + GEM must not
# collide either.
# In the garage-door layout, the right-column surfaces intentionally
# overlap and rely on z-order stacking. Only check the upper-band +
# left-column overlay surfaces that must NOT overlap.
_OVERLAY_SURFACE_IDS = {
    "activity-header-top-mid",
    "recruitment-candidate-top",
    "thinking-indicator-tr",
    "pressure-gauge-ul",
    "whos-here-tc",
}


def _rects_intersect(a: dict, b: dict) -> bool:
    ax1, ay1 = a["x"], a["y"]
    ax2, ay2 = ax1 + a["w"], ay1 + a["h"]
    bx1, by1 = b["x"], b["y"]
    bx2, by2 = bx1 + b["w"], by1 + b["h"]
    return not (ax2 <= bx1 or bx2 <= ax1 or ay2 <= by1 or by2 <= ay1)


def test_no_overlay_surface_overlap() -> None:
    raw = json.loads(_DEFAULT_JSON.read_text())
    geos = {
        s["id"]: s["geometry"]
        for s in raw["surfaces"]
        if s["id"] in _OVERLAY_SURFACE_IDS and s["geometry"]["kind"] == "rect"
    }
    missing = _OVERLAY_SURFACE_IDS - geos.keys()
    assert not missing, f"expected overlay surfaces missing from default.json: {missing}"

    pairs = sorted(geos.items())
    overlaps = []
    for i, (a_id, a) in enumerate(pairs):
        for b_id, b in pairs[i + 1 :]:
            if _rects_intersect(a, b):
                overlaps.append(
                    (a_id, (a["x"], a["y"], a["w"], a["h"]), b_id, (b["x"], b["y"], b["w"], b["h"]))
                )
    assert not overlaps, (
        "overlay surfaces must not geometrically overlap — z-order dominance "
        "is not sufficient for operator legibility. Collisions:\n"
        + "\n".join(f"  {a} {ag} overlaps {b} {bg}" for a, ag, b, bg in overlaps)
    )


def test_upper_band_cluster_spatial_separation() -> None:
    """Upper-band legibility cluster must not collide.

    In the garage-door layout, whos-here-tc sits LEFT of thinking-indicator-tr
    at the same y; stance-indicator-right-column is in the right column below.
    Pins their positions so a future refactor can't silently re-introduce
    overlap.
    """
    raw = json.loads(_DEFAULT_JSON.read_text())
    geos = {s["id"]: s["geometry"] for s in raw["surfaces"] if s["geometry"]["kind"] == "rect"}

    thinking = geos["thinking-indicator-tr"]
    stance = geos["stance-indicator-right-column"]
    whos = geos["whos-here-tc"]

    # whos-here-tc is to the LEFT of thinking-indicator-tr (same row, no overlap).
    whos_rect = {"x": whos["x"], "y": whos["y"], "w": whos["w"], "h": whos["h"]}
    thinking_rect = {"x": thinking["x"], "y": thinking["y"], "w": thinking["w"], "h": thinking["h"]}
    assert not _rects_intersect(whos_rect, thinking_rect), (
        "whos-here-tc and thinking-indicator-tr must not overlap"
    )
    # stance-indicator and thinking-indicator must not overlap.
    stance_rect = {"x": stance["x"], "y": stance["y"], "w": stance["w"], "h": stance["h"]}
    assert not _rects_intersect(thinking_rect, stance_rect), (
        "thinking-indicator-tr and stance-indicator-right-column must not overlap"
    )
