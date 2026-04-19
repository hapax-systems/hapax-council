"""Unit tests + golden-image regressions for ``emissive_base``.

Phase A1 of the homage-completion plan. Covers:

- ``paint_breathing_alpha`` bounds + phase symmetry
- ``paint_emissive_point`` geometry, drawing order, halo alpha falloff
- ``paint_emissive_glyph`` rendering (halo + text pass)
- ``paint_emissive_stroke`` glow + crisp-line composition
- ``paint_scanlines`` row cadence
- ``paint_emissive_bg`` flat-fill
- ``STANCE_HZ`` / ``stance_hz`` lookup
- Two golden-image regressions (``paint_emissive_point`` at t=0 and
  mid-shimmer ``paint_emissive_stroke``)

Golden PNGs live in ``golden_images/emissive_base/`` next to the other
studio-compositor goldens. Regenerate with ``HAPAX_UPDATE_GOLDEN=1``.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import pytest

from agents.studio_compositor.homage.emissive_base import (
    BREATHING_AMPLITUDE,
    BREATHING_BASELINE,
    CENTRE_DOT_RADIUS_PX,
    GRUVBOX_BG0,
    HALO_RADIUS_PX,
    OUTER_GLOW_RADIUS_PX,
    SHIMMER_HZ_DEFAULT,
    STANCE_HZ,
    paint_breathing_alpha,
    paint_emissive_bg,
    paint_emissive_glyph,
    paint_emissive_point,
    paint_emissive_stroke,
    paint_scanlines,
    stance_hz,
)


def _cairo_available() -> bool:
    try:
        import cairo  # noqa: F401
    except ImportError:
        return False
    return True


_HAS_CAIRO = _cairo_available()
requires_cairo = pytest.mark.skipif(not _HAS_CAIRO, reason="pycairo not installed")


_GOLDEN_DIR = Path(__file__).parent / "golden_images" / "emissive_base"
_GOLDEN_PIXEL_TOLERANCE = 4  # per channel (plan §A1 success criteria)


def _update_golden_requested() -> bool:
    return os.environ.get("HAPAX_UPDATE_GOLDEN", "").strip() not in ("", "0", "false")


def _make_surface(width: int, height: int) -> tuple[Any, Any]:
    """Return (surface, cr) ARGB32 with a painted dark ground."""
    import cairo

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    # Ground — mirror paint_emissive_bg so tests are self-contained.
    paint_emissive_bg(cr, width, height)
    return surface, cr


def _pixel_rgba(surface: Any, x: int, y: int) -> tuple[int, int, int, int]:
    """Sample a pixel as (R, G, B, A) in 0..255.

    Cairo ARGB32 is stored BGRA in little-endian. The stride can be
    larger than width*4 for alignment, so read via ``get_stride``.
    """
    data = bytes(surface.get_data())
    stride = surface.get_stride()
    offset = y * stride + x * 4
    b = data[offset]
    g = data[offset + 1]
    r = data[offset + 2]
    a = data[offset + 3]
    return r, g, b, a


def _surfaces_match(actual: Any, expected: Any, tolerance: int) -> tuple[bool, str]:
    if actual.get_width() != expected.get_width():
        return False, f"width {actual.get_width()} != {expected.get_width()}"
    if actual.get_height() != expected.get_height():
        return False, f"height {actual.get_height()} != {expected.get_height()}"
    a = bytes(actual.get_data())
    e = bytes(expected.get_data())
    if len(a) != len(e):
        return False, f"byte-len {len(a)} != {len(e)}"
    max_delta = 0
    n_over = 0
    for ab, eb in zip(a, e, strict=True):
        d = abs(ab - eb)
        if d > max_delta:
            max_delta = d
        if d > tolerance:
            n_over += 1
    if max_delta > tolerance:
        return False, f"max delta {max_delta} > tol {tolerance} ({n_over} bytes over)"
    return True, f"max delta {max_delta} within tol {tolerance}"


# ── Breathing / shimmer modulator ────────────────────────────────────────


class TestPaintBreathingAlpha:
    def test_midpoint_returns_baseline(self):
        # sin(0) == 0 ⇒ baseline exactly.
        assert paint_breathing_alpha(0.0, hz=1.0, phase=0.0) == pytest.approx(BREATHING_BASELINE)

    def test_peak_returns_baseline_plus_amplitude(self):
        # Quarter cycle at hz=1 is t=0.25 s ⇒ sin = 1.
        v = paint_breathing_alpha(0.25, hz=1.0, phase=0.0)
        assert v == pytest.approx(BREATHING_BASELINE + BREATHING_AMPLITUDE)

    def test_trough_returns_baseline_minus_amplitude(self):
        # Three-quarter cycle ⇒ sin = -1.
        v = paint_breathing_alpha(0.75, hz=1.0, phase=0.0)
        assert v == pytest.approx(BREATHING_BASELINE - BREATHING_AMPLITUDE)

    def test_phase_offset_is_equivalent_to_time_shift(self):
        # phase=pi/2 at t=0 should equal phase=0 at t=0.25 s (hz=1).
        a = paint_breathing_alpha(0.0, hz=1.0, phase=math.pi / 2.0)
        b = paint_breathing_alpha(0.25, hz=1.0, phase=0.0)
        assert a == pytest.approx(b)

    def test_clamped_to_zero_one(self):
        # Force an out-of-range amplitude.
        v_hi = paint_breathing_alpha(0.25, hz=1.0, baseline=0.9, amplitude=0.5)
        v_lo = paint_breathing_alpha(0.75, hz=1.0, baseline=0.1, amplitude=0.5)
        assert 0.0 <= v_hi <= 1.0
        assert 0.0 <= v_lo <= 1.0
        assert v_hi == pytest.approx(1.0)
        assert v_lo == pytest.approx(0.0)

    def test_different_frequencies_produce_different_values(self):
        a = paint_breathing_alpha(0.1, hz=0.5)
        b = paint_breathing_alpha(0.1, hz=2.0)
        assert a != pytest.approx(b)


# ── Stance table ────────────────────────────────────────────────────────


class TestStanceHz:
    def test_all_documented_stances_present(self):
        for name in ("nominal", "seeking", "cautious", "degraded", "critical"):
            assert name in STANCE_HZ
            assert STANCE_HZ[name] > 0.0

    def test_critical_is_fastest(self):
        assert STANCE_HZ["critical"] > STANCE_HZ["nominal"]
        assert STANCE_HZ["critical"] > STANCE_HZ["seeking"]

    def test_degraded_is_slowest(self):
        assert STANCE_HZ["degraded"] < STANCE_HZ["nominal"]
        assert STANCE_HZ["degraded"] < STANCE_HZ["cautious"]

    def test_unknown_stance_returns_fallback(self):
        assert stance_hz("nonsense") == pytest.approx(1.0)
        assert stance_hz("nonsense", fallback=3.3) == pytest.approx(3.3)

    def test_known_stance_lookup(self):
        assert stance_hz("seeking") == pytest.approx(STANCE_HZ["seeking"])


# ── Emissive background ─────────────────────────────────────────────────


@requires_cairo
class TestPaintEmissiveBg:
    def test_fills_entire_surface_with_ground_rgba(self):
        import cairo

        w, h = 8, 8
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        paint_emissive_bg(cr, w, h)
        surface.flush()
        r, g, b, a = _pixel_rgba(surface, 4, 4)
        # GRUVBOX_BG0 = (0x1D, 0x20, 0x21, 0xFF).
        assert r == 0x1D
        assert g == 0x20
        assert b == 0x21
        assert a == 0xFF

    def test_custom_ground_rgba(self):
        import cairo

        w, h = 4, 4
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        paint_emissive_bg(cr, w, h, ground_rgba=(1.0, 0.0, 0.0, 1.0))
        surface.flush()
        r, _g, _b, a = _pixel_rgba(surface, 1, 1)
        assert r == 0xFF
        assert a == 0xFF

    def test_restores_cairo_state(self):
        import cairo

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
        cr = cairo.Context(surface)
        cr.set_source_rgba(0.5, 0.5, 0.5, 1.0)
        paint_emissive_bg(cr, 4, 4)
        # If paint_emissive_bg leaked its source, the next set_source
        # call would be redundant. We can only verify state via the
        # observable effect of not polluting callers; reading the
        # current source back is not strictly portable in pycairo, so
        # we assert via a second draw call that still lands the
        # expected colour.
        cr.rectangle(0, 0, 1, 1)
        cr.fill()
        surface.flush()
        # Pixel (0,0) was set by bg then overwritten by caller's fill
        # using the caller's preserved (grey) source — should be grey.
        r, g, b, _a = _pixel_rgba(surface, 0, 0)
        assert 100 <= r <= 160
        assert 100 <= g <= 160
        assert 100 <= b <= 160


# ── Emissive point ──────────────────────────────────────────────────────


@requires_cairo
class TestPaintEmissivePoint:
    def test_centre_pixel_gets_full_signal_colour(self):
        w, h = 32, 32
        surface, cr = _make_surface(w, h)
        paint_emissive_point(
            cr,
            cx=16.0,
            cy=16.0,
            role_rgba=(1.0, 0.0, 0.0, 1.0),
            t=0.0,
            phase=0.0,
            baseline_alpha=1.0,
        )
        surface.flush()
        r, g, b, a = _pixel_rgba(surface, 16, 16)
        # Shimmer at t=0, phase=0 with sin=0 ⇒ baseline (0.85). Centre
        # dot alpha is 1.0 over bg (0x1D, 0x20, 0x21) with source alpha
        # 1.0 ⇒ the dot's colour fully replaces the ground.
        assert r >= 0xD0  # ≥0.85 * 255 ≈ 216
        assert g <= 0x20  # green stays dark (input green=0)
        assert b <= 0x21
        assert a == 0xFF

    def test_far_pixel_stays_at_bg(self):
        w, h = 64, 64
        surface, cr = _make_surface(w, h)
        paint_emissive_point(
            cr,
            cx=32.0,
            cy=32.0,
            role_rgba=(1.0, 1.0, 1.0, 1.0),
            t=0.0,
            baseline_alpha=1.0,
        )
        surface.flush()
        # Sample near the corner — well outside outer_glow_radius of 9.
        r, g, b, a = _pixel_rgba(surface, 2, 2)
        assert r == 0x1D
        assert g == 0x20
        assert b == 0x21
        assert a == 0xFF

    def test_baseline_alpha_zero_paints_nothing(self):
        w, h = 32, 32
        surface, cr = _make_surface(w, h)
        paint_emissive_point(
            cr,
            cx=16.0,
            cy=16.0,
            role_rgba=(1.0, 1.0, 1.0, 1.0),
            t=0.0,
            baseline_alpha=0.0,
        )
        surface.flush()
        r, g, b, _a = _pixel_rgba(surface, 16, 16)
        assert r == 0x1D
        assert g == 0x20
        assert b == 0x21

    def test_drawing_order_centre_over_halo(self):
        """At the centre pixel, the crisp dot must win over the halo.

        If drawing order were wrong (halo last), the centre pixel would
        receive a blend of ``cell_alpha * 0.45`` (mid-halo stop) instead
        of the full signal colour. Verified by comparing the centre
        intensity to an off-centre-but-inside-halo pixel.
        """
        w, h = 64, 64
        surface, cr = _make_surface(w, h)
        paint_emissive_point(
            cr,
            cx=32.0,
            cy=32.0,
            role_rgba=(1.0, 1.0, 1.0, 1.0),
            t=0.0,
            baseline_alpha=1.0,
        )
        surface.flush()
        centre_r, *_ = _pixel_rgba(surface, 32, 32)
        halo_r, *_ = _pixel_rgba(surface, 34, 34)
        # Centre should be brighter than the halo sample.
        assert centre_r > halo_r

    def test_zero_radii_does_not_crash(self):
        w, h = 16, 16
        surface, cr = _make_surface(w, h)
        # Should no-op on all three passes without error.
        paint_emissive_point(
            cr,
            cx=8.0,
            cy=8.0,
            role_rgba=(1.0, 1.0, 1.0, 1.0),
            t=0.0,
            centre_radius_px=0.0,
            halo_radius_px=0.0,
            outer_glow_radius_px=0.0,
        )
        surface.flush()
        r, g, b, _a = _pixel_rgba(surface, 8, 8)
        # Nothing drawn ⇒ still the bg.
        assert (r, g, b) == (0x1D, 0x20, 0x21)


# ── Emissive glyph ──────────────────────────────────────────────────────


@requires_cairo
class TestPaintEmissiveGlyph:
    def test_glyph_draws_some_ink(self):
        """A non-empty glyph must change pixels somewhere near (x,y).

        We don't pin specific bytes (font rasterisation is system-
        dependent) — we just verify ink is deposited within the
        glyph's expected footprint.
        """
        w, h = 64, 64
        surface, cr = _make_surface(w, h)
        paint_emissive_glyph(
            cr,
            x=16.0,
            y=40.0,
            glyph="*",
            font_size=16.0,
            role_rgba=(1.0, 1.0, 1.0, 1.0),
            t=0.0,
        )
        surface.flush()
        # Scan the glyph region for any non-bg pixel.
        found_ink = False
        for yy in range(20, 44):
            for xx in range(12, 36):
                r, g, b, _a = _pixel_rgba(surface, xx, yy)
                if (r, g, b) != (0x1D, 0x20, 0x21):
                    found_ink = True
                    break
            if found_ink:
                break
        assert found_ink, "glyph deposited no ink inside expected footprint"

    def test_zero_baseline_alpha_paints_nothing(self):
        w, h = 48, 48
        surface, cr = _make_surface(w, h)
        paint_emissive_glyph(
            cr,
            x=16.0,
            y=32.0,
            glyph="A",
            font_size=16.0,
            role_rgba=(1.0, 0.5, 0.2, 1.0),
            t=0.0,
            baseline_alpha=0.0,
        )
        surface.flush()
        # Every sampled pixel must still be bg.
        for yy in range(0, 48, 4):
            for xx in range(0, 48, 4):
                r, g, b, _a = _pixel_rgba(surface, xx, yy)
                assert (r, g, b) == (0x1D, 0x20, 0x21)


# ── Emissive stroke ────────────────────────────────────────────────────


@requires_cairo
class TestPaintEmissiveStroke:
    def test_stroke_paints_along_line(self):
        w, h = 64, 8
        surface, cr = _make_surface(w, h)
        paint_emissive_stroke(
            cr,
            x0=4.0,
            y0=4.0,
            x1=60.0,
            y1=4.0,
            role_rgba=(1.0, 1.0, 1.0, 1.0),
            t=0.0,
            width_px=2.0,
        )
        surface.flush()
        # Midpoint sample should be bright.
        r, _g, _b, _a = _pixel_rgba(surface, 32, 4)
        assert r > 0x80

    def test_horizontal_stroke_does_not_paint_far_from_line(self):
        w, h = 64, 64
        surface, cr = _make_surface(w, h)
        paint_emissive_stroke(
            cr,
            x0=4.0,
            y0=32.0,
            x1=60.0,
            y1=32.0,
            role_rgba=(1.0, 1.0, 1.0, 1.0),
            t=0.0,
            width_px=2.0,
            glow_width_mult=2.0,
        )
        surface.flush()
        # Top-edge pixel is far from y=32 ⇒ should be bg.
        r, g, b, _a = _pixel_rgba(surface, 32, 2)
        assert (r, g, b) == (0x1D, 0x20, 0x21)

    def test_zero_length_stroke_no_crash(self):
        w, h = 16, 16
        surface, cr = _make_surface(w, h)
        # Degenerate zero-length stroke — round cap paints a dot.
        paint_emissive_stroke(
            cr,
            x0=8.0,
            y0=8.0,
            x1=8.0,
            y1=8.0,
            role_rgba=(1.0, 1.0, 1.0, 1.0),
            t=0.0,
            width_px=1.0,
        )
        surface.flush()


# ── Scanlines ──────────────────────────────────────────────────────────


@requires_cairo
class TestPaintScanlines:
    def test_scanlines_at_expected_rows(self):
        """With default every_n_rows=4 and row_height=16, rows 0, 4, 8...
        are painted. A row-0 scanline sits at y≈8 (row centre)."""
        import cairo

        w, h = 64, 64
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        # Leave bg transparent so the scanline stands out.
        paint_scanlines(
            cr,
            w,
            h,
            role_rgba=(1.0, 1.0, 1.0, 1.0),
            every_n_rows=4,
            alpha=1.0,
            row_height_px=16.0,
        )
        surface.flush()
        # At y=8 (first scanline centre) we expect ink.
        _r, _g, _b, a_scan = _pixel_rgba(surface, 32, 8)
        # At y=20 (between row 1 and row 4's scanline) we expect bg.
        _r2, _g2, _b2, a_gap = _pixel_rgba(surface, 32, 20)
        assert a_scan > a_gap

    def test_alpha_zero_no_ink(self):
        import cairo

        w, h = 32, 32
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        paint_scanlines(cr, w, h, alpha=0.0, row_height_px=16.0)
        surface.flush()
        # Whole surface still fully transparent.
        for yy in range(0, h, 4):
            _r, _g, _b, a = _pixel_rgba(surface, 0, yy)
            assert a == 0


# ── Constants sanity ────────────────────────────────────────────────────


class TestConstants:
    def test_gruvbox_bg0_matches_palette_hex(self):
        expected = (0x1D / 255.0, 0x20 / 255.0, 0x21 / 255.0, 1.0)
        assert pytest.approx(expected) == GRUVBOX_BG0

    def test_radii_monotonic(self):
        assert CENTRE_DOT_RADIUS_PX < HALO_RADIUS_PX < OUTER_GLOW_RADIUS_PX

    def test_shimmer_hz_default_positive(self):
        assert SHIMMER_HZ_DEFAULT > 0.0


# ── Golden-image regressions ────────────────────────────────────────────


def _render_point_golden() -> Any:
    """Deterministic 48×48 render of a single emissive point at t=0."""
    import cairo

    w, h = 48, 48
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    paint_emissive_bg(cr, w, h)
    paint_emissive_point(
        cr,
        cx=24.0,
        cy=24.0,
        role_rgba=(0.52, 0.60, 0.00, 1.0),  # gruvbox accent-green-ish
        t=0.0,
        phase=0.0,
        baseline_alpha=1.0,
    )
    surface.flush()
    return surface


def _render_stroke_golden() -> Any:
    """Deterministic 96×24 render of an emissive stroke at mid-shimmer.

    ``t = 1 / (4 * SHIMMER_HZ_DEFAULT)`` corresponds to a quarter cycle
    so sin(2*pi*hz*t) = 1 ⇒ shimmer multiplier = baseline + amplitude.
    Pins the mid-peak state of the breathing pulse.
    """
    import cairo

    w, h = 96, 24
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    paint_emissive_bg(cr, w, h)
    t_mid = 1.0 / (4.0 * SHIMMER_HZ_DEFAULT)
    paint_emissive_stroke(
        cr,
        x0=6.0,
        y0=12.0,
        x1=90.0,
        y1=12.0,
        role_rgba=(0.51, 0.65, 0.74, 1.0),  # gruvbox accent-blue-ish
        t=t_mid,
        phase=0.0,
        baseline_alpha=1.0,
        width_px=2.0,
    )
    surface.flush()
    return surface


@requires_cairo
def test_emissive_point_golden() -> None:
    actual = _render_point_golden()
    path = _GOLDEN_DIR / "emissive_point_48x48.png"
    if _update_golden_requested():
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        actual.write_to_png(str(path))
        return
    assert path.is_file(), (
        f"golden image missing at {path} — set HAPAX_UPDATE_GOLDEN=1 "
        f"and re-run to generate, then audit and commit"
    )
    import cairo

    expected = cairo.ImageSurface.create_from_png(str(path))
    ok, diag = _surfaces_match(actual, expected, _GOLDEN_PIXEL_TOLERANCE)
    assert ok, diag


@requires_cairo
def test_emissive_stroke_golden_mid_shimmer() -> None:
    actual = _render_stroke_golden()
    path = _GOLDEN_DIR / "emissive_stroke_96x24_mid_shimmer.png"
    if _update_golden_requested():
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        actual.write_to_png(str(path))
        return
    assert path.is_file(), (
        f"golden image missing at {path} — set HAPAX_UPDATE_GOLDEN=1 "
        f"and re-run to generate, then audit and commit"
    )
    import cairo

    expected = cairo.ImageSurface.create_from_png(str(path))
    ok, diag = _surfaces_match(actual, expected, _GOLDEN_PIXEL_TOLERANCE)
    assert ok, diag


@requires_cairo
def test_emissive_point_golden_render_is_stable() -> None:
    """Sanity: two back-to-back deterministic renders are byte-identical."""
    a = _render_point_golden()
    b = _render_point_golden()
    assert bytes(a.get_data()) == bytes(b.get_data())
