"""Tests for the visual_self_perception stimmung dimension and frame analysis."""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

from shared.stimmung import (
    _PERCEPTUAL_DIMENSION_NAMES,
    _PERCEPTUAL_STANCE_WEIGHT,
    _PERCEPTUAL_THRESHOLDS,
    DimensionReading,
    Stance,
    StimmungCollector,
    SystemStimmung,
)


class TestVisualSelfPerceptionDimension:
    def test_dimension_exists_on_model(self):
        s = SystemStimmung()
        assert hasattr(s, "visual_self_perception")
        assert s.visual_self_perception.value == 0.0

    def test_dimension_in_names_list(self):
        assert "visual_self_perception" in _PERCEPTUAL_DIMENSION_NAMES

    def test_perceptual_weight(self):
        assert _PERCEPTUAL_STANCE_WEIGHT == 0.2

    def test_perceptual_thresholds_prevent_degraded(self):
        assert _PERCEPTUAL_THRESHOLDS[1] > 1.0
        assert _PERCEPTUAL_THRESHOLDS[2] > 1.0

    def test_format_for_prompt_includes_dimension(self):
        s = SystemStimmung(
            visual_self_perception=DimensionReading(value=0.6, trend="rising", freshness_s=2.0),
        )
        text = s.format_for_prompt()
        assert "visual_self_perception: 0.60 (rising)" in text

    def test_non_nominal_includes_high_value(self):
        s = SystemStimmung(
            visual_self_perception=DimensionReading(value=0.5, freshness_s=1.0),
        )
        nn = s.non_nominal_dimensions
        assert "visual_self_perception" in nn

    def test_non_nominal_excludes_low_value(self):
        s = SystemStimmung(
            visual_self_perception=DimensionReading(value=0.1, freshness_s=1.0),
        )
        nn = s.non_nominal_dimensions
        assert "visual_self_perception" not in nn


class TestCollectorVisualSelfPerception:
    def test_update_records_value(self):
        c = StimmungCollector(enable_exploration=False)
        c.update_visual_self_perception(0.7)
        snap = c.snapshot()
        assert snap.visual_self_perception.value == 0.7

    def test_update_clamps_to_unit(self):
        c = StimmungCollector(enable_exploration=False)
        c.update_visual_self_perception(1.5)
        snap = c.snapshot()
        assert snap.visual_self_perception.value == 1.0

        c.update_visual_self_perception(-0.3)
        snap = c.snapshot()
        assert snap.visual_self_perception.value == 0.0

    def test_high_value_does_not_cause_degraded(self):
        c = StimmungCollector(enable_exploration=False)
        c.update_visual_self_perception(1.0)
        snap = c.snapshot()
        assert snap.overall_stance in (Stance.NOMINAL, Stance.CAUTIOUS)

    def test_max_value_can_reach_cautious(self):
        c = StimmungCollector(enable_exploration=False)
        c.update_visual_self_perception(1.0)
        snap = c.snapshot()
        # effective = 1.0 * 0.2 = 0.2, threshold for CAUTIOUS is 0.15
        assert snap.overall_stance == Stance.CAUTIOUS


class TestFramePerception:
    def _make_bmp(self, tmp_dir: Path, r: int, g: int, b: int) -> Path:
        """Create a minimal 2x2 BMP for testing."""
        path = tmp_dir / "test.bmp"
        width, height = 2, 2
        row_size = (width * 3 + 3) & ~3
        pixel_data_size = row_size * height
        file_size = 54 + pixel_data_size

        header = struct.pack(
            "<2sIHHI",
            b"BM",
            file_size,
            0,
            0,
            54,
        )
        dib = struct.pack(
            "<IiiHHIIiiII",
            40,
            width,
            height,
            1,
            24,
            0,
            pixel_data_size,
            2835,
            2835,
            0,
            0,
        )
        row = bytes([b, g, r] * width)
        padding = b"\x00" * (row_size - width * 3)
        pixels = (row + padding) * height

        path.write_bytes(header + dib + pixels)
        return path

    def test_analyze_missing_file(self):
        from agents.visual_layer_aggregator.frame_perception import analyze_frame

        result = analyze_frame(Path("/nonexistent/frame.jpg"))
        assert result is None

    def test_analyze_stale_file(self):
        from agents.visual_layer_aggregator.frame_perception import analyze_frame

        with tempfile.TemporaryDirectory() as td:
            p = self._make_bmp(Path(td), 128, 128, 128)
            with patch("time.time", return_value=p.stat().st_mtime + 20):
                result = analyze_frame(p)
            assert result is None

    def test_analyze_uniform_gray(self):
        from agents.visual_layer_aggregator.frame_perception import analyze_frame

        with tempfile.TemporaryDirectory() as td:
            p = self._make_bmp(Path(td), 128, 128, 128)
            with patch("time.time", return_value=p.stat().st_mtime + 1):
                result = analyze_frame(p)
            assert result is not None
            assert result.contrast_extremity == 1.0
            assert result.entropy_deficit > 0.5
            assert 0.0 <= result.composite <= 1.0

    def test_analyze_bright_white(self):
        from agents.visual_layer_aggregator.frame_perception import analyze_frame

        with tempfile.TemporaryDirectory() as td:
            p = self._make_bmp(Path(td), 255, 255, 255)
            with patch("time.time", return_value=p.stat().st_mtime + 1):
                result = analyze_frame(p)
            assert result is not None
            assert result.brightness_extremity > 0.8

    def test_composite_in_unit_range(self):
        from agents.visual_layer_aggregator.frame_perception import analyze_frame

        with tempfile.TemporaryDirectory() as td:
            p = self._make_bmp(Path(td), 50, 100, 200)
            with patch("time.time", return_value=p.stat().st_mtime + 1):
                result = analyze_frame(p)
            assert result is not None
            assert 0.0 <= result.composite <= 1.0
