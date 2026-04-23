"""Shared Cairo rendering helpers used by every HOMAGE-migrated ward.

HOMAGE spec §4.2 grammar rules are implemented uniformly via this
module so each ward's ``render_content`` doesn't redo the boilerplate.
The helpers all take the active :class:`HomagePackage` as an argument
and resolve palette / typography from there — no hardcoded hex.
"""

from __future__ import annotations

import logging
import time
import warnings
from typing import TYPE_CHECKING

from agents.studio_compositor.homage import get_active_package
from shared.homage_package import HomagePackage

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


def active_package() -> HomagePackage:
    """Return the active package, or the BitchX fallback when registry
    resolution fails (consent-safe path, tests in isolation)."""
    pkg = get_active_package()
    if pkg is not None:
        return pkg
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def select_bitchx_font_pango(
    cr: cairo.Context,  # noqa: ARG001 — kept for symmetry with old API; Pango doesn't need it
    size: int,
    *,
    bold: bool = False,
) -> str:
    """Return a Pango-compatible font-description string for the active package.

    Phase A5 (homage-completion-plan §3.3): the old
    :func:`select_bitchx_font` invoked Cairo's toy ``select_font_face``
    API, which does not consult fontconfig the way Pango does — it
    silently falls back to DejaVu Sans Mono for unknown family names.
    The fix: every HOMAGE ward builds a Pango ``font_description``
    string from the active package's ``primary_font_family`` and feeds
    it through :func:`text_render.render_text` (which uses
    PangoCairo + ``layout.set_font_description``). Pango consults
    fontconfig, so ``"Px437 IBM VGA 8x16"`` resolves correctly.

    The ``cr`` parameter is accepted (and unused) so call sites can
    swap ``select_bitchx_font(cr, …)`` → ``select_bitchx_font_pango(cr, …)``
    as a mechanical replacement.
    """
    pkg = active_package()
    weight = " Bold" if bold else ""
    return f"{pkg.typography.primary_font_family}{weight} {int(size)}"


def select_bitchx_font(cr: cairo.Context, size: int, *, bold: bool = False) -> None:
    """Deprecated: use :func:`select_bitchx_font_pango` + text_render instead.

    The Cairo toy-API path does not consult fontconfig so unknown
    families (Px437 IBM VGA 8x16) silently degrade to DejaVu Sans Mono.
    Retained as a shim only for legacy callers not yet migrated off
    ``cr.show_text``. New code MUST construct a
    :class:`text_render.TextStyle` with ``font_description`` sourced
    from :func:`select_bitchx_font_pango` and call
    :func:`text_render.render_text`.
    """
    warnings.warn(
        "select_bitchx_font is deprecated; use select_bitchx_font_pango + "
        "text_render.render_text. Cairo toy API does not consult fontconfig.",
        DeprecationWarning,
        stacklevel=2,
    )
    import cairo as _c

    pkg = active_package()
    cr.select_font_face(
        pkg.typography.primary_font_family,
        _c.FONT_SLANT_NORMAL,
        _c.FONT_WEIGHT_BOLD if bold else _c.FONT_WEIGHT_NORMAL,
    )
    cr.set_font_size(size)


