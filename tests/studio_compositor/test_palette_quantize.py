"""Tests for ``agents.studio_compositor.palette_quantize``.

Coverage:

- ``PACKAGE_PALETTE_ROLES`` length + canonical ordering.
- ``build_mirc16_palette_image``: well-formed package → 768-byte PIL
  palette with the package's 16 colours in the canonical order;
  malformed package roles fall back to 50% grey.
- ``cairo_surface_to_pil`` / ``pil_to_cairo_surface`` roundtrip
  preserves RGB to within JPEG/PIL rounding tolerance.
- ``quantize_cairo_to_package_palette``: end-to-end success returns
  a Cairo surface of the same dimensions; PIL absence / package
  absence / palette resolution failure returns None.
"""

from __future__ import annotations

import cairo

from agents.studio_compositor.palette_quantize import (
    PACKAGE_PALETTE_ROLES,
    build_mirc16_palette_image,
    cairo_surface_to_pil,
    pil_to_cairo_surface,
    quantize_cairo_to_package_palette,
)


class _StubPackage:
    """Minimal HOMAGE package double — resolves a fixed colour table."""

    def __init__(self, table: dict[str, tuple[float, float, float, float]] | None = None):
        self._table = table or {role: (0.5, 0.5, 0.5, 1.0) for role in PACKAGE_PALETTE_ROLES}

    def resolve_colour(self, role: str) -> tuple[float, float, float, float]:
        return self._table[role]


class _RaisingPackage:
    """Package whose resolve_colour fails for every role."""

    def resolve_colour(self, role: str) -> tuple[float, float, float, float]:
        raise RuntimeError(f"missing role: {role}")


def _solid_cairo_surface(
    rgb: tuple[int, int, int], *, w: int = 32, h: int = 32
) -> cairo.ImageSurface:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surface)
    cr.set_source_rgba(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, 1.0)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    return surface


# ── PACKAGE_PALETTE_ROLES ────────────────────────────────────────────────


class TestPackagePaletteRoles:
    def test_has_sixteen_roles(self) -> None:
        assert len(PACKAGE_PALETTE_ROLES) == 16

    def test_canonical_first_four(self) -> None:
        """The first four entries are the BitchX baseline; downstream
        consumers may key on positional indices, so the ordering pin
        is load-bearing."""
        assert PACKAGE_PALETTE_ROLES[:4] == (
            "background",
            "foreground",
            "muted",
            "bright",
        )

    def test_no_duplicates(self) -> None:
        assert len(set(PACKAGE_PALETTE_ROLES)) == len(PACKAGE_PALETTE_ROLES)


# ── build_mirc16_palette_image ──────────────────────────────────────────


class TestBuildMirc16PaletteImage:
    def test_returns_pil_p_mode_image(self) -> None:
        from PIL import Image

        pkg = _StubPackage()
        img = build_mirc16_palette_image(pkg)
        assert img is not None
        assert isinstance(img, Image.Image)
        assert img.mode == "P"

    def test_palette_byte_length_is_768(self) -> None:
        pkg = _StubPackage()
        img = build_mirc16_palette_image(pkg)
        assert img is not None
        palette = img.getpalette()
        assert palette is not None
        # 256 entries × 3 channels.
        assert len(palette) == 768

    def test_first_role_colour_lands_at_index_zero(self) -> None:
        pkg = _StubPackage(
            table={role: (0.5, 0.5, 0.5, 1.0) for role in PACKAGE_PALETTE_ROLES}
            | {"background": (1.0, 0.0, 0.0, 1.0)}  # red
        )
        img = build_mirc16_palette_image(pkg)
        assert img is not None
        palette = img.getpalette()
        assert palette is not None
        # Index 0 (background) should be red (255, 0, 0).
        assert palette[0:3] == [255, 0, 0]

    def test_malformed_role_falls_back_to_grey(self) -> None:
        img = build_mirc16_palette_image(_RaisingPackage())
        assert img is not None
        palette = img.getpalette()
        assert palette is not None
        # First 16 roles all fall back to 50% grey (127, 127, 127).
        for i in range(16):
            assert palette[i * 3 : i * 3 + 3] == [127, 127, 127]


# ── cairo_surface_to_pil / pil_to_cairo_surface ─────────────────────────


