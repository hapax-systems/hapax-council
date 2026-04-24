"""Tests for the palette curve evaluator (Phase 3b)."""

from __future__ import annotations

import math

import pytest

from shared.palette_curve_evaluator import (
    CurveParamError,
    apply_palette,
    evaluate,
    lab_to_rgb,
    rgb_to_lab,
)
from shared.palette_family import PaletteResponseCurve, ScrimPalette
from shared.palette_registry import PaletteRegistry

# ---------------------------------------------------------------------------
# Colour conversion
# ---------------------------------------------------------------------------


class TestColourConversion:
    """sRGB ↔ LAB reference round-trips against known-good values."""

    def test_white_srgb_is_lab_100(self):
        L, a, b = rgb_to_lab(1.0, 1.0, 1.0)
        assert math.isclose(L, 100.0, abs_tol=0.1)
        assert math.isclose(a, 0.0, abs_tol=0.2)
        assert math.isclose(b, 0.0, abs_tol=0.2)

    def test_black_srgb_is_lab_0(self):
        L, a, b = rgb_to_lab(0.0, 0.0, 0.0)
        assert math.isclose(L, 0.0, abs_tol=0.1)
        assert math.isclose(a, 0.0, abs_tol=0.2)
        assert math.isclose(b, 0.0, abs_tol=0.2)

    def test_neutral_gray_has_zero_chroma(self):
        L, a, b = rgb_to_lab(0.5, 0.5, 0.5)
        assert math.isclose(a, 0.0, abs_tol=0.2)
        assert math.isclose(b, 0.0, abs_tol=0.2)
        # L* for sRGB 0.5 gray is ~53.4
        assert 50.0 < L < 56.0

    def test_round_trip_preserves_colour(self):
        cases = [
            (0.9, 0.2, 0.1),
            (0.25, 0.6, 0.85),
            (0.5, 0.5, 0.5),
            (0.1, 0.1, 0.1),
            (0.8, 0.8, 0.2),
        ]
        for r, g, b in cases:
            lab = rgb_to_lab(r, g, b)
            r2, g2, b2 = lab_to_rgb(*lab)
            assert math.isclose(r, r2, abs_tol=0.002), f"r differs for {(r, g, b)}"
            assert math.isclose(g, g2, abs_tol=0.002), f"g differs for {(r, g, b)}"
            assert math.isclose(b, b2, abs_tol=0.002), f"b differs for {(r, g, b)}"

    def test_lab_to_rgb_clamps_out_of_gamut(self):
        # Absurd chroma — should clamp, not raise.
        r, g, b = lab_to_rgb(50.0, 200.0, 200.0)
        for v in (r, g, b):
            assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# Per-mode evaluation
# ---------------------------------------------------------------------------


class TestIdentityMode:
    def test_identity_returns_input(self):
        curve = PaletteResponseCurve(mode="identity")
        assert evaluate(curve, (50.0, 10.0, -5.0)) == (50.0, 10.0, -5.0)


class TestLabShiftMode:
    def test_lab_shift_adds_deltas(self):
        curve = PaletteResponseCurve(
            mode="lab_shift",
            params={"delta_l": 5.0, "delta_a": -3.0, "delta_b": 10.0},
        )
        out = evaluate(curve, (50.0, 2.0, 1.0))
        assert out == (55.0, -1.0, 11.0)

    def test_lab_shift_missing_params_defaults_to_zero(self):
        curve = PaletteResponseCurve(mode="lab_shift")
        out = evaluate(curve, (50.0, 2.0, 1.0))
        assert out == (50.0, 2.0, 1.0)