def paint_bitchx_bg(
    cr: cairo.Context,
    w: float,
    h: float,
    pkg: HomagePackage,
    *,
    border_rgba: tuple[float, float, float, float] | None = None,
    ward_id: str | None = None,
) -> None:
    """Paint the ward's background — domain-tinted gradient when ward_id given.

    Cascade-delta (2026-04-18): the flat-fill path was the aesthetic
    culprit the operator flagged ("looks like total garbage", "static
    techno overlay with dumb containers"). When ``ward_id`` is supplied
    we paint:

    1. A vertical gradient from ``background`` at the top to a 12%-lifted
       blend of ``background`` and the ward's per-domain accent at the
       bottom. No pure black — the ward feels tinted without losing
       legibility.
    2. A 2 px accent side-bar on the left edge in the ward's domain
       colour (music → magenta, token → cyan, presence → yellow,
       communication → green, cognition → cyan, director → yellow).
       Gives every ward an identity colour at a glance without hand-
       authoring headers.

    Legacy callers that don't pass ``ward_id`` get the package's
    background role as a flat fill — prior behaviour preserved.
    Sharp corners (spec §5.5 refuses rounded-corners).

    2026-04-23 operator directive: "all containers should have zero
    opacity and rely on text size and quality and smart contrasting
    alone to deal with visibility." Splattribution is the reference —
    text with outline, no container chrome. This function is a no-op;
    all 15 call sites across ``legibility_sources``, ``hothouse_sources``,
    and ``emissive_base`` inherit zero-chrome rendering. Signature
    preserved for back-compat.
    """
    _ = (cr, w, h, pkg, border_rgba, ward_id)  # params retained; unused


# WardDomain → accent colour role. Each HOMAGE ward's domain (per
# ``shared/ward_fx_bus.py::WardDomain``) is mapped to one of the active
# HomagePackage's accent roles so the side-bar + gradient carry the
# ward's identity. Unknown domains fall through to ``accent_cyan``.
_DOMAIN_ACCENT_ROLE: dict[str, str] = {
    "communication": "accent_green",
    "presence": "accent_yellow",
    "token": "accent_cyan",
    "music": "accent_magenta",
    "cognition": "accent_cyan",
    "director": "accent_yellow",
    "perception": "accent_green",
}


def _domain_for_ward(ward_id: str) -> str:
    """Return the WardDomain for ``ward_id`` or a safe default.

    Lazy import so the HOMAGE package bootstrap doesn't pull
    ``ward_fx_bus`` prematurely.
    """
    try:
        from agents.studio_compositor.ward_fx_mapping import domain_for_ward

        return domain_for_ward(ward_id)
    except Exception:
        return "perception"


def _domain_accent(pkg: HomagePackage, ward_id: str) -> tuple[float, float, float, float]:
    """Resolve the per-domain accent colour for the ward."""
    role = _DOMAIN_ACCENT_ROLE.get(_domain_for_ward(ward_id), "accent_cyan")
    try:
        return pkg.resolve_colour(role)
    except Exception:
        try:
            return pkg.resolve_colour("bright")
        except Exception:
            return (0.7, 0.85, 1.0, 1.0)


def irc_line_start(cr: cairo.Context, x: float, y: float, pkg: HomagePackage) -> float:
    """Draw the package's line-start marker at (x, y) in the muted role.

    Returns the updated x-cursor position.

    Phase A5: uses :func:`text_render.render_text` (Pango) so the
    marker resolves Px437 IBM VGA 8x16 through fontconfig, not Cairo's
    toy font selector.
    """
    from agents.studio_compositor.text_render import TextStyle, measure_text, render_text

    marker = pkg.grammar.line_start_marker + " "
    font_desc = select_bitchx_font_pango(cr, 13, bold=False)
    style = TextStyle(
        text=marker,
        font_description=font_desc,
        color_rgba=pkg.resolve_colour(pkg.grammar.punctuation_colour_role),
    )
    w, _h = measure_text(cr, style)
    render_text(cr, style, x=x, y=y)
    return x + w


