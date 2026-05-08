"""Force-field camera layout — Arnheim perceptual force distribution.

Pins the force-field layout's structural properties: polycentric
distribution, cross-canvas spread, quadrant coverage, equal sizing,
centroid balance, and semantic axis tension.
"""

from __future__ import annotations

import math

import pytest

from agents.studio_compositor.config import _DEFAULT_CAMERAS, OUTPUT_HEIGHT, OUTPUT_WIDTH
from agents.studio_compositor.layout import compute_tile_layout
from agents.studio_compositor.models import CameraSpec, TileRect

CANVAS_W = OUTPUT_WIDTH
CANVAS_H = OUTPUT_HEIGHT
CAMERAS = [CameraSpec(**c) for c in _DEFAULT_CAMERAS]


@pytest.fixture
def ff_layout() -> dict[str, TileRect]:
    return compute_tile_layout(CAMERAS, CANVAS_W, CANVAS_H, mode="forcefield")


def _visible_tiles(layout: dict[str, TileRect]) -> list[tuple[str, TileRect]]:
    return [(r, t) for r, t in layout.items() if not r.startswith("_")]


def _centroid(tiles: list[tuple[str, TileRect]]) -> tuple[float, float]:
    cx = sum(t.x + t.w / 2 for _, t in tiles) / len(tiles)
    cy = sum(t.y + t.h / 2 for _, t in tiles) / len(tiles)
    return cx, cy


class TestForcefieldBasics:
    def test_all_cameras_placed(self, ff_layout: dict[str, TileRect]) -> None:
        visible = _visible_tiles(ff_layout)
        assert len(visible) == len(CAMERAS)

    def test_mode_string_selects_forcefield(self) -> None:
        layout = compute_tile_layout(CAMERAS, CANVAS_W, CANVAS_H, mode="forcefield")
        assert len(layout) == len(CAMERAS)

    def test_all_tiles_on_canvas(self, ff_layout: dict[str, TileRect]) -> None:
        for role, tile in _visible_tiles(ff_layout):
            assert tile.x >= 0, f"{role} x={tile.x}"
            assert tile.y >= 0, f"{role} y={tile.y}"
            assert tile.x + tile.w <= CANVAS_W, f"{role} exceeds canvas width"
            assert tile.y + tile.h <= CANVAS_H, f"{role} exceeds canvas height"


class TestEqualSizing:
    """No hero — all cameras same size (design brief principle #3)."""

    def test_all_tiles_equal_width(self, ff_layout: dict[str, TileRect]) -> None:
        widths = {t.w for _, t in _visible_tiles(ff_layout)}
        assert len(widths) == 1, f"Expected uniform width, got {widths}"

    def test_all_tiles_equal_height(self, ff_layout: dict[str, TileRect]) -> None:
        heights = {t.h for _, t in _visible_tiles(ff_layout)}
        assert len(heights) == 1, f"Expected uniform height, got {heights}"

    def test_tiles_are_16x9(self, ff_layout: dict[str, TileRect]) -> None:
        for role, tile in _visible_tiles(ff_layout):
            ratio = tile.w / tile.h
            assert abs(ratio - 16 / 9) < 0.1, f"{role} aspect {ratio:.2f} != 16:9"