class TestDuotoneMode:
    def test_duotone_explicit_stops(self):
        curve = PaletteResponseCurve(
            mode="duotone",
            params={"stop_low": [20.0, 10.0, 5.0], "stop_high": [80.0, -5.0, 20.0]},
        )
        # L*/100 = 0.5 → midpoint
        out = evaluate(curve, (50.0, 0.0, 0.0))
        assert math.isclose(out[0], 50.0, abs_tol=0.01)
        assert math.isclose(out[1], 2.5, abs_tol=0.01)
        assert math.isclose(out[2], 12.5, abs_tol=0.01)

    def test_duotone_extremes(self):
        curve = PaletteResponseCurve(
            mode="duotone",
            params={"stop_low": [0.0, 0.0, 0.0], "stop_high": [100.0, 0.0, 0.0]},
        )
        assert evaluate(curve, (0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0)
        assert evaluate(curve, (100.0, 0.0, 0.0)) == (100.0, 0.0, 0.0)

    def test_duotone_falls_back_to_palette_anchors(self):
        palette = ScrimPalette(
            id="p",
            display_name="P",
            dominant_lab=(80.0, 10.0, 20.0),
            accent_lab=(20.0, 5.0, 10.0),
        )
        curve = PaletteResponseCurve(mode="duotone")
        # With no explicit stops, uses accent as low and dominant as high.
        out = evaluate(curve, (50.0, 0.0, 0.0), palette=palette)
        assert math.isclose(out[0], 50.0, abs_tol=0.01)

    def test_duotone_no_stops_no_palette_raises(self):
        curve = PaletteResponseCurve(mode="duotone")
        with pytest.raises(CurveParamError, match="stop_low"):
            evaluate(curve, (50.0, 0.0, 0.0))


class TestGradientMapMode:
    def test_gradient_map_basic(self):
        curve = PaletteResponseCurve(
            mode="gradient_map",
            params={
                "stops": [
                    {"t": 0.0, "lab": [0.0, 0.0, 0.0]},
                    {"t": 1.0, "lab": [100.0, 0.0, 0.0]},
                ]
            },
        )
        # L*/100 = 0.25 → interpolate between stops
        out = evaluate(curve, (25.0, 5.0, 5.0))
        assert math.isclose(out[0], 25.0, abs_tol=0.01)

    def test_gradient_map_multi_stop(self):
        curve = PaletteResponseCurve(
            mode="gradient_map",
            params={
                "stops": [
                    {"t": 0.0, "lab": [10.0, 0.0, 0.0]},
                    {"t": 0.5, "lab": [50.0, 30.0, 0.0]},
                    {"t": 1.0, "lab": [90.0, 0.0, 0.0]},
                ]
            },
        )
        # At L*=25 (t=0.25), midway between stops[0] and stops[1]
        out = evaluate(curve, (25.0, 0.0, 0.0))
        assert math.isclose(out[0], 30.0, abs_tol=0.01)  # (10 + 50) / 2
        assert math.isclose(out[1], 15.0, abs_tol=0.01)  # (0 + 30) / 2

    def test_gradient_map_clamps_below_first_stop(self):
        curve = PaletteResponseCurve(
            mode="gradient_map",
            params={
                "stops": [
                    {"t": 0.2, "lab": [20.0, 0.0, 0.0]},
                    {"t": 0.8, "lab": [80.0, 0.0, 0.0]},
                ]
            },
        )
        # L*/100 = 0.05 → below first stop, clamped
        out = evaluate(curve, (5.0, 0.0, 0.0))
        assert out == (20.0, 0.0, 0.0)

    def test_gradient_map_too_few_stops_raises(self):
        curve = PaletteResponseCurve(
            mode="gradient_map",
            params={"stops": [{"t": 0.0, "lab": [0.0, 0.0, 0.0]}]},
        )
        with pytest.raises(CurveParamError, match="at least 2"):
            evaluate(curve, (50.0, 0.0, 0.0))

    def test_gradient_map_malformed_stop_raises(self):
        curve = PaletteResponseCurve(
            mode="gradient_map",
            params={"stops": [{"t": 0.0}, {"t": 1.0, "lab": [100.0, 0.0, 0.0]}]},
        )
        with pytest.raises(CurveParamError, match="stops\\[0\\]"):
            evaluate(curve, (50.0, 0.0, 0.0))


class TestHueRotateMode:
    def test_hue_rotate_preserves_chroma_and_luminance(self):
        curve = PaletteResponseCurve(mode="hue_rotate", params={"degrees": 90.0})
        input_lab = (50.0, 20.0, 0.0)  # chroma along +a axis
        out = evaluate(curve, input_lab)
        assert math.isclose(out[0], 50.0, abs_tol=0.01)
        # +90° rotation: a=20, b=0 → a=0, b=20
        assert math.isclose(out[1], 0.0, abs_tol=0.01)
        assert math.isclose(out[2], 20.0, abs_tol=0.01)

    def test_hue_rotate_zero_degrees_is_identity(self):
        curve = PaletteResponseCurve(mode="hue_rotate", params={"degrees": 0.0})
        out = evaluate(curve, (40.0, 15.0, -10.0))
        assert math.isclose(out[0], 40.0, abs_tol=0.01)
        assert math.isclose(out[1], 15.0, abs_tol=0.01)
        assert math.isclose(out[2], -10.0, abs_tol=0.01)

    def test_hue_rotate_on_zero_chroma_is_noop(self):
        curve = PaletteResponseCurve(mode="hue_rotate", params={"degrees": 45.0})
        out = evaluate(curve, (50.0, 0.0, 0.0))
        assert math.isclose(out[1], 0.0, abs_tol=0.01)
        assert math.isclose(out[2], 0.0, abs_tol=0.01)


class TestChannelMixMode:
    def test_channel_mix_identity_matrix(self):
        curve = PaletteResponseCurve(
            mode="channel_mix",
            params={
                "rr": 1.0,
                "rg": 0.0,
                "rb": 0.0,
                "gr": 0.0,
                "gg": 1.0,
                "gb": 0.0,
                "br": 0.0,
                "bg": 0.0,
                "bb": 1.0,
            },
        )
        input_lab = rgb_to_lab(0.5, 0.3, 0.7)
        out = evaluate(curve, input_lab)
        # Identity matrix: round-trip through RGB should preserve LAB within float tolerance.
        for i in range(3):
            assert math.isclose(out[i], input_lab[i], abs_tol=0.1)

    def test_channel_mix_grayscale_matrix(self):
        # Standard luminance weights.
        curve = PaletteResponseCurve(
            mode="channel_mix",
            params={
                "rr": 0.299,
                "rg": 0.587,
                "rb": 0.114,
                "gr": 0.299,
                "gg": 0.587,
                "gb": 0.114,
                "br": 0.299,
                "bg": 0.587,
                "bb": 0.114,
            },
        )
        input_lab = rgb_to_lab(0.9, 0.1, 0.1)  # strong red
        out = evaluate(curve, input_lab)
        # Output should have near-zero chroma (grayscaled).
        assert abs(out[1]) < 2.0
        assert abs(out[2]) < 2.0

    def test_channel_mix_missing_param_raises(self):
        curve = PaletteResponseCurve(
            mode="channel_mix",
            params={"rr": 1.0, "rg": 0.0, "rb": 0.0},  # incomplete
        )
        with pytest.raises(CurveParamError, match="channel_mix"):
            evaluate(curve, (50.0, 0.0, 0.0))


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


class TestPostProcessing:
    def test_preserve_luminance_keeps_input_l(self):
        curve = PaletteResponseCurve(
            mode="lab_shift",
            params={"delta_l": 30.0, "delta_a": 5.0, "delta_b": -5.0},
            preserve_luminance=True,
        )
        out = evaluate(curve, (50.0, 0.0, 0.0))
        assert out[0] == 50.0  # L* preserved
        assert out[1] == 5.0
        assert out[2] == -5.0

    def test_clip_s_curve_clamps_luminance(self):
        curve = PaletteResponseCurve(
            mode="lab_shift",
            params={"delta_l": 50.0, "delta_a": 0.0, "delta_b": 0.0},
            clip_s_curve=(10.0, 80.0),
        )
        # 80 + 50 = 130 → clamped to 80
        out = evaluate(curve, (80.0, 0.0, 0.0))
        assert out[0] == 80.0

        # 0 - 50 would go negative, but no negative shift here
        # Test lower bound with negative shift:
        curve2 = PaletteResponseCurve(
            mode="lab_shift",
            params={"delta_l": -50.0},
            clip_s_curve=(10.0, 80.0),
        )
        out2 = evaluate(curve2, (20.0, 0.0, 0.0))
        # 20 - 50 = -30 → clamped to 10
        assert out2[0] == 10.0


# ---------------------------------------------------------------------------
# Top-level + palette-aware path
# ---------------------------------------------------------------------------


class TestTopLevel:
    def test_unknown_mode_raises(self):
        # Need to bypass the pydantic Literal; construct manually.
        # The evaluator's dispatch covers all declared modes, so this
        # is really a paranoid pin that future mode additions get
        # wired in :func:`evaluate`.
        curve = PaletteResponseCurve(mode="identity")
        # Monkey-patch past the frozen model for test purposes.
        object.__setattr__(curve, "mode", "nonexistent")
        with pytest.raises(CurveParamError, match="unknown curve mode"):
            evaluate(curve, (50.0, 0.0, 0.0))

    def test_apply_palette_shortcut(self):
        palette = ScrimPalette(
            id="x",
            display_name="X",
            dominant_lab=(70.0, 10.0, 20.0),
            accent_lab=(30.0, 5.0, 10.0),
            curve=PaletteResponseCurve(mode="duotone"),  # uses anchor fallback
        )
        out = apply_palette(palette, (50.0, 0.0, 0.0))
        # Duotone of (30, 5, 10) ↔ (70, 10, 20) at t=0.5 → (50, 7.5, 15)
        assert math.isclose(out[0], 50.0, abs_tol=0.01)
        assert math.isclose(out[1], 7.5, abs_tol=0.01)
        assert math.isclose(out[2], 15.0, abs_tol=0.01)


# ---------------------------------------------------------------------------
# Smoke: run every registry palette through its own curve without raising.
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    @pytest.fixture
    def registry(self):
        return PaletteRegistry.load()

    def test_every_palette_evaluates_without_error(self, registry):
        """Every palette in the shipped registry must produce a valid
        LAB triple when its curve is applied to a neutral input."""
        test_input = (50.0, 0.0, 0.0)
        for palette in registry.all_palettes():
            out = apply_palette(palette, test_input)
            assert len(out) == 3
            assert all(isinstance(v, float) for v in out)
            # L* should stay roughly in range (may slightly exceed after
            # shift modes, that's OK — clip_s_curve handles tight bounds).
            assert -50.0 <= out[0] <= 150.0

    def test_registry_palettes_cover_all_modes(self, registry):
        """The shipped registry exercises every curve mode so the
        `test_every_palette_evaluates_without_error` pin has coverage."""
        modes_used = {p.curve.mode for p in registry.all_palettes()}
        expected = {
            "lab_shift",
            "duotone",
            "gradient_map",
            "hue_rotate",
            "channel_mix",
        }
        assert expected.issubset(modes_used)
