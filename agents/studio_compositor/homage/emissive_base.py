"""Shared HARDM-style emissive rendering primitives for HOMAGE wards.

Generalises the pointillism / shimmer / halo pattern from
``hardm_source.py:621-739`` into a reusable helper module. Phase A1 of
the homage-completion plan (``docs/superpowers/plans/2026-04-19-homage-
completion-plan.md`` §2). Consumed by Phase A2/A3/A4 ward rewrites.

Design goals:

- **Points of light, not boxes.** Every primitive renders an emissive
  radial-gradient surface: a precise centre dot, a diffuse halo, and an
  optional outer glow that bleeds faintly into neighbours. No flat
  rectangles with text labels.
- **Shimmer without flicker.** ``paint_breathing_alpha`` modulates alpha
  with a per-element phase so surfaces read as "never totally stable"
  without losing grid structure. The angular frequency is slow enough
  (~0.1-0.4 Hz range) to read as shimmer, not strobe.
- **Stance-indexed rhythms.** ``STANCE_HZ`` gives every ward a single
  place to look up pulse rate for the active director stance.
- **Palette discipline.** Callers resolve role RGBAs from the active
  HomagePackage (``pkg.resolve_colour(...)``) and pass them in. This
  module does NOT hardcode colours except ``GRUVBOX_BG0`` for the
  common near-black ground.

All helpers are side-effect-free relative to the input ``cairo.Context``
apart from the drawing they perform. They wrap every stroke in
``cr.save()`` / ``cr.restore()`` so callers' state is preserved.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import cairo


# ── Gruvbox Hard Dark ground ──────────────────────────────────────────────
# Mirrors ``hardm_source.py::_GRUVBOX_BG0``. Near-black (#1d2021) — the
# emissive glow reads as light-on-dark. See ``docs/logos-design-language.md``
# §3 for palette governance.
GRUVBOX_BG0: tuple[float, float, float, float] = (
    0x1D / 255.0,
    0x20 / 255.0,
    0x21 / 255.0,
    1.0,
)


# ── Shimmer / breathing constants ─────────────────────────────────────────
# Nominal baseline+amplitude match the HARDM dot-matrix shimmer
# (``SHIMMER_BASELINE``, ``SHIMMER_AMPLITUDE``). Angular frequency is
# expressed as a *Hz* here rather than rad/s so callers can reason
# about actual cadence; ``paint_breathing_alpha`` converts internally.
BREATHING_BASELINE: float = 0.85
BREATHING_AMPLITUDE: float = 0.15
SHIMMER_HZ_DEFAULT: float = 2.0 / (2.0 * math.pi)  # ≈0.318 Hz, matches HARDM 2.0 rad/s


# ── Emissive halo geometry ────────────────────────────────────────────────
# Defaults are tuned for the HARDM 16 px cell but work on arbitrary
# surfaces — the radii are in absolute pixels and callers can override.
CENTRE_DOT_RADIUS_PX: float = 2.5
HALO_RADIUS_PX: float = 6.5
OUTER_GLOW_RADIUS_PX: float = 9.0
OUTER_GLOW_ALPHA: float = 0.12
HALO_MID_STOP: float = 0.55
HALO_MID_ALPHA_MULT: float = 0.45


# ── Scanline defaults ─────────────────────────────────────────────────────
SCANLINE_EVERY_N_ROWS: int = 4
SCANLINE_ALPHA: float = 0.10


# ── Stance → breathing rate (Hz) ──────────────────────────────────────────
# Wards index into this table by the active director stance so every
# surface pulses at the same rate for the same stance. Spec §A1 lists
# nominal=1.0, seeking=1.6, cautious=0.7, degraded=0.5, critical=2.4.
STANCE_HZ: dict[str, float] = {
    "nominal": 1.0,
    "seeking": 1.6,
    "cautious": 0.7,
    "degraded": 0.5,
    "critical": 2.4,
}


# ── Helpers ──────────────────────────────────────────────────────────────


def paint_breathing_alpha(
    t: float,
    *,
    hz: float = 1.0,
    baseline: float = BREATHING_BASELINE,
    amplitude: float = BREATHING_AMPLITUDE,
    phase: float = 0.0,
) -> float:
    """Return a sinusoidal alpha multiplier clamped to [0, 1].

    ``baseline`` is the mid-alpha (default 0.85); ``amplitude`` is the
    half-range (default 0.15). At ``hz=1.0`` the modulator completes one
    full cycle per second. ``phase`` is a per-element phase offset in
    radians — use it to de-synchronise neighbouring elements so the
    surface doesn't strobe.

    Clamped because callers multiply this into an RGBA alpha directly
    and Cairo will hard-fail on out-of-range alphas in some contexts.
    """
    value = baseline + amplitude * math.sin(2.0 * math.pi * hz * t + phase)
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def paint_emissive_bg(
    cr: cairo.Context,
    w: float,
    h: float,
    *,
    ground_rgba: tuple[float, float, float, float] = GRUVBOX_BG0,
) -> None:
    """Paint a flat-fill ground covering the whole surface.

    Default is the Gruvbox bg0 near-black used by HARDM. Callers that
    need a tinted/gradient ground should use ``paint_bitchx_bg`` from
    ``rendering.py`` instead.
    """
    cr.save()
    cr.set_source_rgba(*ground_rgba)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    cr.restore()


def paint_emissive_point(
    cr: cairo.Context,
    cx: float,
    cy: float,
    role_rgba: tuple[float, float, float, float],
    *,
    t: float,
    phase: float = 0.0,
    baseline_alpha: float = 1.0,
    centre_radius_px: float = CENTRE_DOT_RADIUS_PX,
    halo_radius_px: float = HALO_RADIUS_PX,
    outer_glow_radius_px: float = OUTER_GLOW_RADIUS_PX,
    shimmer_hz: float = SHIMMER_HZ_DEFAULT,
) -> None:
    """Paint one radial-gradient point of light at ``(cx, cy)``.

    Mirrors the HARDM dot-matrix cell: outer glow first (low alpha, wide
    radius), halo second (diffuse body with an alpha falloff), centre
    dot last (crisp point at full signal intensity). Drawing order
    matters — the centre pixel must be the signal colour, not a halo
    blend.

    ``role_rgba`` is the colour sampled from the active HomagePackage
    palette (``pkg.resolve_colour("bright")``, etc.). Its alpha is
    multiplied by ``baseline_alpha`` and the per-frame shimmer so a
    muted role reads as a dim flicker while a bright accent burns hot.

    ``phase`` is the per-element shimmer phase — pass something
    reproducible (e.g. ``row * 0.31 + col * 0.17``) so neighbours
    de-synchronise but the ward re-renders deterministically.
    """
    import cairo as _c

    r, g, b, a = role_rgba
    shimmer = paint_breathing_alpha(
        t,
        hz=shimmer_hz,
        baseline=BREATHING_BASELINE,
        amplitude=BREATHING_AMPLITUDE,
        phase=phase,
    )
    sr = r * shimmer
    sg = g * shimmer
    sb = b * shimmer
    cell_alpha = a * baseline_alpha

    # Outer glow — low-alpha bleed into neighbours.
    if outer_glow_radius_px > 0.0:
        cr.save()
        outer = _c.RadialGradient(cx, cy, 0.0, cx, cy, outer_glow_radius_px)
        outer.add_color_stop_rgba(0.0, sr, sg, sb, OUTER_GLOW_ALPHA * cell_alpha)
        outer.add_color_stop_rgba(1.0, sr, sg, sb, 0.0)
        cr.set_source(outer)
        cr.arc(cx, cy, outer_glow_radius_px, 0.0, 2.0 * math.pi)
        cr.fill()
        cr.restore()

    # Halo — the diffuse body, alpha falloff.
    if halo_radius_px > 0.0:
        cr.save()
        halo = _c.RadialGradient(cx, cy, 0.0, cx, cy, halo_radius_px)
        halo.add_color_stop_rgba(0.0, sr, sg, sb, cell_alpha)
        halo.add_color_stop_rgba(HALO_MID_STOP, sr, sg, sb, cell_alpha * HALO_MID_ALPHA_MULT)
        halo.add_color_stop_rgba(1.0, sr, sg, sb, 0.0)
        cr.set_source(halo)
        cr.arc(cx, cy, halo_radius_px, 0.0, 2.0 * math.pi)
        cr.fill()
        cr.restore()

    # Centre dot — drawn last so the sampled centre pixel is the signal
    # colour at full intensity, not a halo blend.
    if centre_radius_px > 0.0:
        cr.save()
        cr.set_source_rgba(sr, sg, sb, cell_alpha)
        cr.arc(cx, cy, centre_radius_px, 0.0, 2.0 * math.pi)
        cr.fill()
        cr.restore()


def paint_emissive_glyph(
    cr: cairo.Context,
    x: float,
    y: float,
    glyph: str,
    font_size: float,
    role_rgba: tuple[float, float, float, float],
    *,
    t: float,
    phase: float = 0.0,
    baseline_alpha: float = 1.0,
    font_family: str = "Px437 IBM VGA 8x16",
    shimmer_hz: float = SHIMMER_HZ_DEFAULT,
    halo_radius_px: float = HALO_RADIUS_PX,
) -> None:
    """Render a CP437 glyph as an emissive point.

    The glyph is rendered with an emissive halo underneath and the crisp
    text pass on top, so the character reads as a point-of-light rather
    than a flat-fill label. Used for chevron line-start markers, bracket
    characters, and single-char mnemonics in the hothouse wards.

    ``(x, y)`` is the Cairo text origin (baseline-left) as per
    ``cr.move_to``. ``font_size`` is in Cairo user units. The glyph's
    geometric centre is approximated as ``(x + font_size/2, y - font_size/2)``
    — good enough for the halo, and callers rarely need sub-pixel
    precision here.

    ``font_family`` defaults to the Phase A5 typography foundation. If
    the font is missing, Cairo falls back gracefully.
    """
    import cairo as _c

    r, g, b, a = role_rgba
    shimmer = paint_breathing_alpha(
        t,
        hz=shimmer_hz,
        baseline=BREATHING_BASELINE,
        amplitude=BREATHING_AMPLITUDE,
        phase=phase,
    )
    sr = r * shimmer
    sg = g * shimmer
    sb = b * shimmer
    cell_alpha = a * baseline_alpha

    # Halo under the glyph centre.
    cx = x + font_size * 0.5
    cy = y - font_size * 0.5
    if halo_radius_px > 0.0:
        cr.save()
        halo = _c.RadialGradient(cx, cy, 0.0, cx, cy, halo_radius_px)
        halo.add_color_stop_rgba(0.0, sr, sg, sb, cell_alpha * HALO_MID_ALPHA_MULT)
        halo.add_color_stop_rgba(1.0, sr, sg, sb, 0.0)
        cr.set_source(halo)
        cr.arc(cx, cy, halo_radius_px, 0.0, 2.0 * math.pi)
        cr.fill()
        cr.restore()

    # Glyph text pass.
    cr.save()
    cr.select_font_face(font_family, _c.FONT_SLANT_NORMAL, _c.FONT_WEIGHT_BOLD)
    cr.set_font_size(font_size)
    cr.set_source_rgba(sr, sg, sb, cell_alpha)
    cr.move_to(x, y)
    cr.show_text(glyph)
    cr.restore()


def paint_emissive_stroke(
    cr: cairo.Context,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    role_rgba: tuple[float, float, float, float],
    *,
    t: float,
    phase: float = 0.0,
    baseline_alpha: float = 1.0,
    width_px: float = 2.0,
    glow_width_mult: float = 2.4,
    glow_alpha_mult: float = 0.35,
    shimmer_hz: float = SHIMMER_HZ_DEFAULT,
) -> None:
    """Emissive line stroke from ``(x0, y0)`` to ``(x1, y1)``.

    Paints a wide low-alpha glow stroke first, then the crisp inner
    stroke on top, giving the line the same "point of light" quality as
    ``paint_emissive_point`` — the beam has a halo, not a hard edge.

    Used by token-pole limbs, pressure-gauge cells, and the
    recruitment-candidate bar renderings in A2/A3/A4.
    """
    import cairo as _c

    r, g, b, a = role_rgba
    shimmer = paint_breathing_alpha(
        t,
        hz=shimmer_hz,
        baseline=BREATHING_BASELINE,
        amplitude=BREATHING_AMPLITUDE,
        phase=phase,
    )
    sr = r * shimmer
    sg = g * shimmer
    sb = b * shimmer
    cell_alpha = a * baseline_alpha

    # Outer glow stroke.
    if glow_width_mult > 1.0:
        cr.save()
        cr.set_source_rgba(sr, sg, sb, cell_alpha * glow_alpha_mult)
        cr.set_line_width(width_px * glow_width_mult)
        cr.set_line_cap(_c.LINE_CAP_ROUND)
        cr.move_to(x0, y0)
        cr.line_to(x1, y1)
        cr.stroke()
        cr.restore()

    # Inner crisp stroke.
    cr.save()
    cr.set_source_rgba(sr, sg, sb, cell_alpha)
    cr.set_line_width(width_px)
    cr.set_line_cap(_c.LINE_CAP_ROUND)
    cr.move_to(x0, y0)
    cr.line_to(x1, y1)
    cr.stroke()
    cr.restore()


def paint_scanlines(
    cr: cairo.Context,
    w: float,
    h: float,
    *,
    role_rgba: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
    every_n_rows: int = SCANLINE_EVERY_N_ROWS,
    alpha: float = SCANLINE_ALPHA,
    row_height_px: float = 16.0,
) -> None:
    """Paint faint horizontal scanlines — CRT raster hint.

    Every ``every_n_rows`` rows of ``row_height_px`` pixels, draw a 1 px
    horizontal line at the given low alpha. Generalised from the HARDM
    scanline pass. ``role_rgba``'s RGB is used; its alpha is overridden
    by the ``alpha`` kwarg so callers can pass a palette role directly
    without having to clone it.
    """
    r, g, b, _ = role_rgba
    cr.save()
    cr.set_source_rgba(r, g, b, alpha)
    row = 0
    while row < int(h // max(1.0, row_height_px)):
        y = row * row_height_px + row_height_px / 2.0
        cr.rectangle(0, y, w, 1.0)
        cr.fill()
        row += every_n_rows
    cr.restore()


def stance_hz(stance: str, *, fallback: float = 1.0) -> float:
    """Return the breathing frequency (Hz) for a director stance.

    Unknown stances fall through to ``fallback`` (nominal rate). Used
    by every ward's render tick so pulse cadence is package-invariant
    and governed from one table.
    """
    return STANCE_HZ.get(stance, fallback)


__all__ = [
    "BREATHING_AMPLITUDE",
    "BREATHING_BASELINE",
    "CENTRE_DOT_RADIUS_PX",
    "GRUVBOX_BG0",
    "HALO_MID_ALPHA_MULT",
    "HALO_MID_STOP",
    "HALO_RADIUS_PX",
    "OUTER_GLOW_ALPHA",
    "OUTER_GLOW_RADIUS_PX",
    "SCANLINE_ALPHA",
    "SCANLINE_EVERY_N_ROWS",
    "SHIMMER_HZ_DEFAULT",
    "STANCE_HZ",
    "paint_breathing_alpha",
    "paint_emissive_bg",
    "paint_emissive_glyph",
    "paint_emissive_point",
    "paint_emissive_stroke",
    "paint_scanlines",
    "stance_hz",
]