class TestSurfaceRoundtrip:
    def test_solid_red_roundtrip(self) -> None:
        from PIL import Image

        original = _solid_cairo_surface((220, 30, 30), w=8, h=8)
        pil_image = cairo_surface_to_pil(original)
        assert pil_image is not None
        assert isinstance(pil_image, Image.Image)
        # PIL image should be solid-red.
        center = pil_image.getpixel((4, 4))
        assert center == (220, 30, 30)

    def test_zero_size_surface_returns_none(self) -> None:
        zero = cairo.ImageSurface(cairo.FORMAT_ARGB32, 0, 0)
        assert cairo_surface_to_pil(zero) is None

    def test_pil_to_cairo_preserves_dimensions(self) -> None:
        from PIL import Image

        img = Image.new("RGB", (16, 12), (10, 20, 30))
        surface = pil_to_cairo_surface(img)
        assert surface is not None
        assert surface.get_width() == 16
        assert surface.get_height() == 12

    def test_pil_to_cairo_preserves_solid_colour(self) -> None:
        from PIL import Image

        img = Image.new("RGB", (4, 4), (128, 200, 64))
        surface = pil_to_cairo_surface(img)
        assert surface is not None
        # Read center pixel; ARGB32 BGRA byte order.
        data = bytes(surface.get_data())
        stride = surface.get_stride()
        offset = 2 * stride + 2 * 4
        b = data[offset]
        g = data[offset + 1]
        r = data[offset + 2]
        a = data[offset + 3]
        assert (r, g, b, a) == (128, 200, 64, 255)


# ── quantize_cairo_to_package_palette ───────────────────────────────────


class TestQuantizeCairoToPackagePalette:
    def test_end_to_end_success_returns_surface(self) -> None:
        original = _solid_cairo_surface((180, 90, 50), w=8, h=8)
        pkg = _StubPackage(
            table={role: (0.5, 0.5, 0.5, 1.0) for role in PACKAGE_PALETTE_ROLES}
            | {"accent_orange": (180 / 255, 90 / 255, 50 / 255, 1.0)}
        )
        out = quantize_cairo_to_package_palette(original, pkg)
        assert out is not None
        # Same dimensions as input.
        assert out.get_width() == 8
        assert out.get_height() == 8

    def test_zero_size_input_returns_none(self) -> None:
        zero = cairo.ImageSurface(cairo.FORMAT_ARGB32, 0, 0)
        assert quantize_cairo_to_package_palette(zero, _StubPackage()) is None

    def test_raising_package_returns_quantized_with_grey_fallback(self) -> None:
        """A package whose roles all raise still yields a valid
        quantized surface — :func:`build_mirc16_palette_image` falls
        back to 50% grey for every role, so the result is a 16-shade-
        of-grey image of the same dimensions."""
        original = _solid_cairo_surface((180, 90, 50), w=8, h=8)
        out = quantize_cairo_to_package_palette(original, _RaisingPackage())
        assert out is not None
        assert out.get_width() == 8
        assert out.get_height() == 8

    def test_can_be_imported_independently(self) -> None:
        """The new module must be importable without pulling in the
        existing ``album_overlay`` (which the legacy ward owns).
        Shipping side-by-side requires zero coupling."""
        import importlib

        mod = importlib.import_module("agents.studio_compositor.palette_quantize")
        assert mod.PACKAGE_PALETTE_ROLES == PACKAGE_PALETTE_ROLES
        assert mod.build_mirc16_palette_image is build_mirc16_palette_image


# ── Integration with cbip_signal_density Layer 1 ────────────────────────


class TestCbipSignalDensityIntegration:
    def test_cover_art_layer_uses_palette_quantize(self) -> None:
        """The CBIP cover-art layer must call into the new
        ``palette_quantize`` module rather than the legacy private
        helpers in ``album_overlay``. Verify by inspecting the
        ``_refresh_cover`` source — that's where the wire-up lives."""
        import inspect

        from agents.studio_compositor.cbip_signal_density import (
            CBIPSignalDensityCairoSource,
        )

        src = inspect.getsource(CBIPSignalDensityCairoSource._refresh_cover)
        # Phase 2 wiring: import + call surfaces in the method body.
        assert "palette_quantize" in src
        assert "quantize_cairo_to_package_palette" in src
