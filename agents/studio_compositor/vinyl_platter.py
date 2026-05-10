"""VinylPlatterCairoSource — HOMAGE-styled ward for the spinning platter.

Phase A4 (homage-completion-plan §2) classification: this module is a
Cairo source (inherits :class:`HomageTransitionalSource`) and already
routes every text path through Pango via
:mod:`agents.studio_compositor.text_render` — no ``cr.show_text``, no
``cr.select_font_face``. Typography sources the package's
``primary_font_family`` (Px437 IBM VGA 8x16 for BitchX). No rewrite
needed; the ward is already substantially emissive-compliant. Future
pointillism passes (per-glyph halos on the ``NOW SPINNING`` header,
rpm-readout emissive stroke) can land as follow-ons without breaking
the ward's current contract.

Task #159. Operator directive: when a record is playing, a camera capture
of the turntable platter should appear as a ward surface — not the album
art panel (``AlbumOverlayCairoSource``) but the platter itself, tinted
to the active HomagePackage's palette, motion-blurred in proportion to
the deck's playback rate, and framed with BitchX grammar (1-px border,
``»»»`` cardinal markers, ``NOW SPINNING`` header, rpm readout).

Gates on the #127 SPLATTRIBUTION ``vinyl_playing`` derived signal — the
ward is transparent (no-op) when vinyl is not actually spinning. The
source frame is the camera whose ``semantic_role`` is ``turntables``
(task #135); the module resolves the role name → camera snapshot path
at render time via ``/dev/shm/hapax-compositor/camera-classifications.json``,
falling back to ``brio-synths.jpg`` when the classification file is
absent.

Registered in ``cairo_sources/__init__.py`` under the class name
``VinylPlatterCairoSource``. The retired ``vinyl-focus`` layout was
purged in PR #2770; future platter presentation should be owned by the
current layout/effect responsibility system, not by reviving that static
layout file.
"""

from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


# ── Canvas / geometry ────────────────────────────────────────────────────

# Square canvas; the platter is circle-cropped inside with a 1-px border.
CANVAS_W: int = 360
CANVAS_H: int = 360

# Margin between the canvas edge and the platter circle so the BitchX
# border + cardinal markers have pixels to live in without clipping.
_BORDER_MARGIN_PX: int = 8

# Cardinal marker glyph (BitchX 1.3 line-start grammar). Four copies
# placed N/E/S/W around the circle.
_CARDINAL_MARKER: str = "»»»"

# Default camera frame when camera-classifications.json is missing or
# unreadable — the brio-synths BRIO is the turntable camera per the
# council config (agents/studio_compositor/config.py).
_DEFAULT_CAMERA_FRAME: Path = Path("/dev/shm/hapax-compositor/brio-synths.jpg")
_CAMERA_CLASSIFICATIONS: Path = Path("/dev/shm/hapax-compositor/camera-classifications.json")
_SNAPSHOT_DIR: Path = Path("/dev/shm/hapax-compositor")

# Nominal RPM reference for the readout. Operator plays 33⅓ records at
# the 33⅓ preset (rate 1.0) and 45-on-33 (rate 0.741) — the readout
# displays observed RPM = nominal × rate with two decimals of precision.
_NOMINAL_RPM: float = 33.333

# Motion-blur bank: fewer samples at rest, more when spinning fast. Blur
# samples are rotational, not linear — the platter spins so the blur
# kernel is a series of rotated stamps around the platter centre.
_BLUR_SAMPLES_MIN: int = 1
_BLUR_SAMPLES_MAX: int = 6
_BLUR_MAX_DEG: float = 18.0  # maximum rotational spread at rate 1.0


# ── Camera resolution ────────────────────────────────────────────────────


