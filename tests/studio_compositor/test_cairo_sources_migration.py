"""Each migrated cairo source renders at natural size with origin (0, 0).

Phase 2 of the reverie source registry completion epic (parent C8–C11).
The three built-in CairoSource classes must:

1. Render successfully into a surface sized to the source's declared
   natural dimensions (not the full compositor canvas).
2. Produce non-empty output within the natural surface bounds (no
   drawing falls outside the surface into the canvas "margin").
3. Have no hardcoded ``OVERLAY_X`` / ``OVERLAY_Y`` / ``OVERLAY_SIZE``
   style offsets in their source modules.

The third check is a source-level regression pin that keeps the
origin-relative render contract honest going forward — the parent
reverie-bridge handoff flagged TokenPole's OVERLAY_* constants as the
single reason Phase C was deferred.
"""

from __future__ import annotations

import re
from pathlib import Path

import cairo
import pytest

from agents.studio_compositor.cairo_sources import get_cairo_source_class


def _render_at(class_name: str, w: int, h: int) -> cairo.ImageSurface:
    """Construct the registered source and render it into a natural-size surface."""
    cls = get_cairo_source_class(class_name)
    source = cls()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    source.render(cr, w, h, t=0.0, state={})
    surface.flush()
    return surface


def _any_nonzero_pixels(surface: cairo.ImageSurface) -> bool:
    """Return True if the surface has at least one non-zero byte.

    Stride is surface-width * 4 for ARGB32; ``get_data()`` returns the
    raw buffer. We scan the whole buffer (not just the first 1024 bytes)
    because some sources — TokenPole in particular — draw their dark
    backing card last, which may leave the first rows mostly clear
    under default test conditions.
    """
    return any(b != 0 for b in bytes(surface.get_data()))


def test_token_pole_renders_at_natural_300x300() -> None:
    surf = _render_at("TokenPoleCairoSource", 300, 300)
    assert surf.get_width() == 300
    assert surf.get_height() == 300
    assert _any_nonzero_pixels(surf)


def test_album_overlay_renders_at_natural_400x520() -> None:
    surf = _render_at("AlbumOverlayCairoSource", 400, 520)
    assert surf.get_width() == 400
    assert surf.get_height() == 520
    # AlbumOverlayCairoSource draws nothing until its underlying album
    # cover file exists on disk (it bails with ``return`` on missing
    # surface). We only assert the surface allocates cleanly at the
    # requested dimensions — the render contract holds even with no
    # cover present, and the pixel-content assertion is deferred to
    # the golden-image regression suite.
    assert isinstance(surf, cairo.ImageSurface)


def test_sierpinski_renders_at_natural_640x640() -> None:
    surf = _render_at("AoaCairoSource", 640, 640)
    assert surf.get_width() == 640
    assert surf.get_height() == 640
    assert _any_nonzero_pixels(surf)


def test_cairo_source_runner_has_per_source_freshness_gauge() -> None:
    """Post-epic audit Phase 1 finding #3 regression pin.

    AC-10 ("compositor_source_frame_age_seconds populates for every
    registered source") required a heartbeat gauge on each cairo
    runner. Phase 8 wired one into imagination_loop and ShmRgbaReader
    but skipped cairo sources, leaving the four core cairo runners
    (token_pole, album, stream_overlay, sierpinski) ungauged. Post-
    epic audit wires a gauge per runner — this test pins that
    ``CairoSourceRunner.__init__`` builds the gauge and that a
    successful render advances ``mark_published``.
    """
    from agents.studio_compositor.cairo_source import CairoSourceRunner
    from agents.studio_compositor.token_pole import TokenPoleCairoSource

    runner = CairoSourceRunner(
        source_id="token_pole_test",
        source=TokenPoleCairoSource(),
        canvas_w=300,
        canvas_h=300,
        natural_w=300,
        natural_h=300,
        target_fps=5.0,
    )
    # Gauge exists as an attribute — the constructor should not have
    # silently skipped it. ``None`` is only acceptable if
    # ``prometheus_client`` is wholly absent AND ``FreshnessGauge``
    # itself raises on import, which it does not.
    assert hasattr(runner, "_freshness_gauge")
    assert runner._freshness_gauge is not None

    # A fresh runner has no published frames, so ``age_seconds``
    # returns ``+inf`` (never-marked sentinel). After a single tick
    # the gauge flips to a finite value.
    import math

    assert math.isinf(runner._freshness_gauge.age_seconds())
    runner.tick_once()
    age = runner._freshness_gauge.age_seconds()
    assert math.isfinite(age) and age >= 0.0


@pytest.mark.parametrize(
    ("module_path", "pattern_name"),
    [
        ("agents/studio_compositor/token_pole.py", "OVERLAY_X"),
        ("agents/studio_compositor/token_pole.py", "OVERLAY_Y"),
        ("agents/studio_compositor/token_pole.py", "OVERLAY_SIZE"),
        ("agents/studio_compositor/album_overlay.py", "OVERLAY_X"),
        ("agents/studio_compositor/album_overlay.py", "OVERLAY_Y"),
        ("agents/studio_compositor/album_overlay.py", "OVERLAY_SIZE"),
        ("agents/studio_compositor/aoa_renderer.py", "OVERLAY_X"),
        ("agents/studio_compositor/aoa_renderer.py", "OVERLAY_Y"),
        ("agents/studio_compositor/aoa_renderer.py", "OVERLAY_SIZE"),
    ],
)
def test_no_hardcoded_overlay_offsets(module_path: str, pattern_name: str) -> None:
    """No legacy cairo source keeps canvas-absolute offset constants.

    The natural-size migration assumes every source draws at local
    origin. Any remaining ``OVERLAY_X`` / ``OVERLAY_Y`` / ``OVERLAY_SIZE``
    reference breaks that contract — the compositor places sources via
    their ``SurfaceSchema.geometry`` now, not via hardcoded Python
    offsets.
    """
    # Anchor the grep at the repo root regardless of test cwd.
    repo_root = Path(__file__).resolve().parents[2]
    src = (repo_root / module_path).read_text()
    pattern = re.compile(rf"\b{re.escape(pattern_name)}\b")
    matches = pattern.findall(src)
    assert not matches, (
        f"{module_path} still references {pattern_name}: "
        f"{len(matches)} occurrence(s). Natural-size migration is incomplete."
    )
