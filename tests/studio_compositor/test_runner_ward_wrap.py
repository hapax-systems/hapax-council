"""Tests for the runner-level ward modulation wrap in CairoSourceRunner.

The wrap means every Cairo source automatically honors per-ward
visibility + alpha — sources don't need per-source code changes.
"""

from __future__ import annotations

from typing import Any

import cairo  # noqa: TC002 — runtime use: ImageSurface in test bodies
import pytest

from agents.studio_compositor import ward_properties as wp
from agents.studio_compositor.cairo_source import CairoSource, CairoSourceRunner


@pytest.fixture(autouse=True)
def _redirect_path(monkeypatch, tmp_path):
    monkeypatch.setattr(wp, "WARD_PROPERTIES_PATH", tmp_path / "ward-properties.json")
    wp.clear_ward_properties_cache()
    yield
    wp.clear_ward_properties_cache()


class _RecordingSource(CairoSource):
    """Cairo source that records render calls + paints a solid red box."""

    def __init__(self) -> None:
        self.render_calls = 0

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        self.render_calls += 1
        # Paint a fully opaque red rectangle at the center pixel.
        cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()


def _read_pixel_alpha(surface: cairo.ImageSurface, x: int = 0, y: int = 0) -> int:
    """Sample the alpha byte of a single ARGB32 pixel."""
    data = bytes(surface.get_data())
    stride = surface.get_stride()
    # ARGB32 little-endian: bytes are B,G,R,A
    return data[y * stride + x * 4 + 3]


class TestRunnerWardWrap:
    def test_default_state_renders_normally(self):
        source = _RecordingSource()
        runner = CairoSourceRunner(
            source_id="recording",
            source=source,
            canvas_w=4,
            canvas_h=4,
            target_fps=30.0,
            natural_w=4,
            natural_h=4,
        )
        runner.tick_once()
        assert source.render_calls == 1
        surface = runner.get_output_surface()
        assert surface is not None
        assert _read_pixel_alpha(surface) == 255  # fully opaque red

    def test_visible_false_short_circuits_render(self):
        source = _RecordingSource()
        wp.set_ward_properties("hidden", wp.WardProperties(visible=False), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        runner = CairoSourceRunner(
            source_id="hidden",
            source=source,
            canvas_w=4,
            canvas_h=4,
            target_fps=30.0,
            natural_w=4,
            natural_h=4,
        )
        runner.tick_once()
        # Source render was skipped — render_calls stayed at 0.
        assert source.render_calls == 0
        surface = runner.get_output_surface()
        assert surface is not None
        # Surface is fully transparent (CLEAR was applied, source draw skipped)
        assert _read_pixel_alpha(surface) == 0

    def test_alpha_attenuates_output(self):
        source = _RecordingSource()
        wp.set_ward_properties("dimmed", wp.WardProperties(alpha=0.5), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        runner = CairoSourceRunner(
            source_id="dimmed",
            source=source,
            canvas_w=4,
            canvas_h=4,
            target_fps=30.0,
            natural_w=4,
            natural_h=4,
        )
        runner.tick_once()
        assert source.render_calls == 1
        surface = runner.get_output_surface()
        assert surface is not None
        # Alpha = round(255 * 0.5) = 127 or 128 (Cairo rounding may vary)
        alpha = _read_pixel_alpha(surface)
        assert 120 <= alpha <= 135, f"expected ~127 alpha, got {alpha}"

    def test_runner_does_not_double_attenuate_with_per_source_wrap(self):
        # If a per-source render() also called ward_render_scope, the
        # alpha would multiply (alpha²). Today the runner is the sole
        # site applying ward modulation to the whole-source surface; the
        # per-source overlay-zone wraps target a different ward_id
        # (overlay-zone:<id>) so they don't double up.
        # This test pins that per-CairoSource wraps are absent — Source
        # IDs that are NOT registered as overlay-zone:* should produce
        # alpha == 0.5 * 255, not 0.25 * 255.
        source = _RecordingSource()
        wp.set_ward_properties("single_layer", wp.WardProperties(alpha=0.5), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        runner = CairoSourceRunner(
            source_id="single_layer",
            source=source,
            canvas_w=4,
            canvas_h=4,
            target_fps=30.0,
            natural_w=4,
            natural_h=4,
        )
        runner.tick_once()
        surface = runner.get_output_surface()
        assert surface is not None
        alpha = _read_pixel_alpha(surface)
        # Single attenuation: ~127. Double would be ~64.
        assert alpha > 100, f"alpha {alpha} suggests double attenuation"
