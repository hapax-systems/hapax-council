"""Tests for the CairoSource protocol and CairoSourceRunner.

Phase 3b of the compositor unification epic — the polymorphic
mechanism that drives Python Cairo content sources on background
threads.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import cairo
import pytest

from agents.studio_compositor.cairo_source import CairoSource, CairoSourceRunner


class _RecordingSource(CairoSource):
    """Test source that records render calls and counts ticks."""

    def __init__(self) -> None:
        self.calls = 0
        self.canvas_sizes: list[tuple[int, int]] = []
        self.times: list[float] = []
        self.state_seen: list[dict[str, Any]] = []
        self.cleanup_called = False
        self._next_state: dict[str, Any] = {}

    def set_state(self, value: dict[str, Any]) -> None:
        self._next_state = value

    def state(self) -> dict[str, Any]:
        return dict(self._next_state)

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        self.calls += 1
        self.canvas_sizes.append((canvas_w, canvas_h))
        self.times.append(t)
        self.state_seen.append(dict(state))
        # Draw something so the surface is non-empty
        cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)
        cr.rectangle(0, 0, canvas_w, canvas_h)
        cr.fill()

    def cleanup(self) -> None:
        self.cleanup_called = True


class _ExplodingSource(CairoSource):
    def __init__(self) -> None:
        self.calls = 0

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        self.calls += 1
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# CairoSourceRunner basics
# ---------------------------------------------------------------------------


def test_runner_validates_target_fps():
    src = _RecordingSource()
    with pytest.raises(ValueError):
        CairoSourceRunner(source_id="bad", source=src, target_fps=0.0)


def test_runner_tick_once_calls_render():
    src = _RecordingSource()
    runner = CairoSourceRunner(source_id="t", source=src, canvas_w=64, canvas_h=32, target_fps=10)
    runner.tick_once()
    assert src.calls == 1
    assert src.canvas_sizes == [(64, 32)]


def test_runner_caches_output_surface():
    src = _RecordingSource()
    runner = CairoSourceRunner(source_id="t", source=src, canvas_w=64, canvas_h=32, target_fps=10)
    assert runner.get_output_surface() is None
    runner.tick_once()
    surface = runner.get_output_surface()
    assert surface is not None
    assert surface.get_width() == 64
    assert surface.get_height() == 32


def test_runner_passes_state_to_render():
    src = _RecordingSource()
    src.set_state({"slot": 2, "energy": 0.7})
    runner = CairoSourceRunner(source_id="t", source=src, canvas_w=16, canvas_h=16, target_fps=10)
    runner.tick_once()
    assert src.state_seen[-1] == {"slot": 2, "energy": 0.7}


def test_runner_render_exception_does_not_corrupt_state():
    src = _ExplodingSource()
    runner = CairoSourceRunner(source_id="boom", source=src, canvas_w=8, canvas_h=8, target_fps=10)
    # Exception is swallowed and logged.
    runner.tick_once()
    assert src.calls == 1
    # No surface should be cached after a failed render.
    assert runner.get_output_surface() is None


def test_runner_set_canvas_size_picked_up_on_next_tick():
    src = _RecordingSource()
    runner = CairoSourceRunner(source_id="t", source=src, canvas_w=64, canvas_h=32, target_fps=10)
    runner.tick_once()
    runner.set_canvas_size(128, 64)
    runner.tick_once()
    assert src.canvas_sizes[-1] == (128, 64)
    surface = runner.get_output_surface()
    assert surface is not None
    assert surface.get_width() == 128
    assert surface.get_height() == 64


def test_runner_frame_count_and_render_ms():
    src = _RecordingSource()
    runner = CairoSourceRunner(source_id="t", source=src, canvas_w=8, canvas_h=8, target_fps=10)
    assert runner.frame_count == 0
    runner.tick_once()
    runner.tick_once()
    assert runner.frame_count == 2
    assert runner.last_render_ms >= 0.0


# ---------------------------------------------------------------------------
# Threaded loop
# ---------------------------------------------------------------------------


def test_runner_background_thread_renders_and_stops():
    src = _RecordingSource()
    runner = CairoSourceRunner(
        source_id="bg",
        source=src,
        canvas_w=8,
        canvas_h=8,
        target_fps=200.0,
    )
    runner.start()
    # Allow several ticks at 200fps (5ms period).
    time.sleep(0.06)
    runner.stop(timeout=1.0)
    # Expect at least 2 renders in 60ms at the target rate.
    assert src.calls >= 2
    assert src.cleanup_called is True
    # Output surface is populated.
    assert runner.get_output_surface() is not None


def test_runner_start_is_idempotent():
    src = _RecordingSource()
    runner = CairoSourceRunner(source_id="idem", source=src, canvas_w=8, canvas_h=8, target_fps=100)
    runner.start()
    # Calling start again must not spawn a second thread.
    runner.start()
    runner.stop(timeout=1.0)
    # If a second thread had started we'd see double the renders, but the
    # main correctness check is that stop() returns cleanly.
    assert src.cleanup_called is True


def test_runner_get_output_surface_is_thread_safe():
    """Concurrent reads from get_output_surface() must not raise."""
    src = _RecordingSource()
    runner = CairoSourceRunner(
        source_id="concurrent",
        source=src,
        canvas_w=16,
        canvas_h=16,
        target_fps=200.0,
    )
    runner.start()
    errors: list[BaseException] = []
    stop = threading.Event()

    def reader() -> None:
        try:
            while not stop.is_set():
                _ = runner.get_output_surface()
        except BaseException as exc:  # pragma: no cover - failure path only
            errors.append(exc)

    readers = [threading.Thread(target=reader) for _ in range(3)]
    for r in readers:
        r.start()
    time.sleep(0.05)
    stop.set()
    for r in readers:
        r.join(timeout=1.0)
    runner.stop(timeout=1.0)
    assert not errors


# ---------------------------------------------------------------------------
# Sierpinski integration — facade still works after the refactor
# ---------------------------------------------------------------------------


def test_sierpinski_renderer_facade_renders_via_runner():
    """Phase 3b: SierpinskiRenderer is a thin facade over CairoSourceRunner.

    The public API (start/stop/draw/set_active_slot/set_audio_energy) must
    still work and the runner should produce a non-empty output surface.
    """
    from agents.studio_compositor.sierpinski_renderer import SierpinskiRenderer

    renderer = SierpinskiRenderer()
    # set_*() should not crash on a fresh renderer.
    renderer.set_active_slot(1)
    renderer.set_audio_energy(0.5)
    # Tick the runner directly so we don't wait on the background thread.
    renderer._runner.tick_once()  # noqa: SLF001 — test boundary

    # The cached surface is now populated. Dimensions come from
    # config.OUTPUT_WIDTH/HEIGHT (A+ Stage 2 B2 fix: 2026-04-17) —
    # Sierpinski was hardcoded to 1920x1080 which wasted pixels at
    # 720p canvas. Test against the config so it survives further
    # canvas resizing.
    from agents.studio_compositor.config import OUTPUT_HEIGHT, OUTPUT_WIDTH

    out = renderer._runner.get_output_surface()  # noqa: SLF001
    assert out is not None
    assert out.get_width() == OUTPUT_WIDTH
    assert out.get_height() == OUTPUT_HEIGHT


def test_sierpinski_renderer_draw_blits_cached_surface():
    """SierpinskiRenderer.draw() must blit the runner's cached surface
    onto the caller's Cairo context (the GStreamer streaming-thread path).
    """
    from agents.studio_compositor.sierpinski_renderer import SierpinskiRenderer

    renderer = SierpinskiRenderer()
    renderer._runner.tick_once()  # noqa: SLF001 — populate cache

    target = cairo.ImageSurface(cairo.FORMAT_ARGB32, 320, 180)
    cr = cairo.Context(target)
    # Should not raise; the call updates the canvas size and blits.
    renderer.draw(cr, 320, 180)


def test_sierpinski_cairo_source_render_into_small_canvas():
    """Direct render into a small ImageSurface — sanity-check the source
    is decoupled from the facade and works standalone.
    """
    from agents.studio_compositor.sierpinski_renderer import SierpinskiCairoSource

    source = SierpinskiCairoSource()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 256, 144)
    cr = cairo.Context(surface)
    source.render(cr, 256, 144, t=0.0, state={})
    surface.flush()
    # Surface bytes should contain non-zero pixels (we drew triangle lines).
    data = bytes(surface.get_data())
    assert any(b != 0 for b in data)


def test_sierpinski_audio_energy_smoothed_lags_raw():
    """The line-width envelope has fast attack and slower release.

    That restores visible transient lift without reintroducing hard
    frame-to-frame snapback. Raw energy is still preserved for the waveform.
    """
    from agents.studio_compositor.sierpinski_renderer import SierpinskiCairoSource

    source = SierpinskiCairoSource()
    assert source._audio_energy == 0.0
    assert source._audio_energy_smoothed == 0.0

    # First impulse at full level: smoothed lags raw.
    source.set_audio_energy(1.0)
    assert source._audio_energy == 1.0
    assert source._audio_energy_smoothed == pytest.approx(0.45)

    # Second tick at full level continues to converge upward.
    source.set_audio_energy(1.0)
    assert source._audio_energy_smoothed == pytest.approx(0.6975)

    # Sudden drop to zero: raw goes to 0 immediately, smoothed releases
    # more slowly than it attacked.
    source.set_audio_energy(0.0)
    assert source._audio_energy == 0.0
    assert source._audio_energy_smoothed == pytest.approx(0.54405)


# ---------------------------------------------------------------------------
# Phase 3b-final: AlbumOverlay / OverlayZones / TokenPole facades
# ---------------------------------------------------------------------------


def test_album_overlay_cairo_source_render_does_not_raise_without_cover():
    """Cover file may be absent; render should be a safe no-op that still
    exits cleanly so the runner's output surface is populated with a
    transparent image (no crash).
    """
    from agents.studio_compositor.album_overlay import (
        CANVAS_H,
        CANVAS_W,
        AlbumOverlayCairoSource,
    )

    source = AlbumOverlayCairoSource()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CANVAS_W, CANVAS_H)
    cr = cairo.Context(surface)
    # No /dev/shm/hapax-compositor/album-cover.png → self._surface stays None
    # and render returns early without drawing.
    source.render(cr, CANVAS_W, CANVAS_H, t=0.0, state={})
    surface.flush()  # must not raise


# ``test_album_overlay_facade_draw_blits_cached_surface`` was removed in
# Phase 9 Task 29 alongside the ``AlbumOverlay`` facade class. The
# natural-size rendering path is covered by the SourceRegistry +
# ``pip_draw_from_layout`` integration tests in
# ``tests/studio_compositor/test_compositor_wiring.py``.


def test_overlay_zones_cairo_source_render_into_empty_canvas():
    """Zones source renders into a small canvas without crashing, even
    when the per-zone file/folder sources are missing.
    """
    from agents.studio_compositor.overlay_zones import OverlayZonesCairoSource

    source = OverlayZonesCairoSource()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 640, 360)
    cr = cairo.Context(surface)
    source.render(cr, 640, 360, t=0.0, state={})
    surface.flush()  # must not raise
    # Default configs yield four zones: main + research + lyrics +
    # right_marker. ``research`` (LRR Phase 8 §12) gates on the active
    # objective; ``right_marker`` fills the right column when the
    # lyrics file is empty.
    assert len(source.zones) == 4


def test_overlay_zone_manager_facade_render_is_a_noop_when_surface_missing():
    """Facade render(cr, w, h) must tolerate the runner having no surface
    cached yet (initial frame before the background thread ticks).
    """
    from agents.studio_compositor.overlay_zones import OverlayZoneManager

    manager = OverlayZoneManager()
    try:
        target = cairo.ImageSurface(cairo.FORMAT_ARGB32, 640, 360)
        cr = cairo.Context(target)
        # Do not pre-tick — runner surface may still be None on first frame.
        manager.render(cr, 640, 360)  # must not raise
    finally:
        manager.stop()


def test_token_pole_cairo_source_render_advances_animation_state():
    """TokenPoleCairoSource.render() must call _tick_state on every frame
    so the pulse phase and position-easing actually progress at the
    runner's cadence.
    """
    from agents.studio_compositor.token_pole import TokenPoleCairoSource

    source = TokenPoleCairoSource()
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 1080)
    cr = cairo.Context(surface)
    for _ in range(5):
        source.render(cr, 1920, 1080, t=0.0, state={})
    # Pulse advances by 0.1 per tick (see TokenPoleCairoSource._tick_state).
    assert source._pulse == pytest.approx(0.5)  # noqa: SLF001 — test boundary


# ``test_token_pole_facade_draw_does_not_raise`` was removed in Phase 9
# Task 29 alongside the ``TokenPole`` facade class.


# ---------------------------------------------------------------------------
# Regression — livestream-performance-map Sprint 2 F5
# ---------------------------------------------------------------------------


def test_runner_freshness_gauge_built_for_hyphenated_source_id():
    """Construction MUST succeed for a source_id containing hyphens.

    Beta's Sprint 2 F5 finding: ``overlay-zones`` and ``sierpinski-lines``
    (both hardcoded in their respective renderer modules) fail the
    ``FreshnessGauge`` regex ``[a-z_][a-z0-9_]*`` at metric-name
    construction time, raising ``ValueError`` that is caught by the
    runner's outer ``except`` and silently leaves
    ``self._freshness_gauge = None``. The compositor's
    ``compositor_source_frame_{source_id}_age_seconds`` metric never
    appears on ``:9482`` for those sources, and stale / dead renders
    cannot be detected.

    Fix: substitute ``-`` with ``_`` in the metric suffix so the
    Prometheus name constraint is satisfied. This test pins the fix
    by asserting the gauge is live after construction with a
    hyphenated id.
    """
    # Force a reload of ``shared.freshness_gauge`` against a fresh
    # CollectorRegistry so this test does not race with any other test
    # that already registered a gauge under the same name.
    src = _RecordingSource()
    runner = CairoSourceRunner(
        source_id="overlay-zones",
        source=src,
        canvas_w=64,
        canvas_h=64,
        target_fps=10,
    )
    assert runner._freshness_gauge is not None, (  # noqa: SLF001 — test boundary
        "FreshnessGauge must be built successfully even when the "
        "source_id contains hyphens; the bug at cairo_source.py:167 "
        "previously caught the ValueError and left the gauge as None"
    )
    # And the public name on the gauge should contain the sanitized
    # metric suffix — with underscore, not hyphen.
    assert runner._freshness_gauge.name == "compositor_source_frame_overlay_zones"  # noqa: SLF001

    # Also verify the publish + fail counter paths still work after
    # construction (no ``AttributeError`` from a dangling None).
    runner.tick_once()
    assert runner._freshness_gauge.published_count >= 1  # noqa: SLF001