def paint_bitchx_header(
    cr: cairo.Context,
    ward_label: str,
    pkg: HomagePackage,
    *,
    accent_role: str = "accent_cyan",
    y: float = 14.0,
    x: float = 8.0,
    font_size: int = 11,
) -> None:
    """Draw the canonical BitchX ward header: ``»»» <label>`` with the
    line-start marker in muted and the label in the named accent role.

    Every ward's ``render_content`` should call this before drawing body
    text so the surface reads as mIRC-contract composition rather than a
    flat techno overlay. Keep ``ward_label`` short (1–3 words) so it
    doesn't collide with body content at small surface widths.

    Phase A5: routes text through Pango (via
    :func:`text_render.render_text`) so Px437 IBM VGA 8x16 resolves via
    fontconfig rather than silently falling back to DejaVu Sans Mono.
    """
    from agents.studio_compositor.text_render import TextStyle, measure_text, render_text

    muted = pkg.resolve_colour(pkg.grammar.punctuation_colour_role)
    try:
        accent = pkg.resolve_colour(accent_role)
    except Exception:
        accent = pkg.resolve_colour("bright")
    font_desc = select_bitchx_font_pango(cr, font_size, bold=True)
    marker = pkg.grammar.line_start_marker + " "
    marker_style = TextStyle(
        text=marker,
        font_description=font_desc,
        color_rgba=muted,
    )
    w_marker, _ = measure_text(cr, marker_style)
    render_text(cr, marker_style, x=x, y=y)
    label_style = TextStyle(
        text=ward_label,
        font_description=font_desc,
        color_rgba=accent,
    )
    render_text(cr, label_style, x=x + w_marker, y=y)


def paint_emphasis_border(
    cr: cairo.Context,
    w: float,
    h: float,
    pkg: HomagePackage,
    *,
    ward_id: str,
    t: float,
    accent_role: str = "accent_cyan",
) -> None:
    """Draw a ward-properties-driven glow border on top of existing content.

    Reads the ward's ``glow_radius_px`` + ``border_pulse_hz`` +
    ``border_color_rgba`` from ``ward_properties`` (200ms-cached, hot-
    path-safe). When ``glow_radius_px`` is non-zero, paints a stroked
    rectangle whose line width modulates with
    ``border_pulse_hz`` so the emphasized ward reads as "actively
    manipulated" not "statically bright".

    No-op when the ward has no active emphasis (glow_radius_px == 0).
    Cairo failures are swallowed — visual polish must never break a
    ward's render path.

    2026-04-23 operator directive: zero container opacity. The outer
    glow halo and inner border stroke were the two remaining chrome
    primitives emphasizing an "active" ward. Both retired; emphasis
    now happens via content-level means (text weight, crop shift,
    eventually parallax/fronting per the video-container epic).
    Signature preserved for back-compat.
    """
    _ = (cr, w, h, pkg, ward_id, t, accent_role)  # params retained; unused


def apply_scale_bump(cr: cairo.Context, w: float, h: float, ward_id: str) -> None:
    """Apply the ward's ``scale_bump_pct`` as a uniform cairo.scale()
    transform, centered on the ward's canvas. No-op at bump == 0.

    Must be called AFTER any positioning translate() but BEFORE
    content drawing, because the transform is multiplicative on the
    current matrix. The caller should wrap this + its draw calls in
    a cr.save()/cr.restore() block.
    """
    try:
        from agents.studio_compositor.ward_properties import resolve_ward_properties

        props = resolve_ward_properties(ward_id)
    except Exception:
        return
    bump = float(getattr(props, "scale_bump_pct", 0.0) or 0.0)
    if abs(bump) < 0.01:
        return
    scale = 1.0 + bump
    cx, cy = w * 0.5, h * 0.5
    try:
        cr.translate(cx, cy)
        cr.scale(scale, scale)
        cr.translate(-cx, -cy)
    except Exception:
        return


def wall_clock_now() -> float:
    """Shared monotonic-ish clock helper for emphasis animation. Using
    ``time.time()`` intentionally so the animation reads the same phase
    across every Cairo source in the same render tick."""
    return time.time()


__all__ = [
    "active_package",
    "apply_scale_bump",
    "irc_line_start",
    "paint_bitchx_bg",
    "paint_bitchx_header",
    "paint_emphasis_border",
    "select_bitchx_font",
    "select_bitchx_font_pango",
    "wall_clock_now",
]
