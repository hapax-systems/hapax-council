"""Legibility Cairo sources — on-frame authorship indicators.

Phase 4 of the volitional-grounded-director epic (PR #1017, spec §3.5).
Phase 4 of the HOMAGE epic (spec §4.10): these four sources are the
first to inherit :class:`HomageTransitionalSource`, rendering their
content under the active HomagePackage's grammar (BitchX grammar as
the default package):

- :class:`ActivityHeaderCairoSource` — ``»»» [ACTIVITY | gloss]``
- :class:`StanceIndicatorCairoSource` — IRC mode-change flash
  (``[+H <stance>]``) — grey brackets, bright mode flag, accent stance.
- :class:`ChatKeywordLegendCairoSource` — IRC topic line
  (``-!- Topic (#homage): <keyword>, <keyword>, ...``).
- :class:`GroundingProvenanceTickerCairoSource` — IRC backscroll of
  ``* <signal> has joined`` / ``(ungrounded)`` when empty.

Every source reads ``/dev/shm/hapax-director/narrative-state.json`` or
``~/hapax-state/stream-experiment/director-intent.jsonl``. Readers are
wrapped in try/except; absent files render neutral/empty states.

When ``HAPAX_HOMAGE_ACTIVE=0`` (default until Phase 12) the transition
FSM is bypassed and ``render_content()`` runs every tick — so these
sources render in BitchX grammar already, even without the choreographer
in the loop. When the flag flips on in Phase 12, transition FSM gates
rendering on choreographer-emitted entries/exits.

Typography: the BitchX package declares Px437 IBM VGA 8x16; Pango falls
back to DejaVu Sans Mono when Px437 is not installed. Palette comes from
the active package (``get_active_package()``) via role resolution —
no hardcoded hex.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.homage_package import HomagePackage

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

_NARRATIVE_STATE = Path("/dev/shm/hapax-director/narrative-state.json")
_DIRECTOR_INTENT_JSONL = Path(
    os.path.expanduser("~/hapax-state/stream-experiment/director-intent.jsonl")
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


def _read_narrative_state() -> dict:
    try:
        if _NARRATIVE_STATE.exists():
            return json.loads(_NARRATIVE_STATE.read_text(encoding="utf-8"))
    except Exception:
        log.debug("narrative-state read failed", exc_info=True)
    return {}


def _read_latest_intent() -> dict:
    try:
        if _DIRECTOR_INTENT_JSONL.exists():
            size = _DIRECTOR_INTENT_JSONL.stat().st_size
            with _DIRECTOR_INTENT_JSONL.open("rb") as fh:
                fh.seek(max(0, size - 4096))
                tail = fh.read().decode("utf-8", errors="ignore")
            lines = [line for line in tail.splitlines() if line.strip()]
            if lines:
                return json.loads(lines[-1])
    except Exception:
        log.debug("director-intent tail failed", exc_info=True)
    return {}


def _select_bitchx_font(cr: cairo.Context, size: int, *, bold: bool = False) -> None:
    """Apply the active package's primary monospaced font to ``cr``.

    Cairo falls back gracefully when the primary font is missing; the
    guarantee we care about is monospacing, which every entry in the
    BitchX fallback chain (DejaVu Sans Mono) provides.
    """
    import cairo as _c

    pkg = get_active_package() or _fallback_package()
    cr.select_font_face(
        pkg.typography.primary_font_family,
        _c.FONT_SLANT_NORMAL,
        _c.FONT_WEIGHT_BOLD if bold else _c.FONT_WEIGHT_NORMAL,
    )
    cr.set_font_size(size)


def _fallback_package() -> HomagePackage:
    """Return the compiled-in BitchX package when registry resolution fails
    (tests in isolation, consent-safe layout for the chrome path)."""
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _paint_bitchx_bg(cr: cairo.Context, w: float, h: float, pkg: HomagePackage) -> None:
    """Fill a flat CP437-style background — sharp corners, no rounded
    rects (spec §5.5 refuses ``rounded-corners``). Thin border hints the
    current stream mode using an accent colour."""
    r, g, b, a = pkg.resolve_colour("background")
    cr.save()
    cr.set_source_rgba(r, g, b, a)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    border = _stream_mode_accent()
    if border is not None:
        cr.set_source_rgba(*border)
        cr.set_line_width(1.0)
        cr.rectangle(0.5, 0.5, w - 1.0, h - 1.0)
        cr.stroke()
    cr.restore()


# ── 1. Activity header ────────────────────────────────────────────────────


class ActivityHeaderCairoSource(HomageTransitionalSource):
    """Top-center strip under BitchX grammar.

    Rendered form: ``»»» [ACTIVITY | gloss]`` where the chevron line-start
    marker and brackets+pipe use the package's muted (grey) role, the
    activity token uses the bright (identity) role, and the gloss uses
    terminal_default.
    """

    def __init__(self) -> None:
        super().__init__(source_id="activity_header")

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
        activity = (ns.get("activity") or intent.get("activity") or "—").upper()
        gloss = ""
        imps = intent.get("compositional_impingements") or []
        if imps:
            best = max(imps, key=lambda i: i.get("salience", 0.0))
            gloss = str(best.get("narrative", ""))[:48]

        pkg = get_active_package() or _fallback_package()
        _paint_bitchx_bg(cr, canvas_w, canvas_h, pkg)

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        content = pkg.resolve_colour("terminal_default")

        _select_bitchx_font(cr, 18, bold=True)
        x = 12.0
        y = 28.0

        # »»» line-start marker (muted)
        cr.set_source_rgba(*muted)
        cr.move_to(x, y)
        marker = pkg.grammar.line_start_marker + " "
        cr.show_text(marker)
        x += cr.text_extents(marker).x_advance

        # Opening bracket (muted)
        cr.move_to(x, y)
        cr.show_text("[")
        x += cr.text_extents("[").x_advance

        # Activity (bright)
        cr.set_source_rgba(*bright)
        cr.move_to(x, y)
        cr.show_text(activity)
        x += cr.text_extents(activity).x_advance

        if gloss:
            # pipe separator (muted)
            cr.set_source_rgba(*muted)
            cr.move_to(x, y)
            cr.show_text(" | ")
            x += cr.text_extents(" | ").x_advance
            # gloss (content)
            cr.set_source_rgba(*content)
            _select_bitchx_font(cr, 13, bold=False)
            cr.move_to(x, y - 2)
            cr.show_text(gloss)
            x += cr.text_extents(gloss).x_advance
            _select_bitchx_font(cr, 18, bold=True)

        # Closing bracket (muted)
        cr.set_source_rgba(*muted)
        cr.move_to(x, y)
        cr.show_text("]")


# ── 2. Stance indicator ───────────────────────────────────────────────────


class StanceIndicatorCairoSource(HomageTransitionalSource):
    """Top-right badge: ``[+H <stance>]`` in IRC mode-change format.

    Grey ``[``, muted ``+H`` flag (literal HOMAGE flag), stance-coloured
    label, grey ``]``. No coloured dot — the stance colour IS on the
    label itself (spec §5.1 identity colouring).
    """

    def __init__(self) -> None:
        super().__init__(source_id="stance_indicator")

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

        pkg = get_active_package() or _fallback_package()
        _paint_bitchx_bg(cr, canvas_w, canvas_h, pkg)

        muted = pkg.resolve_colour("muted")
        stance_rgba = pkg.resolve_colour(_STANCE_ROLE.get(stance, "accent_green"))

        _select_bitchx_font(cr, 13, bold=True)
        y = canvas_h / 2 + 5
        x = 8.0

        cr.set_source_rgba(*muted)
        cr.move_to(x, y)
        cr.show_text("[+H ")
        x += cr.text_extents("[+H ").x_advance

        cr.set_source_rgba(*stance_rgba)
        cr.move_to(x, y)
        cr.show_text(stance.upper())
        x += cr.text_extents(stance.upper()).x_advance

        cr.set_source_rgba(*muted)
        cr.move_to(x, y)
        cr.show_text("]")


# ── 3. Chat keyword legend ────────────────────────────────────────────────


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

    Rendered form (first line, muted): ``-!- Topic (#homage):``. Each
    subsequent line is a keyword+meaning pair — bright keyword, muted
    separator, terminal_default meaning.
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
        _paint_bitchx_bg(cr, canvas_w, canvas_h, pkg)

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        content = pkg.resolve_colour("terminal_default")
        accent = pkg.resolve_colour("accent_cyan")

        _select_bitchx_font(cr, 11, bold=True)
        cr.set_source_rgba(*muted)
        cr.move_to(8, 16)
        cr.show_text("-!- Topic (")
        tx = 8 + cr.text_extents("-!- Topic (").x_advance
        cr.set_source_rgba(*accent)
        cr.move_to(tx, 16)
        cr.show_text("#homage")
        tx += cr.text_extents("#homage").x_advance
        cr.set_source_rgba(*muted)
        cr.move_to(tx, 16)
        cr.show_text("):")

        _select_bitchx_font(cr, 10, bold=False)
        y = 36
        for keyword, meaning in _CHAT_KEYWORDS[:8]:
            cr.set_source_rgba(*bright)
            cr.move_to(8, y)
            cr.show_text(keyword)
            kw_advance = cr.text_extents(keyword).x_advance
            cr.set_source_rgba(*muted)
            cr.move_to(8 + kw_advance, y)
            cr.show_text(" · ")
            sep_advance = cr.text_extents(" · ").x_advance
            cr.set_source_rgba(*content)
            cr.move_to(8 + kw_advance + sep_advance, y)
            cr.show_text(meaning)
            y += 15


# ── 4. Grounding provenance ticker ────────────────────────────────────────


class GroundingProvenanceTickerCairoSource(HomageTransitionalSource):
    """Bottom-left diagnostic: IRC backscroll of ``* <signal> has joined``.

    When grounding_provenance is empty (``*  (ungrounded)``), the line
    uses the muted role to signal the UNGROUNDED state without alarming
    chrome.
    """

    def __init__(self) -> None:
        super().__init__(source_id="grounding_provenance_ticker")

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        intent = _read_latest_intent()
        prov = intent.get("grounding_provenance") or []

        pkg = get_active_package() or _fallback_package()
        _paint_bitchx_bg(cr, canvas_w, canvas_h, pkg)

        muted = pkg.resolve_colour("muted")
        bright = pkg.resolve_colour("bright")
        content = pkg.resolve_colour("terminal_default")

        _select_bitchx_font(cr, 10, bold=False)
        y = canvas_h / 2 + 4
        x = 8.0

        if not prov:
            cr.set_source_rgba(*muted)
            cr.move_to(x, y)
            cr.show_text("*  (ungrounded)")
            return

        # IRC join format: "* <signal> has joined" — one per signal, up to 6.
        for signal in prov[:6]:
            s = str(signal)
            cr.set_source_rgba(*muted)
            cr.move_to(x, y)
            cr.show_text("* ")
            x += cr.text_extents("* ").x_advance

            cr.set_source_rgba(*bright)
            cr.move_to(x, y)
            cr.show_text(s)
            x += cr.text_extents(s).x_advance

            cr.set_source_rgba(*content)
            cr.move_to(x, y)
            cr.show_text("  ")
            x += cr.text_extents("  ").x_advance

            if x > canvas_w - 80:
                break


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
