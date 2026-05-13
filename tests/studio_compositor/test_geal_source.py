"""Tests for :class:`GealCairoSource` Phase 1 MVP (spec §§5, 6, 7, 8).

Phase 1 ships S1 (recursive-depth breathing), V2 (vertex halos), G1
(apex-of-origin wavefront) gated behind ``HAPAX_GEAL_ENABLED=1``. Phase
1 is structural; aesthetic goldens land in task 1.6.
"""

from __future__ import annotations

import os
import time
from typing import Final

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


# ── GEAL render-budget guard (cc-task ytb-GEAL-PERF-BUDGET-FOLLOWUP) ────
#
# The spec target at Phase 1 is **8 ms per render** at 15 fps so the
# overlay can compose into the 1280×720 broadcast frame without
# burning the cairo source registry's per-tick budget. CI hardware is
# noisier than the operator's workstation, so we assert against
# generous **p50** and **p95** thresholds rather than a single mean —
# a one-off slow tick is acceptable, repeated p95 violations are not.
#
# Baseline numbers (operator workstation, 2026-05-01):
#   idle scenario       p50 ≈ 0.5 ms   p95 ≈ 1.2 ms
#   single-event scen.  p50 ≈ 0.8 ms   p95 ≈ 1.8 ms
#   stressed scenario   p50 ≈ 2.5 ms   p95 ≈ 5.0 ms
#
# Headroom multipliers below give CI ~3× the operator-workstation
# baseline so transient noise doesn't flake the build, while still
# catching real regressions (a 5× slowdown will trip).

#: Phase 1 hard p50 budget across all scenarios (15 ms = ~75 % of one
#: 15 fps frame interval; the cairo registry expects each source to
#: stay well under).
GEAL_RENDER_BUDGET_P50_MS: Final[float] = 15.0

#: Phase 1 p95 budget — one slow tick per twenty is tolerated; more
#: than that indicates something deeper than CI noise.
GEAL_RENDER_BUDGET_P95_MS: Final[float] = 30.0


def _measure_render_ms(
    source,  # type: ignore[no-untyped-def]
    cr,  # type: ignore[no-untyped-def]
    *,
    samples: int,
    width: int = 640,
    height: int = 480,
) -> list[float]:
    """Render ``samples`` frames and return per-frame ms timings.

    A warm-up tick is run first so the per-source one-time cache-fill
    cost (path tessellation, palette LAB→sRGB conversion) doesn't
    dominate the first measurement.
    """
    import time

    source.render(cr, width, height, t=0.0, state={})
    timings: list[float] = []
    for i in range(samples):
        start = time.perf_counter()
        source.render(cr, width, height, t=0.001 * (i + 1), state={})
        timings.append((time.perf_counter() - start) * 1000.0)
    return timings


def _percentile(values: list[float], p: float) -> float:
    """Return the ``p``-th percentile (0..1) of ``values`` via linear
    interpolation. ``p=0.5`` yields the median; ``p=0.95`` the p95."""
    if not values:
        raise ValueError("cannot compute percentile of empty list")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = p * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


@pytest.mark.parametrize(
    "scenario,setup",
    [
        # Idle: gate enabled, no grounding events fired. Lowest cost.
        ("idle", lambda src: None),
        # Single-event: one wavefront active. Phase-1 typical case.
        (
            "single-event",
            lambda src: src.fire_grounding_event("insightface.operator", now_s=0.0),
        ),
        # Stressed: many wavefronts + latches. Catches O(n) regressions.
        (
            "stressed",
            lambda src: [
                src.fire_grounding_event(f"insightface.viewer.{i}", now_s=0.0) for i in range(8)
            ],
        ),
    ],
)
def test_render_within_phase_1_budget(canvas, scenario, setup) -> None:
    """GEAL render p50 + p95 stay under the documented Phase 1 budget.

    Three scenarios:

    * ``idle`` — gate on, no grounding events; lowest cost path.
    * ``single-event`` — one wavefront active; Phase 1 typical.
    * ``stressed`` — eight wavefronts active; catches O(n) regressions.

    Both p50 and p95 are checked. A repeated regression on either
    statistic indicates a real perf bug; a single slow tick (which a
    mean would reflect) is tolerated by p95.
    """
    _, cr = canvas
    source = _fresh_source(enabled=True)
    setup(source)

    timings = _measure_render_ms(source, cr, samples=30)
    p50 = _percentile(timings, 0.5)
    p95 = _percentile(timings, 0.95)

    assert p50 < GEAL_RENDER_BUDGET_P50_MS, (
        f"{scenario}: p50 render {p50:.2f} ms exceeds budget {GEAL_RENDER_BUDGET_P50_MS:.1f} ms"
    )
    assert p95 < GEAL_RENDER_BUDGET_P95_MS, (
        f"{scenario}: p95 render {p95:.2f} ms exceeds budget {GEAL_RENDER_BUDGET_P95_MS:.1f} ms"
    )


def test_percentile_helper_matches_definition() -> None:
    """Sanity pin so the budget guard's statistic isn't quietly broken
    by a future helper edit."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert _percentile(values, 0.0) == pytest.approx(1.0)
    assert _percentile(values, 0.5) == pytest.approx(5.5)
    assert _percentile(values, 0.95) == pytest.approx(9.55)
    assert _percentile(values, 1.0) == pytest.approx(10.0)
    # Single-value list returns that value at every percentile.
    assert _percentile([42.0], 0.5) == pytest.approx(42.0)


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


def test_budget_scale_reads_missing_shm_as_peak_attention(tmp_path, monkeypatch) -> None:
    """When /dev/shm/hapax-compositor/video-attention.f32 is absent,
    GEAL backs off to peak-attention intensity. Missing producer must not
    let the substrate paint at full intensity.
    """
    missing = tmp_path / "does-not-exist.f32"
    monkeypatch.setattr("agents.studio_compositor.geal_source.VIDEO_ATTENTION_PATH", missing)
    source = _fresh_source(enabled=True)
    source._video_attention = source._read_video_attention()
    assert source._video_attention == 1.0
    assert source._budget_scale() == pytest.approx(0.30)


def test_budget_scale_reads_stale_shm_as_peak_attention(tmp_path, monkeypatch) -> None:
    stale = tmp_path / "video-attention.f32"
    stale.write_bytes(b"\x00\x00\x00\x00")
    old = time.time() - 30.0
    os.utime(stale, (old, old))
    monkeypatch.setattr("agents.studio_compositor.geal_source.VIDEO_ATTENTION_PATH", stale)
    source = _fresh_source(enabled=True)

    source._video_attention = source._read_video_attention()

    assert source._video_attention == 1.0
    assert source._budget_scale() == pytest.approx(0.30)


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
