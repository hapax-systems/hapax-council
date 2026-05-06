"""Legibility Cairo sources — on-frame authorship indicators.

Phase 4 of the volitional-grounded-director epic (PR #1017, spec §3.5).
Phase 4 of the HOMAGE epic (spec §4.10) migrated these sources to
:class:`HomageTransitionalSource`. Phase A5 swapped Cairo's toy
``cr.show_text`` calls for Pango via :mod:`text_render` so Px437 IBM
VGA 8x16 resolves through fontconfig.

**Phase A3 (this revision): emissive rewrite.** Every text path renders
through the shared :mod:`homage.emissive_base` primitives — structural
chars (chevrons, brackets, stars) via :func:`paint_emissive_glyph`
centre-dot + halo, and narrative text (gloss, meaning, signal names)
via :func:`text_render.render_text` for Px437 legibility. Structural
state changes (activity flip, stance flip) paint a 200 ms
inverse-flash across the ward; grounding ticker entries slide in; and
the stance label pulses at the stance-indexed Hz rate from
:data:`STANCE_HZ`. The four sources are:

- :class:`ActivityHeaderCairoSource` — ``>>> [ACTIVITY | gloss]``
  with optional ``:: [ROTATION:<mode>]`` when rotation is non-default
- :class:`StanceIndicatorCairoSource` — ``[+H <stance>]`` with pulse
- :class:`GroundingProvenanceTickerCairoSource` — ``* <signal>`` rows
  with slide-in / breathing empty state
- :class:`ChatKeywordLegendCairoSource` — legacy alias kept for
  Phase 10 backcompat (B5 binds ``chat_ambient`` to ``ChatAmbientWard``
  in ``default.json``, so this class renders only if a legacy layout
  is used)

Every source reads ``/dev/shm/hapax-director/narrative-state.json`` or
``~/hapax-state/stream-experiment/director-intent.jsonl``. Readers are
wrapped in try/except; absent files render neutral/empty states.

Palette comes from the active HomagePackage (``get_active_package()``)
via role resolution — no hardcoded hex.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.emissive_base import (
    STANCE_HZ,
    paint_breathing_alpha,
    paint_emissive_glyph,
    paint_emissive_point,
    paint_scanlines,
)
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.homage_package import HomagePackage

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

_NARRATIVE_STATE = Path("/dev/shm/hapax-director/narrative-state.json")
_DIRECTOR_INTENT_JSONL = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
)

_BRIGHT_FIELD_OUTLINE_OFFSETS: tuple[tuple[int, int], ...] = (
    (-3, 0),
    (3, 0),
    (0, -3),
    (0, 3),
    (-2, -2),
    (2, -2),
    (-2, 2),
    (2, 2),
)


# Per-stream-mode accent hint. Kept from Phase F6 for the optional border
# under BitchX grammar (BitchX packages do not refuse this — the line is
# a CP437-thin rule, not a rounded outline).
_STREAM_MODE_COLOR: dict[str, tuple[float, float, float, float]] = {
    "private": (0.522, 0.600, 0.702, 0.9),
    "public": (0.596, 0.591, 0.102, 0.9),
    "public_research": (0.522, 0.601, 0.000, 0.9),
    "fortress": (0.796, 0.294, 0.086, 0.9),
    "off": (0.500, 0.500, 0.500, 0.7),
}


def _stream_mode_accent() -> tuple[float, float, float, float] | None:
    try:
        from shared.stream_mode import get_stream_mode

        mode = str(get_stream_mode() or "off")
    except Exception:
        mode = "off"
    return _STREAM_MODE_COLOR.get(mode)


# Per-stance palette role mapping — BitchX grammar rendering maps a
# narrative stance to one of the package's accent roles.
_STANCE_ROLE: dict[str, str] = {
    "nominal": "accent_green",
    "seeking": "accent_cyan",
    "cautious": "accent_yellow",
    "degraded": "accent_yellow",
    "critical": "accent_red",
}


# Rotation-mode → colour role for the optional ``[ROTATION:<mode>]`` token
# appended to the activity header. Plan §A3 spec tokens plus the
# choreographer's existing enum space. Unknown values fall through to
# ``muted``.
_ROTATION_MODE_ROLE: dict[str, str] = {
    # Plan §1.3 tokens
    "steady": "muted",
    "deliberate": "accent_cyan",
    "rapid": "accent_yellow",
    "burst": "accent_red",
    # Choreographer legacy tokens
    "sequential": "muted",
    "paused": "muted",
    "random": "accent_cyan",
    "weighted_by_salience": "accent_yellow",
}

# Rotation modes that are "default" and therefore do NOT trigger the
# ``:: [ROTATION:<mode>]`` suffix on the activity header.
_ROTATION_MODE_DEFAULT: frozenset[str] = frozenset({"steady", "weighted_by_salience"})


# Inverse-flash envelope — triggered by activity / stance change. Plan §A3
# ("mode-change vocab"). lssh-001 (operator 2026-04-21: "way too much
# BLINKING for the homage wards") softened the envelope along four axes:
#
#   1. Peak alpha 0.45 → 0.10 (4.5× softer at the visible-most moment).
#   2. Duration 200 ms → 600 ms (so the change reads as a deliberate
#      pulse rather than a snap).
#   3. Linear decay → sine bell envelope (smooth ramp-up + smooth
#      ramp-down; lssh-001 Phase A used cosine ease-out which fixed
#      the decay tail but left the START as a step from off → peak,
#      producing the blink the operator complained about).
#   4. Bound the peak slope (the operator's blink-threshold heuristic
#      is "no luminance change > 40 % faster than once every 500 ms";
#      sine bell peak slope = peak · π / duration; with these values
#      ≈ 0.10 · π / 0.6 ≈ 0.52 per second = 0.26 per 500 ms, under
#      the 40 % bar).
#
# The pulse still carries the same information signal (activity /
# stance just changed) — it just doesn't strobe. Regression-pinned by
# both the unit-test math at ``_flash_alpha`` AND the rendered-frame
# luminance harness at ``tests/studio_compositor/test_no_blink.py``
# (Phase B of lssh-001).
_INVERSE_FLASH_DURATION_S: float = 0.600
_INVERSE_FLASH_PEAK_ALPHA: float = 0.10

# Breathing alpha frequency for the ungrounded ticker state.
_UNGROUNDED_BREATH_HZ: float = 0.3


def _read_narrative_state() -> dict:
    """Return the narrative-state JSON as a dict, or {} on any failure.

    Validates the JSON root is a mapping. A writer producing valid JSON
    with a non-dict root (``null``, list, string, number) previously
    propagated AttributeError out of ``ns.get("activity")`` in the
    Cairo render callback at line 398, crashing the ActivityHeader /
    StanceIndicator / GroundingProvenanceTicker / ChatKeywordLegend
    sources. Mirrors the isinstance pattern already in
    :func:`_read_rotation_mode` below.
    """
    try:
        if _NARRATIVE_STATE.exists():
            data = json.loads(_NARRATIVE_STATE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            log.debug(
                "narrative-state root is %s, expected mapping",
                type(data).__name__,
            )
    except Exception:
        log.debug("narrative-state read failed", exc_info=True)
    return {}


def _read_latest_intent() -> dict:
    """Return the most recent director-intent JSONL entry as a dict.

    Same isinstance contract as :func:`_read_narrative_state` — the
    last line of the JSONL tail is parsed and validated, with non-dict
    values rejected so the callsite's ``intent.get(...)`` cannot raise
    AttributeError into the Cairo render callback.
    """
    try:
        if _DIRECTOR_INTENT_JSONL.exists():
            size = _DIRECTOR_INTENT_JSONL.stat().st_size
            with _DIRECTOR_INTENT_JSONL.open("rb") as fh:
                fh.seek(max(0, size - 4096))
                tail = fh.read().decode("utf-8", errors="ignore")
            lines = [line for line in tail.splitlines() if line.strip()]
            if lines:
                data = json.loads(lines[-1])
                if isinstance(data, dict):
                    return data
                log.debug(
                    "director-intent tail root is %s, expected mapping",
                    type(data).__name__,
                )
    except Exception:
        log.debug("director-intent tail failed", exc_info=True)
    return {}


def _read_rotation_mode() -> str | None:
    """Read the active ``homage_rotation_mode`` from the intent files.

    Mirrors :class:`HomageChoreographer._read_rotation_mode` for the
    ward's purposes. Returns ``None`` on any failure; callers interpret
    that as "default, don't surface".
    """
    paths: tuple[Path, ...] = (
        Path(
            os.path.expanduser("~/hapax-state/stream-experiment/narrative-structural-intent.json")
        ),
        Path(os.path.expanduser("~/hapax-state/stream-experiment/structural-intent.json")),
    )
    for path in paths:
        try:
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            mode = data.get("homage_rotation_mode")
            if isinstance(mode, str) and mode:
                return mode
        except Exception:
            log.debug("rotation-mode read failed for %s", path, exc_info=True)
    return None


def _bitchx_font_description(size: int, *, bold: bool = False) -> str:
    """Return a Pango font-description string for the active package."""
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


def _fallback_package() -> HomagePackage:
    """Return the compiled-in BitchX package when registry resolution fails."""
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _bright_field_outline(pkg: HomagePackage) -> tuple[float, float, float, float]:
    """Dark package ink used as text outline on bright shader fields."""
    r, g, b, _a = pkg.resolve_colour("background")
    return (r, g, b, 0.95)


def _paint_bitchx_bg(
    cr: cairo.Context,
    w: float,
    h: float,
    pkg: HomagePackage,
    *,
    ward_id: str | None = None,
) -> None:
    """Fill a CP437-style background — sharp corners, no rounded rects.

    2026-04-23 operator directive: zero container opacity. The shared
    primitive and the local stream-mode accent border are both chrome;
    retired. Signature preserved for back-compat with existing callers.
    """
    _ = (cr, w, h, pkg, ward_id)  # params retained; unused


def _paint_inverse_flash(
    cr: cairo.Context,
    w: float,
    h: float,
    rgba: tuple[float, float, float, float],
    *,
    alpha: float,
) -> None:
    """Paint a translucent rectangle covering the ward at ``alpha``.

    2026-04-23 operator directive: zero container opacity. Inverse flash
    was already neutralized in practice (``_flash_alpha`` returns 0.0
    since the no-flashing directive); the rectangle fill itself is also
    retired now so the function cannot reintroduce chrome if a future
    caller passes a non-zero alpha.
    """
    _ = (cr, w, h, rgba, alpha)  # params retained; unused


def _flash_alpha(
    t: float,  # noqa: ARG001 — kept for backward-compat signature
    flash_started_at: float | None,  # noqa: ARG001
) -> float:
    """Return 0.0 always — inverse-flash retired 2026-04-23.

    Operator directive "no flashing of any kind on any of the homage
    wards" retires the inverse-flash bell envelope entirely. Transition
    events (stance change, activity change, preset-family change) now
    signal through non-alpha channels (text content, z-order nudge,
    position change). The ``_paint_inverse_flash`` consumer early-
    returns when alpha is 0.0, so no further callsite changes are
    needed.

    Signature preserved so call-sites that pass ``t`` and the stored
    timestamp keep compiling; the parameters are no-ops.
    """
    return 0.0


def _emissive_structural(
    cr: cairo.Context,
    text: str,
    x: float,
    y: float,
    *,
    role_rgba: tuple[float, float, float, float],
    font_size: float,
    t: float,
    phase_base: float = 0.0,
    shimmer_hz: float = 0.5,
    halo_radius_px: float | None = None,
    outline_rgba: tuple[float, float, float, float] | None = None,
    outline_offsets: tuple[tuple[int, int], ...] = (),
) -> float:
    """Render ``text`` as a run of emissive glyphs + return advance width."""
    from agents.studio_compositor.text_render import TextStyle, measure_text

    style = TextStyle(
        text=text,
        font_description=_bitchx_font_description(int(font_size), bold=True),
        color_rgba=role_rgba,
    )
    total_w, _h = measure_text(cr, style)

    n = max(1, len(text))
    per_cell = float(total_w) / float(n)
    for i, ch in enumerate(text):
        if ch == " ":
            continue
        cx = x + per_cell * i
        phase = phase_base + i * 0.31
        kwargs: dict[str, Any] = {
            "t": t,
            "phase": phase,
            "shimmer_hz": shimmer_hz,
            "outline_rgba": outline_rgba,
            "outline_offsets": outline_offsets,
        }
        if halo_radius_px is not None:
            kwargs["halo_radius_px"] = halo_radius_px
        paint_emissive_glyph(
            cr,
            x=cx,
            y=y,
            glyph=ch,
            font_size=font_size,
            role_rgba=role_rgba,
            **kwargs,
        )
    return float(total_w)


# ── 1. Activity header ────────────────────────────────────────────────────


class ActivityHeaderCairoSource(HomageTransitionalSource):
    """Top-center strip under BitchX grammar.

    Rendered form: ``>>> [ACTIVITY | gloss]`` — chevron marker, brackets,
    and activity token render as emissive point-of-light glyphs. Gloss
    renders via Pango for legibility. On activity change, a 200 ms
    inverse-flash overlays the whole ward. When ``homage_rotation_mode``
    is non-default, append ``:: [ROTATION:<mode>]`` with the rotation
    token coloured by mode.
    """

    def __init__(self) -> None:
        super().__init__(source_id="activity_header")
        self._last_activity: str | None = None
        self._activity_flash_started_at: float | None = None

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        ns = _read_narrative_state()
        intent = _read_latest_intent()
        activity = str(ns.get("activity") or intent.get("activity") or "—").upper()
        # Narrative-leakage audit (operator screenshot 2026-04-22): the
        # ``gloss = best_impingement.narrative[:48]`` line previously
        # rendered the LLM's directorial narrative ("Cut to the wide
        # shot of the room") inline as ``[ACTIVITY | gloss]``. That
        # violates ``feedback_show_dont_tell_director``: wards must
        # not narrate compositor / director actions — the cut IS the
        # communication, not a label about the cut. The activity badge
        # stays as the stance-of-self signal; the dispatch path
        # (camera-hero, ward.highlight, preset.bias) handles the
        # compositional move itself.
        gloss = ""

        if self._last_activity is not None and activity != self._last_activity:
            self._activity_flash_started_at = t
        self._last_activity = activity

        pkg = get_active_package() or _fallback_package()
        _paint_bitchx_bg(cr, canvas_w, canvas_h, pkg, ward_id="activity_header")
        paint_scanlines(
            cr,
            canvas_w,
            canvas_h,
            role_rgba=pkg.resolve_colour("muted"),
            every_n_rows=4,
            alpha=0.07,
            row_height_px=14.0,
        )

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        content = pkg.resolve_colour("terminal_default")

        bold_size = 16.0
        body_font = _bitchx_font_description(14, bold=False)
        x = 12.0
        y = 30.0

        marker = pkg.grammar.line_start_marker + " "
        x += _emissive_structural(
            cr, marker, x, y, role_rgba=muted, font_size=bold_size, t=t, phase_base=0.0
        )
        x += _emissive_structural(
            cr, "[", x, y, role_rgba=muted, font_size=bold_size, t=t, phase_base=0.5
        )
        x += _emissive_structural(
            cr,
            activity,
            x,
            y,
            role_rgba=bright,
            font_size=bold_size,
            t=t,
            phase_base=1.1,
            shimmer_hz=0.7,
        )
        if gloss:
            x += _emissive_structural(
                cr, " | ", x, y, role_rgba=muted, font_size=bold_size, t=t, phase_base=2.0
            )
            x += _draw_pango(cr, gloss, x, y - 2, font_description=body_font, color_rgba=content)
        x += _emissive_structural(
            cr, "]", x, y, role_rgba=muted, font_size=bold_size, phase_base=2.7, t=t
        )

        rotation_mode = _read_rotation_mode()
        if rotation_mode and rotation_mode not in _ROTATION_MODE_DEFAULT:
            rotation_role = _ROTATION_MODE_ROLE.get(rotation_mode, "muted")
            rotation_rgba = pkg.resolve_colour(rotation_role)  # type: ignore[arg-type]
            x += _emissive_structural(
                cr,
                " :: [ROTATION:",
                x,
                y,
                role_rgba=muted,
                font_size=bold_size,
                t=t,
                phase_base=3.3,
            )
            x += _emissive_structural(
                cr,
                rotation_mode.upper(),
                x,
                y,
                role_rgba=rotation_rgba,
                font_size=bold_size,
                t=t,
                phase_base=4.0,
                shimmer_hz=0.8,
            )
            x += _emissive_structural(
                cr,
                "]",
                x,
                y,
                role_rgba=muted,
                font_size=bold_size,
                t=t,
                phase_base=4.6,
            )

        alpha = _flash_alpha(t, self._activity_flash_started_at)
        if alpha > 0.0:
            _paint_inverse_flash(cr, canvas_w, canvas_h, bright, alpha=alpha)


# ── 2. Stance indicator ───────────────────────────────────────────────────


class StanceIndicatorCairoSource(HomageTransitionalSource):
    """Top-right badge: ``[+H <stance>]`` in IRC mode-change format.

    Emissive glyphs throughout — brackets and ``+H`` in muted, stance
    label in the stance's accent role. The label glyphs pulse at the
    stance-indexed breathing rate from :data:`STANCE_HZ`. On stance
    change, a 200 ms inverse-flash overlays the whole ward.
    """

    def __init__(self) -> None:
        super().__init__(source_id="stance_indicator")
        self._last_stance: str | None = None
        self._stance_flash_started_at: float | None = None

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        ns = _read_narrative_state()
        stance = str(ns.get("stance") or "nominal").lower()

        if self._last_stance is not None and stance != self._last_stance:
            self._stance_flash_started_at = t
        self._last_stance = stance

        pkg = get_active_package() or _fallback_package()
        _paint_bitchx_bg(cr, canvas_w, canvas_h, pkg, ward_id="stance_indicator")
        paint_scanlines(
            cr,
            canvas_w,
            canvas_h,
            role_rgba=pkg.resolve_colour("muted"),
            every_n_rows=4,
            alpha=0.07,
            row_height_px=12.0,
        )

        muted = pkg.resolve_colour("muted")
        outline = _bright_field_outline(pkg)
        stance_role_name = _STANCE_ROLE.get(stance, "accent_green")
        stance_rgba = pkg.resolve_colour(stance_role_name)  # type: ignore[arg-type]
        pulse_hz = STANCE_HZ.get(stance, 1.0)

        font_size = 12.0
        y = canvas_h / 2 + 4
        x = 6.0

        x += _emissive_structural(
            cr,
            "[+H ",
            x,
            y,
            role_rgba=muted,
            font_size=font_size,
            t=t,
            phase_base=0.0,
            halo_radius_px=0.0,
            outline_rgba=outline,
            outline_offsets=_BRIGHT_FIELD_OUTLINE_OFFSETS,
        )
        x += _emissive_structural(
            cr,
            stance.upper(),
            x,
            y,
            role_rgba=stance_rgba,
            font_size=font_size,
            t=t,
            phase_base=0.6,
            shimmer_hz=pulse_hz,
            halo_radius_px=0.0,
            outline_rgba=outline,
            outline_offsets=_BRIGHT_FIELD_OUTLINE_OFFSETS,
        )
        _emissive_structural(
            cr,
            "]",
            x,
            y,
            role_rgba=muted,
            font_size=font_size,
            t=t,
            phase_base=1.3,
            halo_radius_px=0.0,
            outline_rgba=outline,
            outline_offsets=_BRIGHT_FIELD_OUTLINE_OFFSETS,
        )

        alpha = _flash_alpha(t, self._stance_flash_started_at)
        if alpha > 0.0:
            _paint_inverse_flash(cr, canvas_w, canvas_h, stance_rgba, alpha=alpha)


# ── 3. Chat keyword legend (legacy alias post-B5) ─────────────────────────


_CHAT_KEYWORDS: list[tuple[str, str]] = [
    ("!glitch", "dense/intense"),
    ("!calm", "slow/textural"),
    ("!warm", "ambient/minimal"),
    ("!react", "beat/sound"),
    ("!vinyl", "turntable"),
    ("!study", "focused"),
]


class ChatKeywordLegendCairoSource(HomageTransitionalSource):
    """Side strip: IRC-style channel topic line listing chat keywords.

    Phase B5 swapped the ``chat_ambient`` layout binding to
    :class:`ChatAmbientWard`; this class stays registered as the legacy
    alias in case a custom layout still names ``chat_keyword_legend``.
    Rendered form: first line is the IRC topic header (with an emissive
    bullet); subsequent lines are keyword + meaning pairs with the
    keyword rendered as per-glyph emissive and the meaning via Pango.
    """

    def __init__(self) -> None:
        super().__init__(source_id="chat_keyword_legend")

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        pkg = get_active_package() or _fallback_package()
        _paint_bitchx_bg(cr, canvas_w, canvas_h, pkg, ward_id="chat_keyword_legend")
        paint_scanlines(
            cr,
            canvas_w,
            canvas_h,
            role_rgba=pkg.resolve_colour("muted"),
            every_n_rows=4,
            alpha=0.06,
            row_height_px=12.0,
        )

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        content = pkg.resolve_colour("terminal_default")
        accent = pkg.resolve_colour("accent_cyan")

        header_font = _bitchx_font_description(11, bold=True)
        body_font = _bitchx_font_description(10, bold=False)

        tx = 6.0
        paint_emissive_point(
            cr,
            cx=tx + 3.0,
            cy=12.0,
            role_rgba=muted,
            t=t,
            phase=0.0,
            centre_radius_px=1.8,
            halo_radius_px=4.0,
            outer_glow_radius_px=6.0,
            shimmer_hz=0.5,
        )
        tx = 14.0
        tx += _draw_pango(cr, "-!- Topic (", tx, 16, font_description=header_font, color_rgba=muted)
        tx += _draw_pango(cr, "#homage", tx, 16, font_description=header_font, color_rgba=accent)
        _draw_pango(cr, "):", tx, 16, font_description=header_font, color_rgba=muted)

        y = 32
        for idx, (keyword, meaning) in enumerate(_CHAT_KEYWORDS[:8]):
            kw_advance = _emissive_structural(
                cr,
                keyword,
                8,
                y,
                role_rgba=bright,
                font_size=10.0,
                t=t,
                phase_base=idx * 0.43,
                shimmer_hz=0.6,
            )
            sep_advance = _draw_pango(
                cr,
                " · ",
                8 + kw_advance,
                y,
                font_description=body_font,
                color_rgba=muted,
            )
            _draw_pango(
                cr,
                meaning,
                8 + kw_advance + sep_advance,
                y,
                font_description=body_font,
                color_rgba=content,
            )
            y += 14


# ── 4. Grounding provenance ticker ────────────────────────────────────────


class GroundingProvenanceTickerCairoSource(HomageTransitionalSource):
    """Bottom-left diagnostic: ``* <signal>`` rows with slide-in entries.

    The ``*`` line-start renders as a 3 px emissive centre dot in the
    muted role (point of light). Signal names render via Pango in the
    bright role for legibility. When no provenance is available, the
    ward shows ``*  (ungrounded)`` in muted, with the label's alpha
    breathing at 0.3 Hz so even the empty state shows life.

    New entries slide in from the left over a 400 ms envelope,
    triggered by a change in the provenance hash.
    """

    def __init__(self) -> None:
        super().__init__(source_id="grounding_provenance_ticker")
        self._last_prov_hash: int | None = None
        self._prov_change_started_at: float | None = None

    def _slide_progress(self, t: float) -> float:
        if self._prov_change_started_at is None:
            return 1.0
        dt = t - self._prov_change_started_at
        if dt >= 0.4:
            return 1.0
        if dt <= 0.0:
            return 0.0
        return dt / 0.4

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        intent = _read_latest_intent()
        from shared.director_intent import split_grounding_provenance

        prov = intent.get("grounding_provenance") or []
        # Synthetic entries (fallback.*, inferred.*, parser-error,
        # silence-hold) are director-loop diagnostics, not evidence.
        # They are meta-state leakage on broadcast and cannot make this
        # ticker look grounded. Mixed lists keep only real refs.
        prov_clean = []
        for s in prov:
            s_str = str(s).strip()
            if s_str.startswith("."):
                continue

            # If the LLM dumped a comma-separated list into one string, split it
            if " , " in s_str or "," in s_str:
                parts = [x.strip() for x in s_str.split(",")]
                real, _synthetic = split_grounding_provenance(
                    [p for p in parts if p and not p.startswith(".")]
                )
                prov_clean.extend(real)
            else:
                real, _synthetic = split_grounding_provenance([s_str])
                prov_clean.extend(real)

        prov_list = prov_clean[:6]

        prov_hash = hash(tuple(prov_list))
        if self._last_prov_hash is not None and prov_hash != self._last_prov_hash:
            self._prov_change_started_at = t
        self._last_prov_hash = prov_hash

        pkg = get_active_package() or _fallback_package()
        _paint_bitchx_bg(cr, canvas_w, canvas_h, pkg, ward_id="grounding_provenance_ticker")
        paint_scanlines(
            cr,
            canvas_w,
            canvas_h,
            role_rgba=pkg.resolve_colour("muted"),
            every_n_rows=4,
            alpha=0.06,
            row_height_px=12.0,
        )

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")

        font = _bitchx_font_description(11, bold=False)
        y = canvas_h / 2 + 4
        x = 8.0

        if not prov_list:
            breath = paint_breathing_alpha(
                t,
                hz=_UNGROUNDED_BREATH_HZ,
                baseline=0.55,
                amplitude=0.25,
                phase=0.0,
            )
            paint_emissive_point(
                cr,
                cx=x + 3.0,
                cy=y - 4.0,
                role_rgba=muted,
                t=t,
                phase=0.0,
                baseline_alpha=0.6,
                centre_radius_px=1.8,
                halo_radius_px=4.0,
                outer_glow_radius_px=6.0,
                shimmer_hz=_UNGROUNDED_BREATH_HZ,
            )
            r, g, b, _a = muted
            _draw_pango(
                cr,
                "  (ungrounded)",
                x + 10.0,
                y,
                font_description=font,
                color_rgba=(r, g, b, breath),
            )
            return

        slide = self._slide_progress(t)
        slide_x_offset = (1.0 - slide) * -30.0

        for idx, signal in enumerate(prov_list):
            if x > canvas_w - 80:
                break
            paint_emissive_point(
                cr,
                cx=x + slide_x_offset + 3.0,
                cy=y - 4.0,
                role_rgba=muted,
                t=t,
                phase=idx * 0.27,
                centre_radius_px=1.8,
                halo_radius_px=4.5,
                outer_glow_radius_px=6.5,
                shimmer_hz=0.6,
            )
            x += 10.0
            advance = _draw_pango(
                cr,
                signal,
                x + slide_x_offset,
                y,
                font_description=font,
                color_rgba=bright,
            )
            x += advance + 8.0


# ── Back-compat helpers for pre-HOMAGE wards (retire in Phase 11) ────────

# ``hothouse_sources.py`` (and any other non-migrated ward) still imports
# ``_draw_rounded_rect`` and ``_palette`` + ``_read_working_mode``. Those
# wards carry the legacy Grafana-era chrome until their Phase 11 migration;
# keeping the helpers here (marked as back-compat) means we don't force a
# big-bang migration just to land the four legibility surfaces.

_WORKING_MODE_FILE = Path(os.path.expanduser("~/.cache/hapax/working-mode"))

_PALETTE = {
    "research": {
        "fg_primary": (0.830, 0.830, 0.740, 1.0),
        "accent_nominal": (0.522, 0.601, 0.000, 1.0),
        "accent_seeking": (0.797, 0.477, 0.022, 1.0),
        "accent_cautious": (0.708, 0.536, 0.000, 1.0),
        "accent_warning": (0.796, 0.294, 0.086, 1.0),
        "bg_overlay": (0.000, 0.169, 0.212, 0.75),
    },
    "rnd": {
        "fg_primary": (0.922, 0.859, 0.699, 1.0),
        "accent_nominal": (0.596, 0.591, 0.102, 1.0),
        "accent_seeking": (0.843, 0.596, 0.129, 1.0),
        "accent_cautious": (0.843, 0.757, 0.490, 1.0),
        "accent_warning": (0.800, 0.141, 0.114, 1.0),
        "bg_overlay": (0.157, 0.157, 0.157, 0.78),
    },
}


def _read_working_mode() -> str:
    try:
        if _WORKING_MODE_FILE.exists():
            text = _WORKING_MODE_FILE.read_text(encoding="utf-8").strip()
            if text in ("research", "rnd"):
                return text
    except Exception:
        pass
    return "research"


def _palette() -> dict:
    return _PALETTE[_read_working_mode()]


def _draw_rounded_rect(
    cr: cairo.Context,
    x: float,
    y: float,
    w: float,
    h: float,
    r: float,
    fill_rgba: tuple[float, float, float, float],
) -> None:
    """Legacy rounded-rect helper kept until Phase 11 migrates hothouse
    surfaces to HomageTransitionalSource. HOMAGE wards do not use this —
    spec §5.5 refuses rounded corners."""

    def _build_path() -> None:
        cr.new_path()
        cr.move_to(x + r, y)
        cr.line_to(x + w - r, y)
        cr.arc(x + w - r, y + r, r, -1.5708, 0)
        cr.line_to(x + w, y + h - r)
        cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
        cr.line_to(x + r, y + h)
        cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
        cr.line_to(x, y + r)
        cr.arc(x + r, y + r, r, 3.1416, 4.7124)
        cr.close_path()

    _build_path()
    cr.set_source_rgba(*fill_rgba)
    cr.fill()
    border = _stream_mode_accent()
    if border is not None:
        _build_path()
        cr.set_source_rgba(*border)
        cr.set_line_width(1.5)
        cr.stroke()


# ── Registry registration ─────────────────────────────────────────────────

# Do NOT register at import — the compositor layout loader calls
# get_cairo_source_class(name) and expects the registration to happen once.
# Wiring is done in agents.studio_compositor.cairo_sources.__init__.