def _resolve_turntables_camera_frame() -> Path:
    """Read the camera classifications file and return the snapshot path
    for the camera whose ``semantic_role`` is ``turntables``.

    Falls back to ``_DEFAULT_CAMERA_FRAME`` (``brio-synths.jpg``) when
    the classifications file is missing, malformed, or lists no
    turntables camera. The compositor snapshot filename convention is
    ``<role>.jpg`` under ``/dev/shm/hapax-compositor/``.
    """
    try:
        if _CAMERA_CLASSIFICATIONS.exists():
            data = json.loads(_CAMERA_CLASSIFICATIONS.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for role, meta in data.items():
                    if not isinstance(meta, dict):
                        continue
                    if meta.get("semantic_role") == "turntables":
                        return _SNAPSHOT_DIR / f"{role}.jpg"
    except Exception:
        log.debug("camera-classifications read failed; using default", exc_info=True)
    return _DEFAULT_CAMERA_FRAME


# ── Playback rate ────────────────────────────────────────────────────────


def _read_playback_rate() -> float:
    """Thin wrapper over ``shared.vinyl_rate.read_vinyl_playback_rate``.

    Imported inside the function so module import stays cheap and test
    monkeypatching works without having to patch the shared module.
    """
    try:
        from shared.vinyl_rate import read_vinyl_playback_rate

        return read_vinyl_playback_rate()
    except Exception:
        log.debug("vinyl-rate probe failed; defaulting to 1.0", exc_info=True)
        return 1.0


def _vinyl_playing() -> bool:
    """#127 SPLATTRIBUTION gate — is a vinyl actually spinning?

    Fail-CLOSED on error (opposite of ``album_overlay``): the platter
    ward is dramatic when present, so we'd rather show nothing during
    a transient probe failure than render a stale snapshot with the
    HOMAGE tint.
    """
    try:
        from shared.perceptual_field import build_perceptual_field

        return build_perceptual_field().vinyl_playing
    except Exception:
        log.debug("vinyl_playing probe failed; gating closed", exc_info=True)
        return False


# ── Rotational blur kernel ───────────────────────────────────────────────


def _blur_samples_for_rate(rate: float) -> int:
    """Number of rotated stamps for the motion-blur kernel.

    Rate 0.0 (stopped) → 1 stamp (no blur). Rate 1.0 (nominal) → max
    samples. Intermediate values interpolate linearly. Clamped so a
    non-finite / negative rate never yields 0 (which would skip the
    frame entirely).
    """
    if not math.isfinite(rate) or rate <= 0.0:
        return _BLUR_SAMPLES_MIN
    r = min(1.0, rate)
    span = _BLUR_SAMPLES_MAX - _BLUR_SAMPLES_MIN
    return _BLUR_SAMPLES_MIN + max(0, round(span * r))


def _blur_spread_deg(rate: float) -> float:
    """Rotational spread (degrees) for the blur kernel at ``rate``."""
    if not math.isfinite(rate) or rate <= 0.0:
        return 0.0
    return _BLUR_MAX_DEG * min(1.0, rate)


# ── Cairo source ─────────────────────────────────────────────────────────


class VinylPlatterCairoSource(HomageTransitionalSource):
    """HOMAGE-styled ward showing the spinning platter.

    The render flow:

    1. Probe ``vinyl_playing`` — if False, return without drawing so the
       runner publishes a transparent surface.
    2. Resolve the turntables camera snapshot via camera-classifications,
       load it through the shared image loader.
    3. Paint the BitchX-skeleton background + 1-px border with ``»»»``
       cardinal markers.
    4. Circle-crop the camera frame into the inner disk, composite with
       rotational motion-blur stamps (count ∝ rate).
    5. Apply a HOMAGE-package palette tint overlay.
    6. Draw ``NOW SPINNING`` header and ``[rpm 33.33/44.80 +1.41]``
       readout in Px437 IBM VGA 8×16.
    """

    def __init__(self) -> None:
        super().__init__(source_id="vinyl_platter")

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pkg = get_active_package()
        if pkg is None:
            # Consent-safe layout — HOMAGE disabled. Paint nothing.
            return

        if not _vinyl_playing():
            # #127 SPLATTRIBUTION gate. Transparent surface = "no ward".
            return

        rate = _read_playback_rate()
        frame_path = _resolve_turntables_camera_frame()

        cx = canvas_w / 2.0
        cy = canvas_h / 2.0
        radius = min(canvas_w, canvas_h) / 2.0 - _BORDER_MARGIN_PX

        # 2026-04-23 operator directive: zero container opacity. Canvas
        # background fill retired — corners outside the platter disk are
        # now transparent, letting the substrate show through.
        _ = pkg  # package still needed below for tint + border markers

        # Platter disk (camera frame, circle-cropped, motion-blurred).
        self._draw_platter_disk(cr, cx, cy, radius, rate, frame_path)

        # HOMAGE palette tint overlay — multiplicative wash in the
        # package's identity-accent hue.
        self._draw_homage_tint(cr, cx, cy, radius, pkg)

        # BitchX border + cardinal ``»»»`` markers.
        self._draw_border(cr, canvas_w, canvas_h, pkg)

        # Header + rpm readout.
        self._draw_labels(cr, canvas_w, rate, pkg)

    # ── draw helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _draw_platter_disk(
        cr: cairo.Context,
        cx: float,
        cy: float,
        radius: float,
        rate: float,
        frame_path: Path,
    ) -> None:
        """Circle-crop the camera frame into a disk + rotational blur.

        When the frame is unavailable the disk is filled with a dim
        muted grey so the ward still reads as a platter silhouette
        rather than vanishing.
        """
        from agents.studio_compositor.image_loader import get_image_loader

        surface = None
        if os.path.exists(frame_path):
            surface = get_image_loader().load(frame_path)

        samples = _blur_samples_for_rate(rate)
        spread_deg = _blur_spread_deg(rate)
        sample_alpha = 1.0 / samples if samples > 0 else 1.0

        cr.save()
        # Clip to the platter disk so the source frame + blur stamps
        # are bounded by the circular crop.
        cr.arc(cx, cy, radius, 0.0, 2.0 * math.pi)
        cr.clip()

        if surface is None:
            # No frame yet — paint a muted grey placeholder so the disk
            # reads correctly and the blur/tint/border still render.
            cr.set_source_rgba(0.2, 0.2, 0.2, 1.0)
            cr.rectangle(cx - radius, cy - radius, 2 * radius, 2 * radius)
            cr.fill()
            cr.restore()
            return

        sw = surface.get_width()
        sh = surface.get_height()
        if sw <= 0 or sh <= 0:
            cr.restore()
            return

        # Scale the camera frame so its shorter edge covers the disk
        # diameter. Centre the frame on (cx, cy).
        scale = (2.0 * radius) / min(sw, sh)
        dx = cx - (sw * scale) / 2.0
        dy = cy - (sh * scale) / 2.0

        for i in range(samples):
            if samples > 1:
                # Distribute stamps symmetrically around zero so the
                # non-blurred centre aligns with the live frame pose.
                t = (i / (samples - 1)) - 0.5
            else:
                t = 0.0
            angle_rad = math.radians(spread_deg * t)
            cr.save()
            cr.translate(cx, cy)
            cr.rotate(angle_rad)
            cr.translate(-cx, -cy)
            cr.translate(dx, dy)
            cr.scale(scale, scale)
            cr.set_source_surface(surface, 0, 0)
            cr.paint_with_alpha(sample_alpha)
            cr.restore()

        cr.restore()

    @staticmethod
    def _draw_homage_tint(
        cr: cairo.Context,
        cx: float,
        cy: float,
        radius: float,
        pkg: Any,
    ) -> None:
        """Overlay a HOMAGE-accent wash bounded by the platter disk.

        Uses the package's ``identity_colour_role`` (BitchX: ``bright``)
        at modest alpha so the camera frame stays legible while the
        platter reads as tinted.
        """
        role = pkg.grammar.identity_colour_role
        r, g, b, _a = pkg.resolve_colour(role)
        cr.save()
        cr.arc(cx, cy, radius, 0.0, 2.0 * math.pi)
        cr.clip()
        cr.set_source_rgba(r, g, b, 0.22)
        cr.rectangle(cx - radius, cy - radius, 2 * radius, 2 * radius)
        cr.fill()
        cr.restore()

    @staticmethod
    def _draw_border(
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        pkg: Any,
    ) -> None:
        """1-px BitchX border + ``»»»`` markers at the four cardinals.

        The border traces the canvas rectangle (not the platter circle)
        so the ward reads as a framed panel. Markers sit outside the
        platter disk, inside the border margin.
        """
        cx = canvas_w / 2.0
        cy = canvas_h / 2.0

        # 2026-04-23 operator directive: zero container opacity. The
        # 1 px canvas-rectangle border is chrome — retired. The ``»»»``
        # cardinal markers below remain (they're content glyphs, not
        # container decoration).
        _ = pkg  # package still used for the marker colour below

        # ``»»»`` at N / E / S / W. Uses the ``render_text`` helper so
        # Pango does the glyph work when the typelibs are present; falls
        # through to a no-op in CI where Pango is missing (the border
        # rectangle still draws, which is the load-bearing element).
        try:
            from agents.studio_compositor.text_render import TextStyle, render_text
        except Exception:
            return

        font = f"{pkg.typography.primary_font_family} {pkg.typography.size_classes['compact']}"
        color = pkg.resolve_colour(pkg.grammar.punctuation_colour_role)

        # North — top-centre just above the platter edge. The glyphs are
        # the BitchX line-start marker, rotated 0° (reads left→right).
        style = TextStyle(
            text=_CARDINAL_MARKER,
            font_description=font,
            color_rgba=color,
        )
        render_text(cr, style, x=cx - 18, y=2)
        # South — bottom-centre just below the platter edge.
        render_text(cr, style, x=cx - 18, y=canvas_h - 16)
        # West — left-centre.
        render_text(cr, style, x=2, y=cy - 8)
        # East — right-centre.
        render_text(cr, style, x=canvas_w - 28, y=cy - 8)

    @staticmethod
    def _draw_labels(
        cr: cairo.Context,
        canvas_w: int,
        rate: float,
        pkg: Any,
    ) -> None:
        """``NOW SPINNING`` header + BitchX-grammar rpm readout.

        Header sits at the top; readout sits at the bottom. Both use
        the package's primary font at the ``compact`` size class so
        the raster grammar stays intact.
        """
        try:
            from agents.studio_compositor.text_render import TextStyle, render_text
        except Exception:
            return

        font_normal = (
            f"{pkg.typography.primary_font_family} {pkg.typography.size_classes['normal']}"
        )
        font_compact = (
            f"{pkg.typography.primary_font_family} {pkg.typography.size_classes['compact']}"
        )
        identity = pkg.resolve_colour(pkg.grammar.identity_colour_role)
        content = pkg.resolve_colour(pkg.grammar.content_colour_role)

        # Header — identity-colour, normal size.
        header_style = TextStyle(
            text="NOW SPINNING",
            font_description=font_normal,
            color_rgba=identity,
        )
        render_text(cr, header_style, x=24, y=18)

        # Readout — content-colour, compact size. BitchX grammar:
        # ``[rpm <observed>/<nominal> +<delta>]``.
        observed_rpm = _NOMINAL_RPM * rate if rate > 0 else 0.0
        nominal_rpm = _NOMINAL_RPM / rate if rate > 0 else _NOMINAL_RPM
        delta = observed_rpm - _NOMINAL_RPM
        sign = "+" if delta >= 0 else "-"
        readout = f"[rpm {observed_rpm:.2f}/{nominal_rpm:.2f} {sign}{abs(delta):.2f}]"
        readout_style = TextStyle(
            text=readout,
            font_description=font_compact,
            color_rgba=content,
        )
        render_text(cr, readout_style, x=24, y=CANVAS_H - 24)


__all__ = [
    "CANVAS_H",
    "CANVAS_W",
    "VinylPlatterCairoSource",
    "_blur_samples_for_rate",
    "_blur_spread_deg",
    "_read_playback_rate",
    "_resolve_turntables_camera_frame",
    "_vinyl_playing",
]
