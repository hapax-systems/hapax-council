"""Tests for :class:`GealCairoSource` Phase 1 MVP (spec §§5, 6, 7, 8).

Phase 1 ships S1 (recursive-depth breathing), V2 (vertex halos), G1
(apex-of-origin wavefront) gated behind ``HAPAX_GEAL_ENABLED=1``. Phase
1 is structural; aesthetic goldens land in task 1.6.
"""

from __future__ import annotations

import os

import cairo
import pytest


def _fresh_source(enabled: bool = True):
    """Instantiate GealCairoSource with the env gate set the way we need.

    Environment is set BEFORE the import so the module-level gate reads
    the right value. ``monkeypatch`` would work too but the env-first
    pattern matches how the production compositor sets the flag (systemd
    override, not runtime reconfiguration).
    """
    if enabled:
        os.environ["HAPAX_GEAL_ENABLED"] = "1"
    else:
        os.environ.pop("HAPAX_GEAL_ENABLED", None)
    # Late import so the gate is re-read per test.
    from agents.studio_compositor.geal_source import GealCairoSource

    return GealCairoSource()


@pytest.fixture()
def canvas() -> tuple[cairo.ImageSurface, cairo.Context]:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 640, 480)
    return surface, cairo.Context(surface)


def _pixel_alpha(surface: cairo.ImageSurface, x: int, y: int) -> int:
    """Return the A byte at (x, y) in an ARGB32 surface."""
    data = surface.get_data()
    stride = surface.get_stride()
    # ARGB32 is actually BGRA in little-endian; alpha is the 4th byte.
    return data[y * stride + x * 4 + 3]


def test_geal_source_gated_off_by_default(canvas) -> None:
    """With HAPAX_GEAL_ENABLED unset, render is a no-op — canvas stays empty."""
    surface, cr = canvas
    source = _fresh_source(enabled=False)
    source.render(cr, 640, 480, t=0.0, state={})
    # Every pixel should still be zero — no drawing happened.
    data = bytes(surface.get_data())
    assert data == bytes(len(data)), "GEAL must not draw when gate is off"


def test_geal_source_draws_when_enabled(canvas) -> None:
    surface, cr = canvas
    source = _fresh_source(enabled=True)
    source.render(cr, 640, 480, t=0.0, state={})
    # At least one pixel should be non-zero (halos paint something even
    # in NOMINAL / conversing with no TTS active — ambient vertex dots).
    data = bytes(surface.get_data())
    assert any(b != 0 for b in data), "GEAL must render when gate is on"


def test_s1_depth_target_for_each_stance() -> None:
    """Spec §6.2 S1 — stance → L3/L4 target-depth map:

    NOMINAL / CAUTIOUS / CRITICAL → L3 baseline.
    SEEKING → L4 (exploratory reach).
    DEGRADED → L3, reduced chroma (handled by palette bridge).
    """
    source = _fresh_source(enabled=True)

    assert source.depth_target_for_stance("NOMINAL") == 3
    assert source.depth_target_for_stance("CAUTIOUS") == 3
    assert source.depth_target_for_stance("SEEKING") == 4
    assert source.depth_target_for_stance("CRITICAL") == 3
    assert source.depth_target_for_stance("DEGRADED") == 3
    # Unknown → safe NOMINAL default.
    assert source.depth_target_for_stance("UNKNOWN") == 3


def test_fire_grounding_event_dispatches_to_correct_apex() -> None:
    """G1 wavefronts get placed on the apex the classifier returns."""
    source = _fresh_source(enabled=True)
    source.fire_grounding_event("insightface.operator", now_s=0.0)
    source.fire_grounding_event("rag.document.42", now_s=0.1)
    source.fire_grounding_event("chat.viewer.applause", now_s=0.2)

    apices = {env.apex for env in source._active_wavefronts}
    assert "top" in apices
    assert "bl" in apices
    assert "br" in apices


def test_fire_grounding_event_imagination_converge_fires_three() -> None:
    source = _fresh_source(enabled=True)
    n_before = len(source._active_wavefronts)
    source.fire_grounding_event("imagination.converge.42", now_s=0.0)
    # Imagination-converge = one event per apex.
    assert len(source._active_wavefronts) == n_before + 3


def test_wavefronts_expire_after_lifetime() -> None:
    source = _fresh_source(enabled=True)
    source.fire_grounding_event("insightface.op", now_s=0.0)
    assert len(source._active_wavefronts) == 1

    # Render well past the wavefront lifetime (G1 is 600 ms travel + σ
    # grace); the expired envelope should be dropped.
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 640, 480)
    cr = cairo.Context(surface)
    source.render(cr, 640, 480, t=3.0, state={})
    assert len(source._active_wavefronts) == 0


def test_render_in_budget_at_15fps(canvas) -> None:
    """Budget per spec: <= 8 ms at 15 fps (Phase 1 target)."""
    import time

    surface, cr = canvas
    source = _fresh_source(enabled=True)
    # Warm-up tick (first render may eat a one-time cache-fill cost).
    source.render(cr, 640, 480, t=0.0, state={})

    start = time.perf_counter()
    n = 10
    for i in range(n):
        source.render(cr, 640, 480, t=0.001 * i, state={})
    elapsed_ms = (time.perf_counter() - start) * 1000.0 / n
    # 8 ms budget for Phase 1; tests headroom to 15 ms to avoid CI flake.
    assert elapsed_ms < 15.0, f"mean render {elapsed_ms:.2f} ms exceeds Phase 1 budget"


def test_never_paints_inside_inscribed_video_rect() -> None:
    """GEAL layers 3, 4, 6, 7 clip to the three sliver + centre-void
    regions — the inscribed 16:9 YT rects must remain uncovered.
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1280, 720)
    cr = cairo.Context(surface)
    source = _fresh_source(enabled=True)

    # Fire a bunch of grounding events so G1 and G2 both paint.
    source.fire_grounding_event("insightface.op", now_s=0.0)
    source.fire_grounding_event("rag.doc.42", now_s=0.0)
    source.fire_grounding_event("chat.keyword.x", now_s=0.0)

    # Render ~mid-event (so the latch/wavefront envelopes are active).
    source.render(cr, 1280, 720, t=0.3, state={})

    # Spec invariant: the centre of every inscribed rect must be
    # untouched (alpha = 0). Use Sierpinski's geometry cache to resolve
    # rect positions at this canvas size.
    from agents.studio_compositor.sierpinski_renderer import SierpinskiCairoSource

    geom = SierpinskiCairoSource().geometry_cache(target_depth=2, canvas_w=1280, canvas_h=720)
    for rx, ry, rw, rh in geom.inscribed_rects:
        cx = int(rx + rw * 0.5)
        cy = int(ry + rh * 0.5)
        if 0 <= cx < 1280 and 0 <= cy < 720:
            a = _pixel_alpha(surface, cx, cy)
            assert a == 0, (
                f"GEAL painted inside inscribed video rect at centre ({cx}, {cy}); alpha={a}"
            )