class TestForceFieldDistribution:
    """Arnheim force-field: cameras as mass-points across the full canvas."""

    def test_bounding_box_covers_majority_of_canvas(self, ff_layout: dict[str, TileRect]) -> None:
        visible = _visible_tiles(ff_layout)
        min_x = min(t.x for _, t in visible)
        min_y = min(t.y for _, t in visible)
        max_x = max(t.x + t.w for _, t in visible)
        max_y = max(t.y + t.h for _, t in visible)
        bb_pct = ((max_x - min_x) * (max_y - min_y)) / (CANVAS_W * CANVAS_H)
        assert bb_pct > 0.60, f"Bounding box {bb_pct:.0%} < 60% — cameras too clustered"

    def test_centroid_near_canvas_center(self, ff_layout: dict[str, TileRect]) -> None:
        visible = _visible_tiles(ff_layout)
        cx, cy = _centroid(visible)
        ideal_cx, ideal_cy = CANVAS_W / 2, CANVAS_H / 2
        offset = math.sqrt((cx - ideal_cx) ** 2 + (cy - ideal_cy) ** 2)
        max_offset = math.sqrt(ideal_cx**2 + ideal_cy**2)
        assert offset / max_offset < 0.15, (
            f"Centroid ({cx:.0f},{cy:.0f}) too far from center: "
            f"{offset:.0f}px ({offset / max_offset:.0%} of max)"
        )

    def test_spread_exceeds_50_percent(self, ff_layout: dict[str, TileRect]) -> None:
        visible = _visible_tiles(ff_layout)
        cx, cy = _centroid(visible)
        rms = math.sqrt(
            sum((t.x + t.w / 2 - cx) ** 2 + (t.y + t.h / 2 - cy) ** 2 for _, t in visible)
            / len(visible)
        )
        max_spread = math.sqrt((CANVAS_W / 2) ** 2 + (CANVAS_H / 2) ** 2)
        assert rms / max_spread > 0.50, (
            f"Spread {rms:.0f}/{max_spread:.0f} = {rms / max_spread:.0%} < 50%"
        )

    def test_all_four_quadrants_populated(self, ff_layout: dict[str, TileRect]) -> None:
        quads: set[str] = set()
        for _, tile in _visible_tiles(ff_layout):
            cx = tile.x + tile.w / 2
            cy = tile.y + tile.h / 2
            q = ("L" if cx < CANVAS_W / 2 else "R") + ("T" if cy < CANVAS_H / 2 else "B")
            quads.add(q)
        missing = {"LT", "RT", "LB", "RB"} - quads
        assert not missing, f"Missing quadrants: {missing}"

    def test_no_two_cameras_overlap(self, ff_layout: dict[str, TileRect]) -> None:
        visible = _visible_tiles(ff_layout)
        for i, (r1, t1) in enumerate(visible):
            for r2, t2 in visible[i + 1 :]:
                overlap_x = max(0, min(t1.x + t1.w, t2.x + t2.w) - max(t1.x, t2.x))
                overlap_y = max(0, min(t1.y + t1.h, t2.y + t2.h) - max(t1.y, t2.y))
                overlap_area = overlap_x * overlap_y
                assert overlap_area == 0, f"{r1} and {r2} overlap by {overlap_area}px²"


class TestSemanticAxisTension:
    """Semantic pairs placed at cross-canvas positions for max tension."""

    def _distance(self, layout: dict[str, TileRect], r1: str, r2: str) -> float:
        t1, t2 = layout[r1], layout[r2]
        cx1, cy1 = t1.x + t1.w / 2, t1.y + t1.h / 2
        cx2, cy2 = t2.x + t2.w / 2, t2.y + t2.h / 2
        return math.sqrt((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2)

    def test_watching_axis_spans_canvas(self, ff_layout: dict[str, TileRect]) -> None:
        d = self._distance(ff_layout, "brio-synths", "c920-room")
        diag = math.sqrt(CANVAS_W**2 + CANVAS_H**2)
        assert d / diag > 0.50, f"Watching axis {d:.0f}px = {d / diag:.0%} of diagonal < 50%"

    def test_activity_axis_spans_canvas(self, ff_layout: dict[str, TileRect]) -> None:
        d = self._distance(ff_layout, "brio-operator", "c920-desk")
        diag = math.sqrt(CANVAS_W**2 + CANVAS_H**2)
        assert d / diag > 0.50, f"Activity axis {d:.0f}px = {d / diag:.0%} of diagonal < 50%"


class TestScaling:
    """Force-field adapts to different canvas sizes."""

    @pytest.mark.parametrize(
        "cw,ch",
        [(1920, 1080), (1280, 720), (640, 360), (3840, 2160)],
        ids=["1080p", "720p", "360p", "4k"],
    )
    def test_all_tiles_fit_any_canvas(self, cw: int, ch: int) -> None:
        layout = compute_tile_layout(CAMERAS, cw, ch, mode="forcefield")
        for role, tile in layout.items():
            assert tile.x >= 0 and tile.y >= 0, f"{role} off-canvas at ({tile.x},{tile.y})"
            assert tile.x + tile.w <= cw, f"{role} exceeds width at {cw}"
            assert tile.y + tile.h <= ch, f"{role} exceeds height at {ch}"


class TestFewCameras:
    """Graceful degradation with fewer cameras."""

    def test_single_camera(self) -> None:
        layout = compute_tile_layout(CAMERAS[:1], CANVAS_W, CANVAS_H, mode="forcefield")
        assert len(layout) == 1

    def test_three_cameras(self) -> None:
        layout = compute_tile_layout(CAMERAS[:3], CANVAS_W, CANVAS_H, mode="forcefield")
        assert len(layout) == 3
        for _role, tile in layout.items():
            assert tile.x >= 0 and tile.y >= 0
            assert tile.x + tile.w <= CANVAS_W

    def test_empty_cameras(self) -> None:
        layout = compute_tile_layout([], CANVAS_W, CANVAS_H, mode="forcefield")
        assert layout == {}
