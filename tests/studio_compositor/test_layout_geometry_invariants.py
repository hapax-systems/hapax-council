"""Layout-geometry invariants across the full layout corpus.

Sister to ``test_layout_integrity_full_corpus.py`` (cairo class_name +
assignment-reference resolution). This file adds a third invariant:

**Surface rect geometry must be positive.** A surface declaration with
``w <= 0`` or ``h <= 0`` either silently disappears at composite time
(GStreamer's compositor accepts width=1+x=-10 as a "hidden" tile) or
crashes the Cairo render path on a zero-area surface. Either failure
is invisible until that surface is recruited on the live broadcast.

The compositor's tile-layout module legitimately uses
``TileRect(x=-10, y=-10, w=1, h=1)`` as a hidden-camera marker
(``_hidden_tile()`` in ``agents/studio_compositor/layout.py``), but
that's runtime-computed — it never appears in the JSON layout files.
Any rect-kind surface in the on-disk corpus should have positive
non-trivial dimensions.

Pure layout-side regression pin — no source touched, no behavior
change. Surfaces with non-rect geometry kinds (``tile``,
``video_out``, ``wgpu_binding``) are skipped — their dimensions are
either implicit (``tile`` is sized by the layout engine) or
non-applicable (``wgpu_binding`` resolves to a GPU resource, not a
2D rect). New layouts added under the discovered roots get coverage
automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Minimum sensible rect dimension. Below this the surface is either
# invisible at typical broadcast resolution (1920×1080) or actively
# malformed. 4 px is permissive — a 4×4 surface IS visible at the
# stream's pixel density and lets unusual but legitimate small
# surfaces (timing-dot indicators, debug pixels) pass while still
# catching obvious typos like w=0 or h=-1.
_MIN_RECT_DIM: int = 4


def _all_layout_paths() -> list[Path]:
    roots = (
        REPO_ROOT / "config" / "layouts",
        REPO_ROOT / "config" / "compositor-layouts",
        REPO_ROOT / "config" / "compositor-layouts" / "examples",
    )
    paths: list[Path] = []
    for root in roots:
        if root.exists():
            paths.extend(sorted(root.glob("*.json")))
    return paths


ALL_LAYOUT_PATHS: list[Path] = _all_layout_paths()


@pytest.mark.parametrize(
    "layout_path",
    ALL_LAYOUT_PATHS,
    ids=lambda p: p.name,
)
def test_rect_surfaces_have_positive_dimensions(layout_path: Path) -> None:
    layout = json.loads(layout_path.read_text())
    errors: list[str] = []
    for surface in layout.get("surfaces", []):
        geometry = surface.get("geometry") or {}
        if geometry.get("kind") != "rect":
            continue
        surface_id = surface.get("id", "<no-id>")
        w = geometry.get("w")
        h = geometry.get("h")
        if not isinstance(w, int) or w < _MIN_RECT_DIM:
            errors.append(f"surface {surface_id!r}: w={w!r} (must be int >= {_MIN_RECT_DIM})")
        if not isinstance(h, int) or h < _MIN_RECT_DIM:
            errors.append(f"surface {surface_id!r}: h={h!r} (must be int >= {_MIN_RECT_DIM})")

    assert not errors, (
        f"{layout_path.relative_to(REPO_ROOT)} declares rect surfaces "
        f"with non-positive dimensions:\n  " + "\n  ".join(errors)
    )
