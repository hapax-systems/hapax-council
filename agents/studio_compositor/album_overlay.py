"""Album cover + splattribution text overlay.

Reads the IR album cover image from ``/dev/shm/hapax-compositor/album-cover.png``
and the splattribution text from ``music-attribution.txt``. Sits in the
lower-left quadrant of the frame.

Phase A4 (homage-completion-plan §2): the five-random ``_pip_fx_*`` dict is
DELETED. A single :func:`_pip_fx_package` quantises the cover to the active
:class:`HomagePackage`'s 16 palette roles via PIL ordered-dither, draws
horizontal scanlines in the package's ``muted`` role, an ordered-dither
shadow in ``accent_magenta``, and a 2-px sharp border in the ward's domain
accent. Splattribution renders in Px437 via Pango through
:mod:`text_render`. BitchX header sits above the attribution.

The per-tick draw logic lives in :class:`AlbumOverlayCairoSource`, which
conforms to the :class:`CairoSource` protocol. The thread loop and
output-surface caching are owned by :class:`CairoSourceRunner`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import cairo

from .homage.rendering import active_package, paint_bitchx_header
from .homage.transitional_source import HomageTransitionalSource

log = logging.getLogger(__name__)


# Canvas layout for the CairoSource surface. The cover itself is SIZE x SIZE;
# the text buffer above it reserves room for the attribution markup so the
# facade can blit the whole thing as a single surface.
SIZE = 300
TEXT_BUFFER = 150
CANVAS_W = SIZE
CANVAS_H = SIZE + TEXT_BUFFER

COVER_PATH = "/dev/shm/hapax-compositor/album-cover.png"
ATTRIB_PATH = "/dev/shm/hapax-compositor/music-attribution.txt"
ALPHA = 0.85
RENDER_FPS = 10

# 2026-04-23 Gemini-reapproach Plan B Phase B3 — audio-reactive chromatic
# aberration. Max pixel offset between red and blue channel shifts at peak
# bass. Operator directive: "audio reactivity is good. Blinking is bad." —
# translate (displacement) and channel-shift magnitude are permitted
# modulations; alpha modulation is FORBIDDEN.
_CHROMATIC_MAX_OFFSET_PX = 6.0
_CHROMATIC_CHANNEL_ALPHA = 0.55


def _read_bass_band() -> float:
    """Read the blended ``bass_band`` signal from the unified reactivity bus.

    Returns 0.0 when SHM is missing / malformed / bus is dormant. This is a
    positive-only signal (monotonic audio energy in [0, 1]); consumers can
    treat 0.0 as "no audio" without distinguishing "no bus" from "silent".
    """
    try:
        from shared.audio_reactivity import read_shm_snapshot

        snapshot = read_shm_snapshot()
        if snapshot is None:
            return 0.0
        return float(snapshot.blended.bass_band)
    except Exception:
        return 0.0


# --- mIRC-16 package-palette PiP effect ------------------------------------
#
# Replaces the five-random ``_pip_fx_*`` dict per spec §5.2. Single Cairo
# effect that quantises the cover to the active package's 16 roles via
# PIL ordered-dither, draws raster scanlines + shadow mask + sharp border.


# Order of package palette roles consulted to build the 16-colour quantise
# target. Six accents + four structural roles + six tonal duplicates fill
# the mIRC-16 slots; PIL's palette-image requires exactly 16 × 3 bytes.
_PACKAGE_PALETTE_ROLES: tuple[str, ...] = (
    "background",
    "muted",
    "terminal_default",
    "bright",
    "accent_cyan",
    "accent_magenta",
    "accent_green",
    "accent_yellow",
    "accent_red",
    "accent_blue",
    # Fill remaining 6 slots with role echoes so quantise spreads cleanly.
    "bright",
    "terminal_default",
    "muted",
    "accent_cyan",
    "accent_magenta",
    "accent_yellow",
)


def _build_mirc16_palette_image(pkg: Any) -> Any | None:
    """Construct a PIL 'P'-mode image whose palette contains the package's
    16 mIRC roles. Returns ``None`` if PIL is unavailable.
    """
    try:
        from PIL import Image
    except Exception:
        return None
    palette_bytes = bytearray()
    for role in _PACKAGE_PALETTE_ROLES:
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
    # PIL expects a 768-byte palette (256 * 3); pad the rest with black.
    palette_bytes += bytes(3 * (256 - len(_PACKAGE_PALETTE_ROLES)))
    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(bytes(palette_bytes))
    return palette_img


def _cairo_surface_to_pil(surface: cairo.ImageSurface) -> Any | None:
    """Copy a Cairo ARGB32 surface into a PIL RGB image.

    Cairo ARGB32 is premultiplied BGRA little-endian; we un-swizzle by
    reading channel bytes. Returns ``None`` on failure so callers can
    skip the quantise pass.
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
    # Reassemble into RGB ignoring alpha — the quantise is content-only.
    rows = []
    for y in range(sh):
        row = bytearray(sw * 3)
        for x in range(sw):
            base = y * stride + x * 4
            # BGRA → RGB.
            row[x * 3 + 0] = data[base + 2]
            row[x * 3 + 1] = data[base + 1]
            row[x * 3 + 2] = data[base + 0]
        rows.append(bytes(row))
    return Image.frombytes("RGB", (sw, sh), b"".join(rows))


