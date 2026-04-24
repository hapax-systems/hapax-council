"""``mirc-16-standard`` scrim palette pins.

The palette is byte-exact derived from the ``mirc16.yaml`` aesthetic-library
asset (ytb-AUTH1). These tests pin:

1. The palette validates and loads via the live ``PaletteRegistry``.
2. Each of the 16 gradient_map stops, when round-tripped LAB → sRGB → hex,
   matches the corresponding ``mirc16.yaml`` slot to within ±1/255 per
   channel (LAB float tolerance — visually indistinguishable).
3. ``dominant_lab`` corresponds to slot 11 cyan; ``accent_lab`` to slot 06
   purple (BitchX HOMAGE A6 alignment).

Spec: ytb-AUTH-PALETTE-MIRC.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from shared.palette_family import ScrimPalette
from shared.palette_registry import PaletteRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
MIRC16_YAML = REPO_ROOT / "assets" / "aesthetic-library" / "bitchx" / "colors" / "mirc16.yaml"

# D65 white point + sRGB→XYZ matrix shared with the authoring helper.
XN, YN, ZN = 0.95047, 1.00000, 1.08883


def _lab_to_xyz(L: float, a: float, b: float) -> tuple[float, float, float]:
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    delta = 6.0 / 29.0
    f3 = lambda f: f**3 if f > delta else 3.0 * delta * delta * (f - 4.0 / 29.0)  # noqa: E731
    return (XN * f3(fx), YN * f3(fy), ZN * f3(fz))


def _srgb_encode(c: float) -> float:
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * (c ** (1.0 / 2.4)) - 0.055


def _lab_to_hex(L: float, a: float, b: float) -> str:
    x, y, z = _lab_to_xyz(L, a, b)
    # XYZ → linear sRGB (inverse of the matrix used in the authoring helper).
    r = 3.2404542 * x + -1.5371385 * y + -0.4985314 * z
    g = -0.9692660 * x + 1.8760108 * y + 0.0415560 * z
    bb = 0.0556434 * x + -0.2040259 * y + 1.0572252 * z
    r, g, bb = (_srgb_encode(max(0.0, min(1.0, c))) for c in (r, g, bb))
    return "#" + "".join(f"{round(c * 255):02X}" for c in (r, g, bb))


@pytest.fixture(scope="module")
def registry() -> PaletteRegistry:
    """Live registry — pins that the new palette validates against the
    real schema, not a stripped-down test fixture."""
    return PaletteRegistry.load()


@pytest.fixture(scope="module")
def mirc16_slots() -> dict[str, str]:
    data = yaml.safe_load(MIRC16_YAML.read_text(encoding="utf-8"))
    return {str(k): v["hex"] for k, v in data["slots"].items()}


class TestPaletteLoads:
    def test_registered_under_id(self, registry: PaletteRegistry) -> None:
        palette = registry.get_palette("mirc-16-standard")
        assert isinstance(palette, ScrimPalette)
        assert palette.id == "mirc-16-standard"

    def test_curve_mode_is_gradient_map(self, registry: PaletteRegistry) -> None:
        palette = registry.get_palette("mirc-16-standard")
        assert palette.curve.mode == "gradient_map"

    def test_has_sixteen_stops(self, registry: PaletteRegistry) -> None:
        palette = registry.get_palette("mirc-16-standard")
        stops = palette.curve.params["stops"]
        assert len(stops) == 16, "mIRC palette must have one stop per slot"

    def test_recruitable_by_authentic_tag(self, registry: PaletteRegistry) -> None:
        results = registry.recruit_by_tags(["authentic", "terminal"])
        ids = {p.id for p in results}
        assert "mirc-16-standard" in ids

    def test_recruitable_by_bitchx_kin_tag(self, registry: PaletteRegistry) -> None:
        results = registry.recruit_by_tags(["bitchx-kin"])
        assert any(p.id == "mirc-16-standard" for p in results)


class TestStopsAreByteExactMIRC:
    """Each gradient_map stop must round-trip back to its source mIRC slot."""

    def test_each_stop_round_trips_to_source_hex(
        self, registry: PaletteRegistry, mirc16_slots: dict[str, str]
    ) -> None:
        palette = registry.get_palette("mirc-16-standard")
        stops = palette.curve.params["stops"]
        # Stops are ordered slot 00 → 15 (t = i/15); pair with sorted keys.
        sorted_slot_keys = sorted(mirc16_slots.keys())
        assert len(stops) == len(sorted_slot_keys)
        for slot_key, stop in zip(sorted_slot_keys, stops, strict=True):
            expected_hex = mirc16_slots[slot_key].lstrip("#").upper()
            L, a, b = stop["lab"]
            actual_hex = _lab_to_hex(L, a, b).lstrip("#").upper()
            # Allow ±1/255 per channel (LAB float math).
            er, eg, eb = (int(expected_hex[i : i + 2], 16) for i in (0, 2, 4))
            ar, ag, ab = (int(actual_hex[i : i + 2], 16) for i in (0, 2, 4))
            assert abs(er - ar) <= 1, (
                f"slot {slot_key}: red channel diverged > 1 "
                f"(expected #{expected_hex}, got #{actual_hex})"
            )
            assert abs(eg - ag) <= 1, (
                f"slot {slot_key}: green channel diverged > 1 "
                f"(expected #{expected_hex}, got #{actual_hex})"
            )
            assert abs(eb - ab) <= 1, (
                f"slot {slot_key}: blue channel diverged > 1 "
                f"(expected #{expected_hex}, got #{actual_hex})"
            )

    def test_stop_t_values_evenly_spaced(self, registry: PaletteRegistry) -> None:
        """t values should be i/15 (0.000, 0.067, ..., 1.000)."""
        palette = registry.get_palette("mirc-16-standard")
        stops = palette.curve.params["stops"]
        for i, stop in enumerate(stops):
            assert stop["t"] == pytest.approx(i / 15.0, abs=1e-3), (
                f"stop {i}: expected t={i / 15.0:.4f}, got {stop['t']}"
            )


class TestAnchorSlotsMatchHomageAlignment:
    """``dominant_lab`` = slot 11 cyan (BitchX HOMAGE A6); ``accent_lab`` =
    slot 06 purple (secondary BitchX accent). Pinning these decouples the
    HOMAGE alignment claim from drift in the per-stop authoring."""

    def test_dominant_is_slot_11_cyan(
        self, registry: PaletteRegistry, mirc16_slots: dict[str, str]
    ) -> None:
        palette = registry.get_palette("mirc-16-standard")
        L, a, b = palette.dominant_lab
        slot_hex = mirc16_slots["11"]
        actual_hex = _lab_to_hex(L, a, b).lstrip("#").upper()
        expected_hex = slot_hex.lstrip("#").upper()
        # Slot 11 is byte-exact #00FFFF.
        assert expected_hex == "00FFFF"
        # Round-trip tolerance (±1/255 per channel).
        for i in (0, 2, 4):
            assert abs(int(expected_hex[i : i + 2], 16) - int(actual_hex[i : i + 2], 16)) <= 1

    def test_accent_is_slot_06_purple(
        self, registry: PaletteRegistry, mirc16_slots: dict[str, str]
    ) -> None:
        palette = registry.get_palette("mirc-16-standard")
        L, a, b = palette.accent_lab
        slot_hex = mirc16_slots["06"]
        actual_hex = _lab_to_hex(L, a, b).lstrip("#").upper()
        expected_hex = slot_hex.lstrip("#").upper()
        assert expected_hex == "9C009C"
        for i in (0, 2, 4):
            assert abs(int(expected_hex[i : i + 2], 16) - int(actual_hex[i : i + 2], 16)) <= 1
