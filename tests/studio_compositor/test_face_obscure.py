"""Tests for `agents.studio_compositor.face_obscure` (task #129).

Exercises the FaceObscurer's geometry and color invariants. Integration with
the per-camera capture pipeline is a separate follow-up (spec §6).
"""

from __future__ import annotations

import numpy as np
import pytest

from agents.studio_compositor.face_obscure import (
    DEFAULT_BLOCK_SIZE,
    DEFAULT_MARGIN,
    GRUVBOX_DARK_BGR,
    BBox,
    FaceObscurer,
)


def _make_frame(h: int = 480, w: int = 640, fill: int = 200) -> np.ndarray:
    """Build a uniform BGR frame distinct from Gruvbox-dark."""
    return np.full((h, w, 3), fill, dtype=np.uint8)


class TestPassThrough:
    def test_no_bboxes_returns_frame_unchanged(self):
        # Spec §11 rollback contract: pass-through must be byte-identical.
        obscurer = FaceObscurer()
        frame = _make_frame()
        result = obscurer.obscure(frame, [])

        assert result is frame  # identity, not just equality
        assert np.array_equal(result, frame)

    def test_empty_list_does_not_mutate_input(self):
        obscurer = FaceObscurer()
        frame = _make_frame()
        original = frame.copy()
        obscurer.obscure(frame, [])
        assert np.array_equal(frame, original)


class TestObscureGeometry:
    def test_nonempty_returns_copy_not_mutation(self):
        obscurer = FaceObscurer()
        frame = _make_frame()
        original = frame.copy()
        result = obscurer.obscure(frame, [BBox(100, 100, 200, 200)])

        # Input is untouched.
        assert np.array_equal(frame, original)
        # Output is a distinct array.
        assert result is not frame

    def test_bbox_region_is_gruvbox_dark(self):
        # The solid floor must equal the Gruvbox-dark color. Pixelation on
        # top of a solid fill is a no-op, so the region stays uniform.
        obscurer = FaceObscurer(margin=0.0, block_size=16)
        frame = _make_frame()
        bbox = BBox(64, 64, 192, 192)  # 128x128, block-aligned
        result = obscurer.obscure(frame, [bbox])

        region = result[64:192, 64:192]
        # Every pixel of the obscured region equals Gruvbox-dark BGR.
        expected = np.array(GRUVBOX_DARK_BGR, dtype=np.uint8)
        assert np.all(region == expected), (
            f"obscured region should be Gruvbox-dark {GRUVBOX_DARK_BGR}, "
            f"got unique values {np.unique(region.reshape(-1, 3), axis=0)}"
        )

    def test_pixels_outside_bbox_untouched(self):
        obscurer = FaceObscurer(margin=0.0)
        frame = _make_frame(fill=200)
        bbox = BBox(100, 100, 200, 200)
        result = obscurer.obscure(frame, [bbox])

        # Corners of the frame are far from the bbox and must be unchanged.
        assert result[0, 0, 0] == 200
        assert result[0, -1, 0] == 200
        assert result[-1, 0, 0] == 200
        assert result[-1, -1, 0] == 200

    def test_margin_expansion_grows_region(self):
        # With 20% margin, a 100x100 bbox expands by 20 px per side → 140x140.
        obscurer = FaceObscurer(margin=0.20)
        frame = _make_frame()
        bbox = BBox(200, 200, 300, 300)  # 100x100
        result = obscurer.obscure(frame, [bbox])

        # Pixel just inside the expanded region (at x=181, original edge - 19)
        # must be Gruvbox-dark, while pixel outside (x=179) must be unchanged.
        # Expanded bbox: x1=180, y1=180, x2=320, y2=320.
        assert tuple(result[250, 181]) == GRUVBOX_DARK_BGR
        assert tuple(result[250, 319]) == GRUVBOX_DARK_BGR
        # Just outside the expansion on the left edge.
        assert tuple(result[250, 179]) != GRUVBOX_DARK_BGR
        assert result[250, 179, 0] == 200  # original fill
        # Just outside on the right edge.
        assert tuple(result[250, 321]) != GRUVBOX_DARK_BGR

    def test_margin_expansion_clamps_to_frame_bounds(self):
        # A bbox at the frame edge expanded by 20% must clamp; no IndexError,
        # and the visible portion must still be obscured.
        obscurer = FaceObscurer(margin=0.50)  # aggressive to force clamping
        frame = _make_frame(h=100, w=100)
        bbox = BBox(10, 10, 40, 40)  # expands to (-5, -5, 55, 55), clamps to (0, 0, 55, 55)
        result = obscurer.obscure(frame, [bbox])

        # (0, 0) must now be part of the obscured region.
        assert tuple(result[0, 0]) == GRUVBOX_DARK_BGR
        # (54, 54) inside expansion must be obscured.
        assert tuple(result[54, 54]) == GRUVBOX_DARK_BGR
        # (60, 60) outside expansion must remain the original fill.
        assert result[60, 60, 0] == 200

    def test_multiple_bboxes_all_obscured(self):
        obscurer = FaceObscurer(margin=0.0)
        frame = _make_frame()
        result = obscurer.obscure(
            frame,
            [BBox(10, 10, 50, 50), BBox(200, 200, 260, 260)],
        )

        # Both regions obscured.
        assert tuple(result[30, 30]) == GRUVBOX_DARK_BGR
        assert tuple(result[230, 230]) == GRUVBOX_DARK_BGR
        # Between them, untouched.
        assert result[100, 100, 0] == 200

    def test_accepts_tuple_bboxes(self):
        # SCRFD returns floats; caller may pass tuples directly.
        obscurer = FaceObscurer(margin=0.0)
        frame = _make_frame()
        result = obscurer.obscure(frame, [(50.0, 50.0, 150.0, 150.0)])

        assert tuple(result[100, 100]) == GRUVBOX_DARK_BGR


class TestConfigAndDefaults:
    def test_defaults_match_spec(self):
        # Spec §3.3: 20% margin, 16 px blocks, Gruvbox-dark.
        assert DEFAULT_MARGIN == 0.20
        assert DEFAULT_BLOCK_SIZE == 16
        assert GRUVBOX_DARK_BGR == (40, 40, 40)

        obscurer = FaceObscurer()
        assert obscurer.margin == 0.20
        assert obscurer.block_size == 16
        assert obscurer.color_bgr == (40, 40, 40)

    def test_rejects_negative_margin(self):
        with pytest.raises(ValueError):
            FaceObscurer(margin=-0.1)

    def test_rejects_nonpositive_block_size(self):
        with pytest.raises(ValueError):
            FaceObscurer(block_size=0)

    def test_rejects_malformed_frame(self):
        obscurer = FaceObscurer()
        with pytest.raises(ValueError):
            obscurer.obscure(np.zeros((10, 10), dtype=np.uint8), [BBox(0, 0, 5, 5)])