def _pil_to_cairo_surface(img: Any) -> cairo.ImageSurface | None:
    """Convert a PIL RGB image back to a Cairo ARGB32 surface (premultiplied)."""
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
    return surface


def _paint_channel_shift(
    cr: cairo.Context,
    source: cairo.ImageSurface,
    *,
    offset_px: float,
    channel_rgb: tuple[float, float, float],
    direction: tuple[float, float],
    alpha: float,
) -> None:
    """Mask ``source`` by ``channel_rgb``, translate, additive-composite.

    ``alpha`` is the constant composite opacity — never time-varying.
    """
    r, g, b = channel_rgb
    dx, dy = direction
    cr.save()
    cr.translate(offset_px * dx, offset_px * dy)
    cr.push_group()
    cr.set_source_surface(source, 0, 0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_IN)
    cr.set_source_rgba(r, g, b, 1.0)
    cr.paint()
    cr.pop_group_to_source()
    cr.set_operator(cairo.OPERATOR_ADD)
    cr.paint_with_alpha(alpha)
    cr.restore()


def _pip_fx_package(
    cr: cairo.Context,
    w: int,
    h: int,
    package: Any,
    *,
    ward_id: str = "album_overlay",
    cover_surface: cairo.ImageSurface | None = None,
    bass_band: float = 0.0,
    cover_scale: float = 1.0,
) -> None:
    """Apply the single package-palette PiP effect + audio-reactive aberration.

    Steps per spec §5.2 + 2026-04-23 Phase B3:

    1. Quantise the cover (already composited below) to the package's
       16-role palette via PIL ordered-dither. No-op if PIL missing.
    2. Horizontal scanlines every 3 px in ``package.muted`` α=0.18.
    3. Ordered-dither shadow mask in ``accent_magenta`` α=0.22 along
       the bottom 25% of the PiP.
    4. 2-px sharp border in the ward's domain-accent role.
    5. (optional) R/B chromatic aberration at magnitude ∝ ``bass_band``.
       Uses ``push_group`` / ``pop_group_to_source`` to mask each channel
       of the underlying cover surface, translate by ±offset, and additive-
       composite back at constant α. The OFFSET modulates with audio;
       the ALPHA does NOT — this is what ``feedback_no_blinking_homage_wards``
       demands.
    """
    # Step 3 (scanlines) — package.muted at 3-px cadence.
    try:
        mr, mg, mb, _ = package.resolve_colour("muted")
    except Exception:
        mr, mg, mb = 0.4, 0.4, 0.4
    cr.save()
    cr.set_source_rgba(mr, mg, mb, 0.18)
    y = 0
    while y < h:
        cr.rectangle(0, y, w, 1)
        y += 3
    cr.fill()
    cr.restore()

    # Step 4 (shadow mask) — ordered-dither chequer pattern in
    # accent_magenta along the bottom 25% of the PiP.
    try:
        am_r, am_g, am_b, _ = package.resolve_colour("accent_magenta")
    except Exception:
        am_r, am_g, am_b = 0.78, 0.0, 0.78
    shadow_top = int(h * 0.75)
    cr.save()
    cr.set_source_rgba(am_r, am_g, am_b, 0.22)
    # Bayer-4-ish ordered pattern: hit every 2nd px on alternating rows.
    row = shadow_top
    while row < h:
        xoff = (row // 2) % 2
        x = xoff
        while x < w:
            cr.rectangle(x, row, 1, 1)
            x += 2
        row += 1
    cr.fill()
    cr.restore()

    # Step 5 (chromatic aberration) — 2026-04-23 RETIRED.
    # Operator flagged CBIP as still blinking after the earlier no-flash
    # sweep. The effect gates on ``bass_band > 0.02`` which is a hard
    # step function; every bass transient pops the R/B channel shift
    # in and out, which reads as blinking even though the per-call
    # alpha is constant. Retired until a properly-enveloped version
    # (low-pass smoothed bass, always-rendering at small offset with
    # magnitude modulation instead of on/off gate) can replace it.
    _ = (cover_surface, bass_band, cover_scale)  # retained for signature

    # Step 6 (border) — RETIRED 2026-04-20.
    # The 2-px sharp border in the ward's domain accent role was drawing
    # an empty-container chrome around the entire 400x520 PiP surface even
    # when the actual content (splattribution text + small cover image)
    # was sparse — operator-visible "outline of a container that is not
    # really containing anything". Per the CBIP (Chess Boxing Interpretive
    # Plane, formerly album/vinyl ward) directive that this surface should
    # do interpretive content not container chrome, the always-on border
    # is dropped. If a future Programme variant wants emphasis chrome it
    # should opt-in via paint_emphasis_border (which gates on
    # ward_properties.glow_radius_px > 0.5 — operator-driven, not always-on).


class AlbumOverlayCairoSource(HomageTransitionalSource):
    """HomageTransitionalSource implementation for the album cover overlay.

    Owns the cached album cover surface and the splattribution text.
    Phase A4: the per-album random PiP effect has been retired — the
    single :func:`_pip_fx_package` renders into the active package's
    palette on every tick.
    """

    def __init__(self) -> None:
        super().__init__(source_id="album_overlay")
        self._surface: cairo.ImageSurface | None = None
        self._surface_mtime: float = 0.0
        self._attrib_text: str = ""
        self._attrib_mtime: float = 0.0

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        # Per-ward visibility + alpha modulation lives in the runner
        # (``cairo_source.CairoSourceRunner._render_one_frame``); this
        # method draws unconditionally.
        #
        # 2026-04-20 fix: cover refresh + attribution draw are NO LONGER
        # gated on vinyl_playing. Operator complaint: the album cover +
        # splattribution were silently invisible whenever the OXI One
        # MIDI transport wasn't actively PLAYING, even though
        # /dev/shm/hapax-compositor/album-cover.png and album-state.json
        # were fresh. The vinyl_playing signal still gates other
        # consumers (twitch director "music is playing" framing, twitch
        # programme rotation) — but this PiP should display the most
        # recently identified album whenever the data exists. That's the
        # operator's mental model for "the album panel".
        self._refresh_cover()
        self._refresh_attribution()

        cr.save()
        cr.translate(0, TEXT_BUFFER)

        if self._attrib_text:
            self._draw_attrib(cr)

        if self._surface is not None:
            sw = self._surface.get_width()
            sh = self._surface.get_height()
            if sw > 0 and sh > 0:
                scale = SIZE / max(sw, sh)
                cr.save()
                cr.scale(scale, scale)
                cr.set_source_surface(self._surface, 0, 0)
                cr.paint_with_alpha(ALPHA)
                cr.restore()

                # Phase A4: single package-palette PiP effect. Resolves
                # the active package per-tick so a mid-flight package
                # swap (e.g. consent-safe) carries through without reload.
                # 2026-04-23 Phase B3: adds audio-reactive chromatic
                # aberration via _read_bass_band(). Effect only engages
                # when the reactivity bus is populated AND bass_band
                # exceeds 0.02 — silent idle stays effect-free.
                try:
                    pkg = active_package()
                    _pip_fx_package(
                        cr,
                        SIZE,
                        SIZE,
                        pkg,
                        cover_surface=self._surface,
                        bass_band=_read_bass_band(),
                        cover_scale=scale,
                    )
                except Exception:
                    log.debug("album pip_fx_package failed", exc_info=True)

        cr.restore()

    def _vinyl_playing(self) -> bool:
        """Consult the derived #127 SPLATTRIBUTION signal.

        Fail-open on error: if the perceptual field can't be built
        (missing dependency, transient /dev/shm state), allow rotation
        so we degrade no worse than pre-#127 behavior.
        """
        try:
            from shared.perceptual_field import build_perceptual_field

            return build_perceptual_field().vinyl_playing
        except Exception:
            log.debug("vinyl_playing probe failed; allowing rotation", exc_info=True)
            return True

    def _refresh_cover(self) -> None:
        try:
            if not os.path.exists(COVER_PATH):
                return
            mtime = os.path.getmtime(COVER_PATH)
        except OSError:
            return
        # Wiring-audit smoking gun #1: prior version cached mtime
        # unconditionally, including when the load returned None (file
        # mid-write, transient PIL failure, etc). Subsequent ticks then
        # early-returned because `mtime == self._surface_mtime`, leaving
        # the cover permanently None until the file mtime changed again.
        # Fix: skip only when mtime matches AND the surface actually
        # loaded successfully. If prior load produced None, keep retrying
        # on every tick.
        if mtime == self._surface_mtime and self._surface is not None:
            return

        from .image_loader import get_image_loader

        loaded = get_image_loader().load(COVER_PATH)
        if loaded is None:
            # Don't update mtime cache on failure — we want to retry
            # next tick with the same file.
            return
        self._surface = loaded
        self._surface_mtime = mtime
        if self._surface is not None:
            log.info(
                "Album cover loaded (%dx%d)",
                self._surface.get_width(),
                self._surface.get_height(),
            )
        else:
            log.warning("Album cover load failed: %s", COVER_PATH)

    def _refresh_attribution(self) -> None:
        try:
            if not os.path.exists(ATTRIB_PATH):
                self._attrib_text = ""
                self._attrib_mtime = 0.0
                return
            mtime = os.path.getmtime(ATTRIB_PATH)
        except OSError:
            self._attrib_text = ""
            self._attrib_mtime = 0.0
            return
        if mtime == self._attrib_mtime:
            return
        try:
            self._attrib_text = Path(ATTRIB_PATH).read_text().strip()
        except OSError:
            return
        self._attrib_mtime = mtime

    def _draw_attrib(self, cr: cairo.Context) -> None:
        """Draw splattribution text above the album cover with a BitchX
        ``»»» ALBUM`` header so the ward reads as active mIRC-contract
        composition rather than a bare caption.

        Phase A4: font family sourced from the active package's primary
        family (Px437 IBM VGA 8x16 for BitchX). Typography now routes
        through the shared Pango helper so fontconfig resolves the
        raster family rather than Cairo's toy fallback.
        """
        from .text_render import OUTLINE_OFFSETS_4, TextStyle, measure_text, render_text

        escaped = self._attrib_text.replace("&", "&amp;").replace("<", "&lt;")
        try:
            pkg = active_package()
            font_family = pkg.typography.primary_font_family
        except Exception:
            pkg = None
            font_family = "Px437 IBM VGA 8x16"

        style = TextStyle(
            text=escaped,
            font_description=f"{font_family} 16",
            color_rgba=(1.0, 0.97, 0.90, 1.0),
            outline_color_rgba=(0.0, 0.0, 0.0, 0.85),
            outline_offsets=OUTLINE_OFFSETS_4,
            max_width_px=SIZE,
            wrap="word_char",
            markup_mode=True,
        )
        _w, h = measure_text(cr, style)
        render_text(cr, style, x=0, y=-h - 5)
        # BitchX-grammar header: ``»»» ALBUM`` above the splattribution
        # block. Uses ``paint_bitchx_header`` which routes through Pango.
        if pkg is not None:
            try:
                paint_bitchx_header(
                    cr,
                    "ALBUM",
                    pkg,
                    accent_role="accent_magenta",
                    x=0.0,
                    y=-h - 20,
                    font_size=11,
                )
            except Exception:
                log.debug("album bitchx header failed", exc_info=True)


# The pre-Phase-9 ``AlbumOverlay`` facade was removed in Phase 9 Task 29.
# Rendering now flows through ``AlbumOverlayCairoSource`` + the
# SourceRegistry + ``fx_chain.pip_draw_from_layout``.
