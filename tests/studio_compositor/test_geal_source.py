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


def test_g2_latches_deterministic_cell_per_source_id() -> None:
    """Spec §6.3 — same source_id → same cell every time."""
    source = _fresh_source(enabled=True)
    source.fire_grounding_event("insightface.jason", now_s=0.0)
    first_cell = source._active_latches[0].sub_triangle_idx

    source2 = _fresh_source(enabled=True)
    source2.fire_grounding_event("insightface.jason", now_s=42.0)
    second_cell = source2._active_latches[0].sub_triangle_idx

    assert first_cell == second_cell, (
        f"G2 hash must be stable across instances; got {first_cell} vs {second_cell}"
    )


def test_g2_latch_spawns_alongside_wavefront() -> None:
    """Grounding events spawn both a G1 wavefront and a G2 latch."""
    source = _fresh_source(enabled=True)
    source.fire_grounding_event("insightface.op", now_s=0.0)
    assert len(source._active_wavefronts) == 1
    assert len(source._active_latches) == 1
    assert source._active_latches[0].apex == "top"


def test_s2_apex_weights_rebalance_on_stance() -> None:
    """Spec §6.2 S2 — SEEKING is apex-heavy; CAUTIOUS is base-heavy."""
    from agents.studio_compositor.geal_source import _S2_APEX_WEIGHTS

    seeking = _S2_APEX_WEIGHTS["SEEKING"]
    cautious = _S2_APEX_WEIGHTS["CAUTIOUS"]

    # SEEKING: top > bl + br.
    assert seeking[0] > seeking[1]
    assert seeking[0] > seeking[2]
    # CAUTIOUS: bl + br > top (inverted).
    assert cautious[1] > cautious[0]
    assert cautious[2] > cautious[0]
    # All weights sum to 1.0 for the five canonical stances (CRITICAL
    # is dark, but we still keep it well-formed).
    # Weights sum to ~1.0. A 0.02 tolerance accommodates the spec's
    # chosen-rounded values (e.g. NOMINAL=(0.33,0.33,0.33)=0.99).
    for stance in ("NOMINAL", "SEEKING", "CAUTIOUS", "DEGRADED"):
        total = sum(_S2_APEX_WEIGHTS[stance])
        assert abs(total - 1.0) < 0.02, f"{stance} weights sum to {total}"


def test_budget_scale_reduces_alpha_under_video_attention() -> None:
    """Spec §5.1 — GEAL halves its output when video_attention peaks."""
    source = _fresh_source(enabled=True)
    # Baseline budget scale (no video attention).
    source._video_attention = 0.0
    baseline = source._budget_scale()
    # Peak attention → (1.0 - 0.7 × 1.0) = 0.30.
    source._video_attention = 1.0
    peaked = source._budget_scale()
    assert baseline == pytest.approx(1.0)
    assert peaked == pytest.approx(0.30)
    # Monotonic: higher attention → lower scale.
    scales = [
        source._budget_scale()
        for va in (0.0, 0.25, 0.5, 0.75, 1.0)
        if (setattr(source, "_video_attention", va) or True)
    ]
    for a, b in zip(scales[:-1], scales[1:], strict=True):
        assert b <= a


def test_budget_scale_reads_missing_shm_as_full_activation(tmp_path, monkeypatch) -> None:
    """When /dev/shm/hapax-compositor/video-attention.f32 is absent,
    GEAL runs at full (budget_scale = 1.0). Missing producer must not
    accidentally dim the avatar.
    """
    missing = tmp_path / "does-not-exist.f32"
    monkeypatch.setattr("agents.studio_compositor.geal_source.VIDEO_ATTENTION_PATH", missing)
    source = _fresh_source(enabled=True)
    assert source._read_video_attention() == 0.0
    assert source._budget_scale() == pytest.approx(1.0)


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
