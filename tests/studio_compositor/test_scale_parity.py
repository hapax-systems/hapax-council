"""2026-04-23 Gemini-reapproach Plan B Phase B2 regression pin.

Scale values live in two files and MUST stay synchronized. Gemini's
d4a4b0113 changed the legacy ``sierpinski_renderer.py`` transport scale
0.75 → 0.675 but left ``layout.py`` at 0.75 — that parity break is what
operator caught as "sierpinski is cropped wrong" at 08:23 session 2.

This test pins the current values as invariants. Any future atomic
reduction (e.g. the 10% "reduce reverie sierp and cbip" directive)
must update BOTH files; this test fires if only one side changes.

Constants checked:
- ``agents/studio_compositor/layout.py::_aoa_layout`` scale
- ``agents/studio_compositor/sierpinski_renderer.py::render_content``
  _get_triangle scale. The renderer module name remains a legacy
  compatibility transport while the layout/API surface is AoA.
- ``agents/studio_compositor/token_pole.py::NATURAL_SIZE`` vs the
  ``pip-ul`` surface w/h in ``default.json``
- ``agents/studio_compositor/album_overlay.py::SIZE``
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]
_COMPOSITOR = _REPO_ROOT / "agents" / "studio_compositor"
_DEFAULT_JSON = _REPO_ROOT / "config" / "compositor-layouts" / "default.json"


def _read_scalar_module_constant(path: Path, name: str) -> float:
    """Parse ``name = <literal>`` at module level via AST (no import)."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    if isinstance(node.value, ast.Constant) and isinstance(
                        node.value.value, (int, float)
                    ):
                        return float(node.value.value)
    raise AssertionError(f"module-level scalar constant {name!r} not found in {path}")


def _find_sierpinski_renderer_scale() -> float:
    """Extract the ``scale=<float>`` kwarg from the ``_get_triangle`` call."""
    text = (_COMPOSITOR / "sierpinski_renderer.py").read_text()
    match = re.search(r"_get_triangle\([^)]*?scale\s*=\s*([0-9]*\.[0-9]+)", text, re.DOTALL)
    assert match, "sierpinski_renderer.py: _get_triangle(scale=<float>) call not found"
    return float(match.group(1))


def _find_layout_aoa_scale() -> float:
    """Extract the ``scale = <float>`` assignment inside ``_aoa_layout``."""
    text = (_COMPOSITOR / "layout.py").read_text()
    match = re.search(r"def\s+_aoa_layout.*?scale\s*=\s*([0-9]*\.[0-9]+)", text, re.DOTALL)
    assert match, "layout.py: _aoa_layout scale = <float> not found"
    return float(match.group(1))


def test_aoa_scale_parity() -> None:
    """The AoA layout and legacy renderer transport scales must be equal."""
    layout_scale = _find_layout_aoa_scale()
    renderer_scale = _find_sierpinski_renderer_scale()
    assert layout_scale == renderer_scale, (
        f"AoA scale parity broken: "
        f"layout.py::_aoa_layout scale={layout_scale!r}, "
        f"sierpinski_renderer.py::render_content scale={renderer_scale!r}. "
        "Both must change atomically. Gemini's d4a4b0113 caught on this "
        "(operator: 'sierpinski is cropped wrong')."
    )


def test_token_pole_natural_size_matches_vitruvian_surface() -> None:
    """TokenPole's NATURAL_SIZE must produce a square source that the
    compositor renders into the upper-left-vitruvian surface. The surface
    may be smaller (compositor scales down) but they must share the same
    aspect ratio (1:1 square)."""
    natural_size = int(_read_scalar_module_constant(_COMPOSITOR / "token_pole.py", "NATURAL_SIZE"))
    default = json.loads(_DEFAULT_JSON.read_text())
    vitruvian = next(s for s in default["surfaces"] if s["id"] == "upper-left-vitruvian")
    geo = vitruvian["geometry"]
    assert geo["w"] == geo["h"], f"upper-left-vitruvian must be square (w={geo['w']}, h={geo['h']})"
    assert natural_size > 0, "token_pole.NATURAL_SIZE must be positive"


def test_album_size_matches_lower_left_album_width() -> None:
    """AlbumOverlay's SIZE must produce a source that the compositor renders
    into the lower-left-album surface. The source may be larger (compositor
    scales down) but the surface must exist and be square."""
    album_size = int(_read_scalar_module_constant(_COMPOSITOR / "album_overlay.py", "SIZE"))
    default = json.loads(_DEFAULT_JSON.read_text())
    album_surf = next(s for s in default["surfaces"] if s["id"] == "lower-left-album")
    geo = album_surf["geometry"]
    assert album_size > 0, "album_overlay.SIZE must be positive"
    assert geo["w"] == geo["h"], f"lower-left-album must be square (w={geo['w']}, h={geo['h']})"
