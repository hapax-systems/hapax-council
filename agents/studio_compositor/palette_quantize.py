"""Palette-quantization helpers for HOMAGE compositor wards.

Phase 2 of cc-task ``content-source-cbip-signal-density``. Extracted
out of ``album_overlay.py`` so wards beyond the legacy album cover
(this PR wires the helpers into the new
:class:`agents.studio_compositor.cbip_signal_density.CBIPSignalDensityCairoSource`
cover-art-base layer) can quantize images to the active HOMAGE
package's 16 mIRC palette roles without duplicating the same Pillow
plumbing.

Three public helpers:

- :func:`build_mirc16_palette_image` — package → PIL ``"P"``-mode
  paletted image holding the 16 active palette-role colours in the
  canonical mIRC order.
- :func:`cairo_surface_to_pil` — copy a Cairo ARGB32 surface into a
  PIL RGB image (un-swizzles the BGRA premultiplied byte order).
- :func:`pil_to_cairo_surface` — round-trip back to a Cairo ARGB32
  premultiplied surface.
- :func:`quantize_cairo_to_package_palette` — convenience wrapper
  combining the three steps for the common consumer path.

The legacy ``album_overlay`` private helpers
(``_build_mirc16_palette_image`` / ``_cairo_surface_to_pil`` /
``_pil_to_cairo_surface``) are **not** removed by this slice.
``album_overlay`` migration to the extracted module lands as a Phase
2b follow-up so this PR is a net-additive change with no regression
surface against the legacy ward. The module-level
:data:`PACKAGE_PALETTE_ROLES` is a verbatim copy of the legacy
ordering for the same reason.
"""

from __future__ import annotations

import logging
from typing import Any, Final

import cairo

log = logging.getLogger(__name__)

#: The 16 mIRC palette roles every HOMAGE package is required to
#: resolve. Ordering matters — PIL palettes are positional, and
#: downstream consumers may key by ordinal index when they need a
#: specific role.
PACKAGE_PALETTE_ROLES: Final[tuple[str, ...]] = (
    "background",
    "foreground",
    "muted",
    "bright",
    "terminal_default",
    "selection",
    "warning",
    "error",
    "accent_red",
    "accent_orange",
    "accent_green",
    "accent_blue",
    "accent_purple",
    "accent_cyan",
    "accent_magenta",
    "accent_yellow",
)


def build_mirc16_palette_image(pkg: Any) -> Any | None:
    """Build a PIL ``"P"``-mode image holding the 16 active palette roles.

    Returns ``None`` when PIL is unavailable. The PIL palette is 768
    bytes (256 entries × 3 channels); the trailing slots beyond the
    16 mIRC roles are zero-padded so PIL is happy with the size.

    Roles that fail to resolve (a malformed package) fall back to
    50% grey so the palette stays a valid 16-colour set rather than
    propagating the failure into a Pillow ``ValueError``.
    """
    try:
        from PIL import Image
    except Exception:
        return None
    palette_bytes = bytearray()
    for role in PACKAGE_PALETTE_ROLES:
        try:
            rgba = pkg.resolve_colour(role)
        except Exception:
            rgba = (0.5, 0.5, 0.5, 1.0)
        palette_bytes += bytes(
            [
                max(0, min(255, int(rgba[0] * 255))),
                max(0, min(255, int(rgba[1] * 255))),
                max(0, min(255, int(rgba[2] * 255))),
            ]
        )
    # Zero-pad up to PIL's expected 256-entry palette.
    palette_bytes += bytes(3 * (256 - len(PACKAGE_PALETTE_ROLES)))
    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(bytes(palette_bytes))
    return palette_img


def cairo_surface_to_pil(surface: cairo.ImageSurface) -> Any | None:
    """Copy a Cairo ARGB32 surface into a PIL RGB image.

    Cairo ARGB32 stores premultiplied BGRA in little-endian byte
    order; we un-swizzle by reading per-pixel byte offsets. Returns
    ``None`` when PIL is unavailable or the surface has zero
    dimensions.
    """
    try:
        from PIL import Image
    except Exception:
        return None
    sw = surface.get_width()
    sh = surface.get_height()
    if sw <= 0 or sh <= 0:
        return None
    stride = surface.get_stride()
    data = bytes(surface.get_data())
    rows: list[bytes] = []
    for y in range(sh):
        row = bytearray(sw * 3)
        for x in range(sw):
            base = y * stride + x * 4
            # Cairo ARGB32 little-endian → BGRA byte order; map to RGB.
            row[x * 3 + 0] = data[base + 2]
            row[x * 3 + 1] = data[base + 1]
            row[x * 3 + 2] = data[base + 0]
        rows.append(bytes(row))
    return Image.frombytes("RGB", (sw, sh), b"".join(rows))


def pil_to_cairo_surface(img: Any) -> cairo.ImageSurface | None:
    """Convert a PIL RGB image to a Cairo ARGB32 premultiplied surface.

    Alpha is forced to opaque (255) so the round-trip preserves the
    quantized RGB without introducing transparency artifacts. Returns
    ``None`` when the input image's ``size`` or ``convert`` raise.
    """
    try:
        sw, sh = img.size
        rgb = img.convert("RGB").tobytes()
    except Exception:
        return None
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
    stride = surface.get_stride()
    buf = bytearray(stride * sh)
    for y in range(sh):
        for x in range(sw):
            r = rgb[(y * sw + x) * 3 + 0]
            g = rgb[(y * sw + x) * 3 + 1]
            b = rgb[(y * sw + x) * 3 + 2]
            base = y * stride + x * 4
            # Premultiplied BGRA; alpha=255 so no scale.
            buf[base + 0] = b
            buf[base + 1] = g
            buf[base + 2] = r
            buf[base + 3] = 255
    surface.get_data()[:] = bytes(buf)
    # Cairo caches dirty state internally; mark_dirty() is required
    # after writing raw bytes via get_data() so subsequent
    # set_source_surface / paint operations actually pick up the new
    # content. Without this, downstream consumers see an all-zero
    # surface.
    surface.mark_dirty()
    return surface


def quantize_cairo_to_package_palette(
    surface: cairo.ImageSurface, pkg: Any
) -> cairo.ImageSurface | None:
    """End-to-end: Cairo surface → palette-quantized Cairo surface.

    Convenience wrapper that callers (the CBIP signal-density
    cover-art-base layer in particular) use to apply package-palette
    quantization in one call. Returns ``None`` on any failure
    (PIL missing, surface zero-sized, palette resolution failed)
    so the caller can fall back to the unquantized cover.
    """
    try:
        from PIL import Image
    except Exception:
        return None
    pil_image = cairo_surface_to_pil(surface)
    if pil_image is None:
        return None
    palette_img = build_mirc16_palette_image(pkg)
    if palette_img is None:
        return None
    try:
        quantized = pil_image.quantize(
            palette=palette_img,
            dither=Image.Dither.ORDERED,
        )
    except Exception:
        log.debug("palette_quantize: Pillow quantize failed", exc_info=True)
        return None
    return pil_to_cairo_surface(quantized)
