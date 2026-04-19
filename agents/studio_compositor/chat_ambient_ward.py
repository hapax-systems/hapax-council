"""ChatAmbientWard — BitchX-grammar aggregate chat surface (task #123).

Replaces the static :class:`ChatKeywordLegendCairoSource` with a
dynamic, aggregate-only surface: a single row of 3–4 BitchX-grammar
cells that render the current chat "temperature" of the room —
participation count, research-keyword activity (+v), citation activity
(+H), and a CP437 rate gauge — **never individual messages, handles, or
text**.

Spec: ``docs/superpowers/specs/2026-04-18-chat-ambient-ward-design.md``

Redaction invariant (axiom ``it-irreversible-broadcast``, T0):
    The ward accepts ONLY integer/float counter values via its state
    dict. Message bodies, author handles, derived snippets, and hashes
    thereof NEVER reach ``render_content()``. The type guard in
    :meth:`ChatAmbientWard._coerce_counters` rejects string values at
    runtime so a programming error upstream (e.g. wiring in a raw
    ``ChatMessage`` state) becomes a ``TypeError`` at construction /
    tick, not a broadcast leak.

Cell layout (left → right), all in BitchX grammar:
    1. ``[Users(#hapax:1/N)]`` — N = ``unique_t4_plus_authors_60s``
       (operator is row 1; N counts all non-operator T4+ participants).
    2. ``[Mode +v +H]`` — +v intensity ∝ ``t5_rate_per_min`` (6/min
       saturates, palette role ``accent_green`` above 0.5/min, muted
       below); +H intensity ∝ ``t6_rate_per_min`` (3/min saturates,
       palette role ``accent_cyan`` above 0.5/min, muted below).
    3. CP437 block-char rate gauge — log-scaled
       ``t4_plus_rate_per_min`` across up to 8 cells using ``░▒▓█``.
    4. Conditional engagement cell — ``[quiet]`` (muted) when
       ``audience_engagement < 0.15``, ``[active]`` (bright) when
       ``> 0.85``, otherwise omitted.

Palette + typography come from ``get_active_package()``. No hardcoded
hex; the consent-safe palette variant flattens identity colours to
muted grey automatically per BITCHX_CONSENT_SAFE_PACKAGE when the
consent gate flips the layout.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, Final

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.homage_package import HomagePackage

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


# Counter state keys the ward consumes. Stable names (match ChatSignals
# field names). The ward asserts every value is int|float at ingest.
_COUNTER_KEYS: Final = (
    "t4_plus_rate_per_min",
    "unique_t4_plus_authors_60s",
    "t5_rate_per_min",
    "t6_rate_per_min",
    "message_rate_per_min",
    "audience_engagement",
)

# BitchX +v saturates at 6 T5/min (IRC-idiom op-indicator threshold).
_T5_SATURATION_RATE: Final = 6.0
# BitchX +H saturates at 3 T6/min (citations are rare; small denominator).
_T6_SATURATION_RATE: Final = 3.0
# Below this T5 rate, +v renders in muted role (present but dim).
_VOICE_ACTIVE_THRESHOLD: Final = 0.5
# Below this T6 rate, +H renders in muted role.
_HOMAGE_ACTIVE_THRESHOLD: Final = 0.5
# Engagement band thresholds (conditional quiet/active cell).
_ENGAGEMENT_QUIET_BELOW: Final = 0.15
_ENGAGEMENT_ACTIVE_ABOVE: Final = 0.85
# Rate gauge: 0–60 msg/min → 0–8 cells, logarithmic.
_GAUGE_CELL_COUNT: Final = 8
_GAUGE_RATE_CAP: Final = 60.0
# CP437 block glyphs ordered lightest → darkest for gauge fill.
_GAUGE_GLYPHS: Final = ("░", "▒", "▓", "█")


def _fallback_package() -> HomagePackage:
    """Compiled-in BitchX package for isolated-test / consent-safe fall-through."""
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _font_description(size: int, *, bold: bool = False) -> str:
    """Return a Pango font-description string for the active package.

    Phase A5 (homage-completion-plan §3.3): routes text through
    :func:`text_render.render_text` (Pango) so ``Px437 IBM VGA 8x16``
    resolves via fontconfig instead of silently falling back to DejaVu
    Sans Mono under Cairo's toy ``select_font_face`` path.
    """
    pkg = get_active_package() or _fallback_package()
    weight = " Bold" if bold else ""
    return f"{pkg.typography.primary_font_family}{weight} {int(size)}"


def _draw_pango(
    cr: cairo.Context,
    text: str,
    x: float,
    y: float,
    *,
    font_description: str,
    color_rgba: tuple[float, float, float, float],
) -> float:
    """Render ``text`` at ``(x, y)`` via Pango. Return advance width."""
    from agents.studio_compositor.text_render import (
        TextStyle,
        measure_text,
        render_text,
    )

    style = TextStyle(
        text=text,
        font_description=font_description,
        color_rgba=color_rgba,
    )
    w, h = measure_text(cr, style)
    render_text(cr, style, x=x, y=y - h)
    return float(w)


def _paint_flat_bg(cr: cairo.Context, w: float, h: float, pkg: HomagePackage) -> None:
    """Flat CP437-style background — sharp rectangle, no chrome."""
    r, g, b, a = pkg.resolve_colour("background")
    cr.save()
    cr.set_source_rgba(r, g, b, a)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    cr.restore()


def _blend(
    base: tuple[float, float, float, float],
    target: tuple[float, float, float, float],
    weight: float,
) -> tuple[float, float, float, float]:
    """Linear blend of ``base`` → ``target`` by ``weight`` (clamped 0..1)."""
    w = max(0.0, min(1.0, weight))
    return (
        base[0] + (target[0] - base[0]) * w,
        base[1] + (target[1] - base[1]) * w,
        base[2] + (target[2] - base[2]) * w,
        base[3] + (target[3] - base[3]) * w,
    )


def _gauge_glyph_for_fraction(frac: float) -> str:
    """Return a CP437 shade glyph for a fill fraction in [0, 1]."""
    f = max(0.0, min(1.0, frac))
    # Split [0,1] across the four glyph tiers.
    if f <= 0.0:
        return " "
    idx = min(len(_GAUGE_GLYPHS) - 1, int(f * len(_GAUGE_GLYPHS)))
    return _GAUGE_GLYPHS[idx]


def _log_gauge_fraction(rate_per_min: float, *, cap: float = _GAUGE_RATE_CAP) -> float:
    """Map a rate onto [0, 1] logarithmically. rate≥cap → 1.0, rate≤0 → 0.0."""
    if rate_per_min <= 0.0:
        return 0.0
    # log1p ensures rate=0 → 0 and smoothly grows; divide by log1p(cap) to normalise.
    denom = math.log1p(cap)
    if denom <= 0.0:
        return 0.0
    return min(1.0, math.log1p(rate_per_min) / denom)


class ChatAmbientWard(HomageTransitionalSource):
    """Aggregate chat surface — BitchX grammar, no identity leak.

    Constructor + state dict accept **counter values only**. Any string
    value (which could carry an author handle or message text) raises
    :class:`TypeError` immediately. This is the constitutional guard
    on axiom ``it-irreversible-broadcast``.
    """

    def __init__(self, initial_counters: dict[str, float] | None = None) -> None:
        super().__init__(source_id="chat_ambient")
        self._counters: dict[str, float] = {}
        if initial_counters is not None:
            self._counters = self._coerce_counters(initial_counters)

    # ── Type guard ──────────────────────────────────────────────────────

    @staticmethod
    def _coerce_counters(raw: dict[str, Any]) -> dict[str, float]:
        """Narrow ``raw`` to a ``dict[str, float]`` of known counter keys.

        Raises :class:`TypeError` if a value is ``str``, ``bytes``,
        ``bytearray``, or any non-numeric type. ``bool`` is accepted and
        coerced to ``0.0/1.0`` since ``bool`` is a subclass of ``int`` —
        but it is never expected here. Unknown keys are silently
        ignored (forward-compatibility with future ChatSignals fields).
        """
        if not isinstance(raw, dict):
            raise TypeError(f"ChatAmbientWard counters must be a dict, got {type(raw).__name__}")
        out: dict[str, float] = {}
        for key in _COUNTER_KEYS:
            if key not in raw:
                continue
            value = raw[key]
            # Explicitly reject any string-like type — this is the
            # redaction invariant's teeth.
            if isinstance(value, (str, bytes, bytearray)):
                raise TypeError(
                    f"ChatAmbientWard.{key} must be numeric; "
                    f"received {type(value).__name__} (constitutional redaction violation)"
                )
            if not isinstance(value, (int, float)):
                raise TypeError(
                    f"ChatAmbientWard.{key} must be int|float; got {type(value).__name__}"
                )
            out[key] = float(value)
        return out

    def update(self, counters: dict[str, Any]) -> None:
        """Replace the ward's counter state. Validates via ``_coerce_counters``."""
        self._counters = self._coerce_counters(counters)

    @property
    def counters(self) -> dict[str, float]:
        """Return a snapshot of the current counter state (read-only copy)."""
        return dict(self._counters)

    # ── Render ──────────────────────────────────────────────────────────

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Render 3–4 BitchX-grammar cells. State may carry counters.

        ``state`` is the runner-supplied dict (generic); if it contains
        any of :data:`_COUNTER_KEYS`, those values replace the ward's
        internal snapshot for this frame (after :meth:`_coerce_counters`
        validation). This lets the compositor feed live
        :class:`ChatSignals` values without a separate update() call.
        """
        counters = self._counters
        if state:
            # _coerce_counters ignores unknown keys, so state may contain
            # arbitrary runner metadata; only counter keys are adopted.
            filtered: dict[str, Any] = {k: state[k] for k in _COUNTER_KEYS if k in state}
            if filtered:
                counters = self._coerce_counters(filtered)

        pkg = get_active_package() or _fallback_package()
        _paint_flat_bg(cr, float(canvas_w), float(canvas_h), pkg)

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        content = pkg.resolve_colour("terminal_default")
        accent_cyan = pkg.resolve_colour("accent_cyan")
        accent_green = pkg.resolve_colour("accent_green")

        unique_authors = int(counters.get("unique_t4_plus_authors_60s", 0.0))
        t4p_rate = counters.get("t4_plus_rate_per_min", 0.0)
        t5_rate = counters.get("t5_rate_per_min", 0.0)
        t6_rate = counters.get("t6_rate_per_min", 0.0)
        engagement = counters.get("audience_engagement", 0.0)

        font = _font_description(14, bold=True)
        y = canvas_h * 0.55 + 8.0
        x = 8.0

        # »»» line-start marker (muted).
        marker = pkg.grammar.line_start_marker + " "
        x += _draw_pango(cr, marker, x, y, font_description=font, color_rgba=muted)

        # ── Cell 1: [Users(#hapax:1/N)] ────────────────────────────────
        x += _draw_pango(cr, "[Users(", x, y, font_description=font, color_rgba=muted)
        x += _draw_pango(cr, "#hapax", x, y, font_description=font, color_rgba=accent_cyan)
        x += _draw_pango(cr, ":", x, y, font_description=font, color_rgba=muted)
        x += _draw_pango(cr, "1", x, y, font_description=font, color_rgba=bright)
        x += _draw_pango(cr, "/", x, y, font_description=font, color_rgba=muted)
        n_text = str(unique_authors)
        x += _draw_pango(cr, n_text, x, y, font_description=font, color_rgba=bright)
        x += _draw_pango(cr, ")] ", x, y, font_description=font, color_rgba=muted)

        # ── Cell 2: [Mode +v +H] — cadence-aware brightness ────────────
        x += _draw_pango(cr, "[Mode ", x, y, font_description=font, color_rgba=muted)

        # +v: T5 research-keyword rate. Below 0.5/min → muted; above → accent_green blended.
        v_weight = min(1.0, t5_rate / _T5_SATURATION_RATE)
        if t5_rate <= _VOICE_ACTIVE_THRESHOLD:
            v_rgba = muted
        else:
            v_rgba = _blend(muted, accent_green, v_weight)
        x += _draw_pango(cr, "+v", x, y, font_description=font, color_rgba=v_rgba)
        x += _draw_pango(cr, " ", x, y, font_description=font, color_rgba=muted)

        # +H: T6 citation rate. Same cadence shape, accent_cyan target.
        h_weight = min(1.0, t6_rate / _T6_SATURATION_RATE)
        if t6_rate <= _HOMAGE_ACTIVE_THRESHOLD:
            h_rgba = muted
        else:
            h_rgba = _blend(muted, accent_cyan, h_weight)
        x += _draw_pango(cr, "+H", x, y, font_description=font, color_rgba=h_rgba)
        x += _draw_pango(cr, "] ", x, y, font_description=font, color_rgba=muted)

        # ── Cell 3: CP437 rate gauge ───────────────────────────────────
        x += _draw_pango(cr, "[", x, y, font_description=font, color_rgba=muted)

        gauge_frac = _log_gauge_fraction(t4p_rate)
        lit_cells_float = gauge_frac * _GAUGE_CELL_COUNT
        full_cells = int(lit_cells_float)
        partial_frac = lit_cells_float - full_cells
        gauge_text = _GAUGE_GLYPHS[-1] * full_cells
        if full_cells < _GAUGE_CELL_COUNT and partial_frac > 0.0:
            gauge_text += _gauge_glyph_for_fraction(partial_frac)
        # Pad with spaces so the cell width is stable frame-to-frame.
        gauge_text = gauge_text.ljust(_GAUGE_CELL_COUNT)
        x += _draw_pango(cr, gauge_text, x, y, font_description=font, color_rgba=content)

        x += _draw_pango(cr, "] ", x, y, font_description=font, color_rgba=muted)

        # ── Cell 4 (conditional): [quiet] / [active] ───────────────────
        if engagement < _ENGAGEMENT_QUIET_BELOW:
            _draw_pango(cr, "[quiet]", x, y, font_description=font, color_rgba=muted)
        elif engagement > _ENGAGEMENT_ACTIVE_ABOVE:
            x += _draw_pango(cr, "[", x, y, font_description=font, color_rgba=muted)
            x += _draw_pango(cr, "active", x, y, font_description=font, color_rgba=bright)
            _draw_pango(cr, "]", x, y, font_description=font, color_rgba=muted)


__all__ = ["ChatAmbientWard"]
