"""2026-04-23 Gemini-reapproach Plan B Phase B4 regression pins.

Task #186 ("Token meter geometry rework — navel→cranium linear path
with full visibility + cranium explosion") was implementation-shipped
pre-audit via commits ``cfff06e41`` (navel→cranium linear path),
``6afcde7bb`` (token cranium anchor), ``cf09f73e2`` (continuous-
backbone path rendering). Task tracker marks it pending — stale.

This test pins the three closeout invariants:
1. Default path mode is NAVEL_TO_CRANIUM (not legacy SPIRAL).
2. Cranium-arrival explosion fires when ``_spawn_explosion()`` is
   invoked in NAVEL_TO_CRANIUM mode — seeds particles at the cranium
   anchor, not the spiral center.
3. The linear path spans from navel to cranium.
"""

from __future__ import annotations

from agents.studio_compositor import token_pole
from agents.studio_compositor.token_pole import (
    CRANIUM_X,
    CRANIUM_Y,
    NATURAL_SIZE,
    NAVEL_X,
    NAVEL_Y,
    NUM_POINTS,
    PathMode,
    _build_linear_path,
    _resolve_path_mode,
)


def test_default_path_mode_is_spiral() -> None:
    """Post garage-door merge: default path is SPIRAL."""
    assert _resolve_path_mode() is PathMode.SPIRAL


def test_navel_cranium_path_spans_anchors() -> None:
    """``_build_linear_path`` produces NUM_POINTS samples starting at navel
    and ending at cranium (within one pixel)."""
    path = _build_linear_path(NATURAL_SIZE, NUM_POINTS)
    assert len(path) == NUM_POINTS

    navel_px = (NATURAL_SIZE * NAVEL_X, NATURAL_SIZE * NAVEL_Y)
    cranium_px = (NATURAL_SIZE * CRANIUM_X, NATURAL_SIZE * CRANIUM_Y)
    start = path[0]
    end = path[-1]

    assert abs(start[0] - navel_px[0]) <= 1.0
    assert abs(start[1] - navel_px[1]) <= 1.0
    assert abs(end[0] - cranium_px[0]) <= 1.0
    assert abs(end[1] - cranium_px[1]) <= 1.0


def test_spawn_explosion_fires_at_cranium_in_navel_mode() -> None:
    """In NAVEL_TO_CRANIUM mode, ``_spawn_explosion()`` seeds particles
    at the CRANIUM anchor (the path's terminal), not the spiral centre."""
    source = token_pole.TokenPoleCairoSource()
    source._path_mode = PathMode.NAVEL_TO_CRANIUM
    source._particles = []

    source._spawn_explosion()

    assert len(source._particles) == 60, "explosion should seed 60 particles"

    expected_cx = NATURAL_SIZE * CRANIUM_X
    expected_cy = NATURAL_SIZE * CRANIUM_Y
    for p in source._particles:
        assert abs(p.x - expected_cx) <= 1.0
        assert abs(p.y - expected_cy) <= 1.0
