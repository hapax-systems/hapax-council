"""Pango text rendering — single source of truth for text-on-Cairo.

Phase 3c of the compositor unification epic. Consolidates the duplicate
Pango setup blocks in fx_chain.AlbumOverlay and overlay_zones.OverlayZone
into one helper. Future text-bearing sources construct a TextStyle and
call render_text() instead of importing PangoCairo themselves.

The helper supports two render modes:

* **Inline** — ``render_text(cr, style, x, y)`` lays out text and draws
  directly into the caller's Cairo context. Used by AlbumOverlay where
  the attribution is composited next to the cover.
* **Offscreen** — ``render_text_to_surface(style, padding)`` produces a
  standalone ``cairo.ImageSurface`` containing the laid-out text with
  outline padding. Used by OverlayZone, which caches the rendered
  surface and re-blits on every overlay frame until the markup changes.

Both call sites can also share the outline pattern via
``style.outline_offsets`` — a list of (dx, dy) tuples that defines
where the outline glyphs are drawn relative to the foreground.

See: docs/superpowers/specs/2026-04-12-phase-3-executor-polymorphism-design.md
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

import cairo

log = logging.getLogger(__name__)

# Guarded against CI environments that lack the Pango/PangoCairo typelibs.
# Same pattern as `sierpinski_renderer._HAS_GDK`. `_build_layout` short-
# circuits via `_HAS_PANGO` so the CairoSource render path becomes a
# no-op rather than raising; callers that do need real text rendering
# (running compositor on the operator workstation) always have the
# typelibs installed and land in the live path.
try:
    import gi

    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo  # noqa: E402

    _HAS_PANGO = True
except (ImportError, ValueError):
    Pango = None  # type: ignore[assignment]
    PangoCairo = None  # type: ignore[assignment]
    _HAS_PANGO = False

# Standard outline offset patterns. Callers can supply custom tuples,
# but these two cover the existing OverlayZone (8-offset thick) and
# AlbumOverlay (4-offset axis-aligned) cases verbatim.
OUTLINE_OFFSETS_4: tuple[tuple[int, int], ...] = (
    (-2, 0),
    (2, 0),
    (0, -2),
    (0, 2),
)
"""4-offset axis-aligned outline at 2px (AlbumOverlay style)."""

OUTLINE_OFFSETS_8: tuple[tuple[int, int], ...] = (
    (-3, 0),
    (3, 0),
    (0, -3),
    (0, 3),
    (-2, -2),
    (2, -2),
    (-2, 2),
    (2, 2),
)
"""8-offset thick outline at 3px (OverlayZone style)."""


@dataclass(frozen=True)
class TextStyle:
    """All knobs for one text render call.

    The dataclass is frozen so callers can hash it as a cache key.
    Outline rendering is opt-in via ``outline_offsets``; an empty tuple
    skips the outline pass entirely.

    Pango markup is opt-in via ``markup_mode``: when True the text is
    passed to ``layout.set_markup``; when False to ``layout.set_text``.
    Callers responsible for escaping ``&``, ``<``, ``>`` when using
    markup.
    """

    text: str
    font_description: str = "JetBrains Mono Bold 14"
    color_rgba: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    outline_color_rgba: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.9)
    outline_offsets: tuple[tuple[int, int], ...] = ()
    max_width_px: int | None = None
    wrap: Literal["word", "char", "word_char"] = "word_char"
    markup_mode: bool = False
    line_spacing: float = 1.0


@dataclass
class _LayoutBundle:
    """Internal: a Pango layout and its measured pixel size.

    The layout reference is opaque to callers (we don't expose
    ``Pango.Layout`` in the public API). Cached size lets the helper
    return ``(w, h)`` without re-calling ``get_pixel_size()`` from the
    outline-then-foreground render loop.
    """

    layout: object
    width_px: int
    height_px: int


def _build_layout(cr: cairo.Context, style: TextStyle) -> _LayoutBundle:
    """Construct a Pango layout for ``style`` on ``cr``.

    When the Pango typelibs are absent (CI), returns an empty bundle
    with ``width_px == height_px == 0`` so callers (measure/render)
    become safe no-ops instead of raising at import time.
    """
    if not _HAS_PANGO:
        return _LayoutBundle(layout=None, width_px=0, height_px=0)

    layout = PangoCairo.create_layout(cr)
    font = Pango.FontDescription.from_string(style.font_description)
    layout.set_font_description(font)
    if style.max_width_px is not None:
        layout.set_width(int(style.max_width_px * Pango.SCALE))
        wrap_map = {
            "word": Pango.WrapMode.WORD,
            "char": Pango.WrapMode.CHAR,
            "word_char": Pango.WrapMode.WORD_CHAR,
        }
        layout.set_wrap(wrap_map[style.wrap])
    if style.line_spacing != 1.0:
        layout.set_line_spacing(style.line_spacing)
    if style.markup_mode:
        layout.set_markup(style.text, -1)
    else:
        layout.set_text(style.text, -1)
    width_px, height_px = layout.get_pixel_size()
    return _LayoutBundle(layout=layout, width_px=width_px, height_px=height_px)


def measure_text(cr: cairo.Context, style: TextStyle) -> tuple[int, int]:
    """Lay out the text on ``cr`` and return the (width, height) in pixels.

    Useful for callers that need to size a region before drawing.
    """
    bundle = _build_layout(cr, style)
    return bundle.width_px, bundle.height_px


def render_text(
    cr: cairo.Context,
    style: TextStyle,
    x: float = 0.0,
    y: float = 0.0,
) -> tuple[int, int]:
    """Render text into ``cr`` at ``(x, y)``. Returns laid-out (w, h).

    The single Pango code path. Used by inline draws (e.g.
    AlbumOverlay attribution) where the text composites directly into
    the live cairooverlay context. No-op when Pango is unavailable.
    """
    if not _HAS_PANGO:
        return 0, 0

    bundle = _build_layout(cr, style)

    if style.outline_offsets:
        cr.set_source_rgba(*style.outline_color_rgba)
        for dx, dy in style.outline_offsets:
            cr.move_to(x + dx, y + dy)
            PangoCairo.show_layout(cr, bundle.layout)

    cr.set_source_rgba(*style.color_rgba)
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, bundle.layout)
    return bundle.width_px, bundle.height_px


def render_text_to_surface(
    style: TextStyle,
    padding_px: int = 4,
) -> tuple[cairo.ImageSurface, int, int]:
    """Render text onto a fresh ARGB surface. Returns (surface, w, h).

    Used by OverlayZone, which caches the rendered surface and re-blits
    it on every overlay tick until the underlying markup changes. The
    output surface is sized to the laid-out text plus ``padding_px`` on
    every side so the outline isn't clipped at the edges.

    The temporary 1×1 measurement surface exists because Pango font
    metrics depend on the target Cairo surface — we cannot create the
    final-size surface before knowing how big the text will be.
    """
    measure_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
    measure_cr = cairo.Context(measure_surface)
    text_w, text_h = measure_text(measure_cr, style)

    sw = text_w + padding_px * 2
    sh = text_h + padding_px * 2
    # Phase 10 R2/D1 diagnostic — delta's overlay_zones-cairo-invalid-size
    # drop captured ~50 ``cairo.Error: invalid value`` exceptions from this
    # exact line in a 4-second window. Wrapping the ImageSurface
    # construction with a diagnostic log that captures the exact inputs
    # narrows the three competing root-cause hypotheses (negative or
    # zero dims, text_w/text_h overflow, Pango layout returning garbage)
    # to one, without needing the live capture to reproduce.
    try:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
    except (cairo.Error, ValueError):
        text_preview = (style.text or "")[:80].replace("\n", "\\n")
        log.exception(
            "render_text_to_surface cairo.ImageSurface failed: "
            "sw=%d sh=%d text_w=%d text_h=%d padding_px=%d "
            "text_len=%d text_preview=%r",
            sw,
            sh,
            text_w,
            text_h,
            padding_px,
            len(style.text or ""),
            text_preview,
        )
        raise
    cr = cairo.Context(surface)
    render_text(cr, style, x=padding_px, y=padding_px)
    return surface, sw, sh


# ---------------------------------------------------------------------------
# Convenience: a TextSource subclass for code that wants a CairoSource
# ---------------------------------------------------------------------------


@dataclass
class TextChange:
    """Records that the text content changed since the last render.

    Returned by :meth:`TextContent.update` so callers can implement
    on_change cadences without recomputing the hash themselves.
    """

    changed: bool
    new_hash: int


@dataclass
class TextContent:
    """Mutable text container with content-hash change detection.

    Used by sources whose update_cadence is ``on_change``. Update the
    style via :meth:`update`, which returns a :class:`TextChange`
    indicating whether the rendered output needs to be regenerated.
    """

    style: TextStyle
    _hash: int = field(init=False)

    def __post_init__(self) -> None:
        self._hash = hash(
            (
                self.style.text,
                self.style.font_description,
                self.style.color_rgba,
                self.style.markup_mode,
            )
        )

    def update(self, style: TextStyle) -> TextChange:
        new_hash = hash(
            (
                style.text,
                style.font_description,
                style.color_rgba,
                style.markup_mode,
            )
        )
        if new_hash == self._hash:
            return TextChange(changed=False, new_hash=new_hash)
        self.style = style
        self._hash = new_hash
        return TextChange(changed=True, new_hash=new_hash)


# ---------------------------------------------------------------------------
# Phase A5 (homage-completion-plan): font-availability probes.
#
# Pango consults fontconfig (so Px437 IBM VGA 8x16 resolves via the
# standard TTF install) where Cairo's toy ``select_font_face`` falls
# back to DejaVu Sans Mono for unknown family names. These helpers let
# the compositor emit a loud startup WARN when a HOMAGE-required font
# is missing, so the operator learns at boot rather than noticing a
# wrong-looking livestream.
# ---------------------------------------------------------------------------


# Fonts required by the HOMAGE BitchX package. Keep in sync with the
# ``primary_font_family`` on ``BITCHX_PACKAGE`` (see
# ``agents/studio_compositor/homage/bitchx.py``).
HOMAGE_REQUIRED_FONTS: tuple[str, ...] = ("Px437 IBM VGA 8x16",)


def has_font(family: str) -> bool:
    """Return True when ``family`` is resolvable via Pango's font map.

    Uses ``PangoCairo.FontMap.get_default()`` to enumerate the available
    families and compares case-insensitively. Returns False when Pango
    is unavailable (CI environments without the typelibs) — callers
    should treat False as "unknown / not available" rather than
    "definitely missing".
    """
    if not _HAS_PANGO:
        return False
    try:
        font_map = PangoCairo.FontMap.get_default()
        if font_map is None:
            return False
        families = font_map.list_families()
    except Exception:
        log.debug("has_font: Pango font map enumeration failed", exc_info=True)
        return False
    wanted = family.strip().casefold()
    for fam in families:
        try:
            name = fam.get_name()
        except Exception:
            continue
        if name and name.strip().casefold() == wanted:
            return True
    return False


def warn_if_missing_homage_fonts() -> None:
    """Emit a loud WARN for each HOMAGE-required font that doesn't resolve.

    Called once at compositor startup. When Pango is unavailable
    (e.g. CI), logs a single info line and returns — the CI path
    renders no-op text anyway, so a missing-font WARN there would be
    noise.
    """
    if not _HAS_PANGO:
        log.info(
            "warn_if_missing_homage_fonts: Pango unavailable; skipping font availability probe"
        )
        return
    for family in HOMAGE_REQUIRED_FONTS:
        if has_font(family):
            log.info("homage-font-probe: %s=available", family)
        else:
            log.warning(
                "homage-font-probe: %s NOT FOUND via Pango/fontconfig — "
                "BitchX surfaces will fall back to DejaVu Sans Mono. "
                "Install the TTF (e.g. /usr/share/fonts/TTF/Px437_IBM_VGA_8x16.ttf) "
                "and restart the compositor.",
                family,
            )
