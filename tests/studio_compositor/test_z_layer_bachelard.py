"""Z-layer Bachelardian house invariants (ARI L12).

Each z-layer band should have distinct visual character. Slow archival
wards sit in the cellar (lower z), fast responsive wards in the attic
(higher z). The test pins the rate→z mapping so future layout changes
don't collapse the house back to a flat plane.

Bachelardian house bands:
  z=30  CELLAR  — 0.5Hz slow lore, research posters, archival
  z=35  GROUND  — 1-2Hz operational, everyday status
  z=40  UPPER   — 6Hz animated expression, reveal
  z=45  ATTIC   — 15Hz+ fast instrument, immediate
"""

from __future__ import annotations

import json
from pathlib import Path

LAYOUT_PATH = Path(__file__).resolve().parents[2] / "config" / "compositor-layouts" / "default.json"

RATE_TO_Z_BAND: dict[float, int] = {
    0.5: 30,
    1.0: 35,
    2.0: 35,
    6.0: 40,
    15.0: 45,
}


def _load_layout() -> dict:
    return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))


def test_no_flat_z35_dump() -> None:
    """The old z=35 dump must not reappear — wards must be stratified."""
    layout = _load_layout()
    z35_surfaces = [s["id"] for s in layout.get("surfaces", []) if s.get("z_order") == 35]
    assert len(z35_surfaces) <= 8, (
        f"Too many surfaces at z=35 ({len(z35_surfaces)}) — "
        f"stratify by rate per Bachelardian house: {z35_surfaces}"
    )


def test_slow_wards_below_fast_wards_in_stratified_band() -> None:
    """Within the stratified ward band (z=30-45), slow wards sit below fast."""
    layout = _load_layout()
    assignments = {a["surface"]: a["source"] for a in layout.get("assignments", [])}
    sources = {s["id"]: s for s in layout.get("sources", [])}

    slow_z: list[int] = []
    fast_z: list[int] = []
    for s in layout.get("surfaces", []):
        z = s.get("z_order", 0)
        if not (30 <= z <= 45):
            continue
        src_id = assignments.get(s["id"], "")
        src = sources.get(src_id, {})
        rate = src.get("rate_hz")
        if rate and rate <= 0.5:
            slow_z.append(z)
        elif rate and rate >= 6.0:
            fast_z.append(z)

    if slow_z and fast_z:
        assert max(slow_z) <= min(fast_z), (
            f"Slow wards (max z={max(slow_z)}) must be below "
            f"fast wards (min z={min(fast_z)}) in the stratified band"
        )


def test_z_band_spread_minimum() -> None:
    """Rate-based wards must span at least 3 distinct z-order values."""
    layout = _load_layout()
    assignments = {a["surface"]: a["source"] for a in layout.get("assignments", [])}
    sources = {s["id"]: s for s in layout.get("sources", [])}

    z_values: set[int] = set()
    for s in layout.get("surfaces", []):
        src_id = assignments.get(s["id"], "")
        src = sources.get(src_id, {})
        if src.get("rate_hz"):
            z_values.add(s.get("z_order", 0))

    assert len(z_values) >= 3, (
        f"Rate-based wards must span >=3 z bands, got {len(z_values)}: {sorted(z_values)}"
    )
