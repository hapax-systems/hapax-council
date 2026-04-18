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

    def test_visible_false_does_not_mark_freshness_published(self):
        # Audit fix: a gated ward must not look "fresh" via the
        # freshness gauge. Otherwise a ward hidden for hours would
        # never trigger the staleness alarm and operators couldn't
        # distinguish "deliberately gated" from "stalled".
        source = _RecordingSource()
        wp.set_ward_properties("gated", wp.WardProperties(visible=False), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        runner = CairoSourceRunner(
            source_id="gated",
            source=source,
            canvas_w=4,
            canvas_h=4,
            target_fps=30.0,
            natural_w=4,
            natural_h=4,
        )
        # Patch the gauge so we can observe its calls.
        from unittest.mock import MagicMock

        runner._freshness_gauge = MagicMock()
        runner.tick_once()
        runner._freshness_gauge.mark_published.assert_not_called()
        runner._freshness_gauge.mark_failed.assert_not_called()

    def test_visible_default_marks_freshness_published(self):
        # Counterpart to the gated test: a normal render still publishes.
        source = _RecordingSource()
        runner = CairoSourceRunner(
            source_id="ungated",
            source=source,
            canvas_w=4,
            canvas_h=4,
            target_fps=30.0,
            natural_w=4,
            natural_h=4,
        )
        from unittest.mock import MagicMock

        runner._freshness_gauge = MagicMock()
        runner.tick_once()
        runner._freshness_gauge.mark_published.assert_called_once()

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

    def test_double_attenuation_when_source_also_calls_ward_render_scope(self):
        # If a Cairo source's render() also calls ward_render_scope on
        # the same ward_id, the alpha multiplies (alpha²). This test
        # actually exercises the bad pattern to lock in expected
        # behavior: with both runner-level and per-source wraps, a 0.5
        # alpha would attenuate to ~64 (0.25). Today's production sources
        # do NOT call ward_render_scope themselves (per-source wraps
        # were removed when the runner-level wrap was added); this test
        # is a guard-rail — if anyone re-introduces a per-source wrap,
        # this test will fail and warn them about the double-attenuation.

        class _DoubleWrappingSource(CairoSource):
            def render(
                self,
                cr: cairo.Context,
                canvas_w: int,
                canvas_h: int,
                t: float,
                state: dict[str, Any],
            ) -> None:
                with wp.ward_render_scope(cr, "double_wrapped") as inner_props:
                    if inner_props is None:
                        return
                    cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)
                    cr.rectangle(0, 0, canvas_w, canvas_h)
                    cr.fill()

        source = _DoubleWrappingSource()
        wp.set_ward_properties("double_wrapped", wp.WardProperties(alpha=0.5), ttl_s=10.0)
        wp.clear_ward_properties_cache()
        runner = CairoSourceRunner(
            source_id="double_wrapped",
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
        # Double attenuation: 0.5 × 0.5 = 0.25 → ~64. Single would be ~127.
        # Cairo rounding can vary; allow a small window around 64.
        assert 55 <= alpha <= 75, (
            f"expected ~64 alpha (double attenuation 0.25); got {alpha}. "
            f"If this test fails with ~127, the per-source wrap was removed "
            f"correctly and this guard-rail can be deleted."
        )
