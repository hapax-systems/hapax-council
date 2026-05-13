"""Tests for cairooverlay face-obscure painting path (task #129 live pipeline fix).

Verifies that the face_obscure_integration bbox cache is populated by
obscure_frame_for_camera and that _paint_face_obscure_rects reads the cache
and paints Gruvbox-dark rectangles at the correct composite tile coordinates.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import cairo
import numpy as np
import pytest

from agents.studio_compositor.face_obscure import BBox
from agents.studio_compositor.face_obscure_integration import (
    get_live_bboxes,
    obscure_frame_for_camera,
    reset_pipeline_cache,
)
from agents.studio_compositor.overlay import _paint_face_obscure_rects


class _StubSource:
    def __init__(self, bboxes: list[BBox]) -> None:
        self._bboxes = bboxes

    def detect(self, frame: Any) -> list[BBox]:  # noqa: ARG002
        return list(self._bboxes)


@pytest.fixture(autouse=True)
def _clean_cache():
    reset_pipeline_cache()
    yield
    reset_pipeline_cache()


class TestLiveBboxCache:
    def test_empty_initially(self) -> None:
        assert get_live_bboxes() == {}

    def test_populated_after_obscure_frame(self) -> None:
        frame = np.full((360, 640, 3), 200, dtype=np.uint8)
        bbox = BBox(100, 80, 200, 180)
        env = {
            "HAPAX_FACE_OBSCURE_ACTIVE": "1",
            "HAPAX_FACE_OBSCURE_PERSON_FALLBACK_ACTIVE": "0",
        }
        obscure_frame_for_camera(
            frame,
            "brio-operator",
            env=env,
            source_factory=lambda _role: _StubSource([bbox]),
        )
        live = get_live_bboxes()
        assert "brio-operator" in live
        norms = live["brio-operator"]
        assert len(norms) == 1
        nx1, ny1, nx2, ny2 = norms[0]
        assert pytest.approx(nx1, abs=0.01) == 100 / 640
        assert pytest.approx(ny1, abs=0.01) == 80 / 360
        assert pytest.approx(nx2, abs=0.01) == 200 / 640
        assert pytest.approx(ny2, abs=0.01) == 180 / 360

    def test_empty_when_no_faces(self) -> None:
        frame = np.full((360, 640, 3), 200, dtype=np.uint8)
        env = {
            "HAPAX_FACE_OBSCURE_ACTIVE": "1",
            "HAPAX_FACE_OBSCURE_PERSON_FALLBACK_ACTIVE": "0",
        }
        obscure_frame_for_camera(
            frame,
            "c920-desk",
            env=env,
            source_factory=lambda _role: _StubSource([]),
        )
        live = get_live_bboxes()
        assert live.get("c920-desk") == []

    def test_cleared_on_reset(self) -> None:
        frame = np.full((360, 640, 3), 200, dtype=np.uint8)
        bbox = BBox(10, 10, 50, 50)
        env = {
            "HAPAX_FACE_OBSCURE_ACTIVE": "1",
            "HAPAX_FACE_OBSCURE_PERSON_FALLBACK_ACTIVE": "0",
        }
        obscure_frame_for_camera(
            frame,
            "brio-operator",
            env=env,
            source_factory=lambda _role: _StubSource([bbox]),
        )
        assert "brio-operator" in get_live_bboxes()
        reset_pipeline_cache()
        assert get_live_bboxes() == {}


class TestPaintFaceObscureRects:
    def _make_compositor(self, tile_layout: dict[str, Any]) -> MagicMock:
        comp = MagicMock()
        comp._tile_layout = tile_layout
        return comp

    def _make_tile(self, x: int, y: int, w: int, h: int) -> MagicMock:
        tile = MagicMock()
        tile.x = x
        tile.y = y
        tile.w = w
        tile.h = h
        return tile

    def test_paints_rect_at_tile_coords(self) -> None:
        tile = self._make_tile(x=0, y=0, w=960, h=540)
        compositor = self._make_compositor({"brio-operator": tile})

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 1080)
        cr = cairo.Context(surface)
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.paint()

        frame = np.full((360, 640, 3), 200, dtype=np.uint8)
        bbox = BBox(100, 80, 200, 180)
        env = {
            "HAPAX_FACE_OBSCURE_ACTIVE": "1",
            "HAPAX_FACE_OBSCURE_PERSON_FALLBACK_ACTIVE": "0",
        }
        obscure_frame_for_camera(
            frame,
            "brio-operator",
            env=env,
            source_factory=lambda _role: _StubSource([bbox]),
        )

        _paint_face_obscure_rects(compositor, cr)

        buf = surface.get_data()
        arr = np.frombuffer(buf, dtype=np.uint8).reshape((1080, 1920, 4))
        # Check a pixel inside the expected obscure region (centre of face rect)
        # Normalized bbox: (100/640, 80/360, 200/640, 180/360)
        # In tile (960×540): x=150, y=120 → x=300, y=270
        cx = int((100 / 640 + 200 / 640) / 2 * 960)
        cy = int((80 / 360 + 180 / 360) / 2 * 540)
        # ARGB32: B=0, G=1, R=2, A=3
        b, g, r = arr[cy, cx, 0], arr[cy, cx, 1], arr[cy, cx, 2]
        assert b == pytest.approx(40, abs=2)
        assert g == pytest.approx(40, abs=2)
        assert r == pytest.approx(40, abs=2)

    def test_noop_when_policy_disabled(self) -> None:
        tile = self._make_tile(x=0, y=0, w=960, h=540)
        compositor = self._make_compositor({"brio-operator": tile})
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
        cr = cairo.Context(surface)
        cr.set_source_rgb(1.0, 1.0, 1.0)
        cr.paint()

        with patch("shared.face_obscure_policy.is_feature_active", return_value=False):
            _paint_face_obscure_rects(compositor, cr)

        buf = surface.get_data()
        arr = np.frombuffer(buf, dtype=np.uint8).reshape((100, 100, 4))
        assert arr[50, 50, 2] == 255  # R channel still white — nothing painted

    def test_noop_when_no_tile_layout(self) -> None:
        compositor = self._make_compositor({})
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 100, 100)
        cr = cairo.Context(surface)
        _paint_face_obscure_rects(compositor, cr)
