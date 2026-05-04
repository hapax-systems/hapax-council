"""Programme-history Cairo source — Enlightenment-GTK + BitchX HOMAGE hybrid ward.

Cc-task ``ward-programme-history-e-panel`` (operator directive
"Enlightenment-GTK + BitchX HOMAGE Ward hybrid epic — get it all done").

Multi-session arc surface: the prior wards (``programme_state_ward``,
``programme_banner_ward``) name the *current* programme; this ward
shows the *trajectory* — the last few programmes the operator has run
laid out as a bordered timeline so a viewer joining the broadcast can
see at a glance the show's recent shape.

Renders inside an Enlightenment/Moksha curly-brace E-panel chrome
border (``ENLIGHTENMENT_MOKSHA_PACKAGE`` from PR #1314, the
``ytb-AUTH-ENLIGHTENMENT-package`` Phase 1 ship). The interior uses
mIRC-flavoured accent colours per role to keep the aesthetic distinct
from the BitchX-grammar wards: BitchX wards use angle-bracket
containers + zero-cut transitions, this ward uses curly-brace chrome +
soft 333 ms envelopes.

Aesthetic-library tokens flow through the active HomagePackage's
palette + typography, so when ``ytb-AUTH-PALETTE`` (Moksha portion)
swaps the inline constants for byte-exact EDC extractions the ward
picks up the new tokens without any code change.

Feature-flagged OFF by default via
``HAPAX_LORE_PROGRAMME_HISTORY_ENABLED=0``. Operator flips after a
visual sign-off on a live broadcast. Default layout assignment is a
separate operator-owned decision — the ward registers itself in
``cairo_sources.__init__`` so any layout JSON can declare it.

Cadence: refreshes the programme-history view every 5 s (0.2 Hz). The
multi-session arc only changes at programme boundaries (minutes), so
even 0.2 Hz is generous; tighter cadence would just burn the store
read. Cap is 2 Hz per the cc-task constraint.
"""

from __future__ import annotations

import logging
import math
import os
import time
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package, get_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.homage_package import HomagePackage
from shared.programme import Programme, ProgrammeStatus
from shared.programme_store import ProgrammePlanStore

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


# Natural-size footprint. Wider than the single-programme wards because
# a multi-session arc needs lateral room for at least 5 cells.
_DEFAULT_NATURAL_W: int = 460
_DEFAULT_NATURAL_H: int = 110

# Refresh cadence — operator constraint ≤ 2 Hz; spec asks for 0.2 Hz
# (one refresh every 5 s). Programme boundaries are minutes apart, so
# this is generous and avoids hammering the file-backed store.
_REFRESH_INTERVAL_S: float = 5.0

# Multi-session arc length. 5 cells fits the natural width with room for
# the curly-brace chrome on either side without text getting clipped.
# Tunable for future layouts that want more or fewer slots.
_HISTORY_DEPTH: int = 5

_FEATURE_FLAG_ENV: str = "HAPAX_LORE_PROGRAMME_HISTORY_ENABLED"

# Active HomagePackage name to resolve palette / typography against.
# Falls through to the runtime-active package when the named package is
# not in the registry (defensive — the registry is import-time-populated
# but tests sometimes mock partial imports).
_MOKSHA_PACKAGE_NAME: str = "enlightenment-moksha-v1"


# ProgrammeRole.value → palette-role mapping. Identical scheme to
# ``programme_state_ward.py`` so the two wards read consistently when
# they appear together; a SHOWCASE programme is yellow on both surfaces.
_ROLE_PALETTE_ROLE: dict[str, str] = {
    # Operator-context roles
    "repair": "accent_red",
    "showcase": "accent_yellow",
    "listening": "accent_cyan",
    "ritual": "accent_magenta",
    "wind_down": "accent_blue",
    # Segmented-content roles
    "tier_list": "accent_blue",
    "top_10": "accent_yellow",
    "rant": "accent_red",
    "react": "accent_green",
    "iceberg": "accent_cyan",
    "interview": "accent_magenta",
    "lecture": "bright",
    # Other operator-context roles
    "interlude": "muted",
    "work_block": "accent_blue",
    "tutorial": "accent_green",
    "hothouse_pressure": "accent_red",
    "ambient": "muted",
    "experiment": "accent_magenta",
    "invitation": "accent_green",
}


def _feature_flag_enabled() -> bool:
    """Read ``HAPAX_LORE_PROGRAMME_HISTORY_ENABLED``. Default OFF."""
    raw = os.environ.get(_FEATURE_FLAG_ENV, "0")
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _resolve_moksha_package() -> HomagePackage:
    """Return the Moksha HomagePackage, falling back to the active package.

    Lookup order:
    1. ``enlightenment-moksha-v1`` from the registry (the primary intent —
       this ward is meant to render in the Moksha aesthetic).
    2. The runtime-active HomagePackage, if any (lets a test or operator
       override route the ward through a different package without touching
       the ward code).
    3. Compiled-in fallback so renders never crash on misconfiguration.
    """
    pkg = get_package(_MOKSHA_PACKAGE_NAME)
    if pkg is not None:
        return pkg
    pkg = get_active_package()
    if pkg is not None:
        return pkg
    # Final fallback — use whatever BitchX ships with so the ward
    # renders SOMETHING legible rather than crashing.
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _moksha_font_description(pkg: HomagePackage, size: int, *, bold: bool = False) -> str:
    """Build a Pango font-description string for the active package."""
    weight = " Bold" if bold else ""
    return f"{pkg.typography.primary_font_family}{weight} {int(size)}"


def _resolve(pkg: HomagePackage, role: str) -> tuple[float, float, float, float]:
    """Resolve a HomagePackage palette role with a muted fallback."""
    try:
        return pkg.resolve_colour(role)
    except Exception:
        log.debug("palette role %s unresolved on %s", role, pkg.name, exc_info=True)
        return pkg.resolve_colour("muted")


def _role_palette_role(role_value: str) -> str:
    """Map a ProgrammeRole value to a HomagePackage palette role name."""
    return _ROLE_PALETTE_ROLE.get(role_value, "muted")


def _short_role(role_value: str) -> str:
    """Compact label for a ProgrammeRole — first ~6 chars, lowercase.

    The cells are narrow; full role names ("hothouse_pressure",
    "wind_down") would clip. We render a 6-char prefix; the role accent
    colour disambiguates between roles that collide on prefix.
    """
    if not role_value:
        return "?"
    return role_value[:6]


def _select_history(
    programmes: list[Programme],
    depth: int,
) -> list[Programme]:
    """Pick the most-recent ``depth`` programmes that have actually run.

    A "run" is any programme with ``actual_started_at`` set — that
    excludes PENDING entries the planner has scheduled but not yet
    activated. The result is sorted oldest-first so the UI renders
    left-to-right as time-flowing-forward.
    """
    started = [p for p in programmes if p.actual_started_at is not None]
    started.sort(key=lambda p: p.actual_started_at or 0.0)
    return started[-depth:]


class ProgrammeHistoryCairoSource(HomageTransitionalSource):
    """Multi-session programme arc — Moksha curly-chrome bordered timeline.

    Instantiated with an optional injected :class:`ProgrammePlanStore`
    to keep the class unit-testable — the default-constructed store
    hits the canonical path the daimonion + logos-api share, which
    tests must not pollute.
    """

    source_id: str = "programme_history"

    def __init__(self, store: ProgrammePlanStore | None = None) -> None:
        super().__init__(source_id=self.source_id)
        self._store = store if store is not None else ProgrammePlanStore()
        self._cached_history: list[Programme] = []
        # Initialise to -inf so the first _maybe_refresh() always fires
        # regardless of the wall-clock the caller passes; matches the
        # programme_state_ward pattern.
        self._last_refresh_ts: float = -float("inf")

    def _maybe_refresh(self, now: float) -> None:
        if now - self._last_refresh_ts < _REFRESH_INTERVAL_S:
            return
        try:
            self._cached_history = _select_history(self._store.all(), _HISTORY_DEPTH)
        except Exception:
            log.debug("programme_history: store read failed", exc_info=True)
            self._cached_history = []
        self._last_refresh_ts = now

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        if not _feature_flag_enabled():
            return

        now = time.time()
        self._maybe_refresh(now)

        # Late import so the module is still importable in CI harnesses
        # that lack Pango / PangoCairo typelibs.
        from agents.studio_compositor.text_render import (
            TextStyle,
            measure_text,
            render_text,
        )

        pkg = _resolve_moksha_package()
        header_font = _moksha_font_description(pkg, 14, bold=True)
        cell_font = _moksha_font_description(pkg, 11)
        small_font = _moksha_font_description(pkg, 10)

        chrome_role = _resolve(pkg, pkg.grammar.punctuation_colour_role)
        bright_role = _resolve(pkg, pkg.grammar.identity_colour_role)
        muted_role = _resolve(pkg, "muted")
        content_role = _resolve(pkg, pkg.grammar.content_colour_role)

        history = list(self._cached_history)

        # ── Header row: { programme history }
        # ``container_shape="curly"`` from Moksha's GrammarRules — render
        # the brace explicitly so the grammar marker is legible even
        # without a chrome border drawn around the canvas.
        header_x = 8.0
        header_y = 6.0
        header_open = TextStyle(
            text="{ ",
            font_description=header_font,
            color_rgba=chrome_role,
        )
        cw, ch = measure_text(cr, header_open)
        render_text(cr, header_open, x=header_x, y=header_y)
        header_label = TextStyle(
            text="programme history",
            font_description=header_font,
            color_rgba=bright_role,
        )
        lw, _lh = measure_text(cr, header_label)
        render_text(cr, header_label, x=header_x + cw, y=header_y)
        header_close = TextStyle(
            text=" }",
            font_description=header_font,
            color_rgba=chrome_role,
        )
        render_text(cr, header_close, x=header_x + cw + lw, y=header_y)

        body_y = header_y + max(ch, 14.0) + 8.0

        if not history:
            # Empty state — single muted "{ no history yet }" row. Avoids
            # the strobe between header-only and fully-populated frames.
            empty_style = TextStyle(
                text="  { no history yet }",
                font_description=cell_font,
                color_rgba=muted_role,
            )
            render_text(cr, empty_style, x=header_x, y=body_y)
            return

        # ── Timeline cells: each programme as a curly-brace cell with
        # role accent colour. Active programmes render in identity-bright;
        # completed programmes render in their role accent at full alpha;
        # aborted programmes render in muted (low alpha implicit via the
        # muted role's typical lightness on the Moksha palette).
        cell_count = len(history)
        # Reserve trailing padding so the right edge doesn't clip and so
        # the connecting arc has room past the last cell.
        usable_w = max(canvas_w - header_x * 2.0 - 24.0, 1.0)
        cell_w = usable_w / max(cell_count, 1)

        # Connecting arc (role arc): single horizontal line through the
        # vertical centre of every cell, drawn FIRST so the cell chrome
        # paints on top of it. A subtle muted line; the chevron at the
        # right tip points to the active programme — the operator's
        # "where the arc has come from / where it ends up".
        line_y = body_y + 14.0
        cr.save()
        cr.set_source_rgba(*muted_role)
        cr.set_line_width(1.5)
        cr.move_to(header_x + 4.0, line_y)
        cr.line_to(header_x + cell_count * cell_w - 4.0, line_y)
        cr.stroke()
        cr.restore()

        for idx, programme in enumerate(history):
            cell_x = header_x + idx * cell_w
            self._render_cell(
                cr,
                programme=programme,
                x=cell_x,
                y=body_y,
                w=cell_w,
                cell_font=cell_font,
                small_font=small_font,
                chrome_role=chrome_role,
                muted_role=muted_role,
                bright_role=bright_role,
                content_role=content_role,
                pkg=pkg,
                now=now,
            )

        # Active-cap chevron at the trailing edge — points to the most
        # recent programme cell. Only drawn when the most-recent entry
        # is currently ACTIVE (per the active-programme invariant the
        # planner enforces).
        last = history[-1]
        if last.status == ProgrammeStatus.ACTIVE:
            cr.save()
            cr.set_source_rgba(*bright_role)
            cr.set_line_width(1.8)
            tip_x = header_x + cell_count * cell_w
            cr.move_to(tip_x - 6.0, line_y - 4.0)
            cr.line_to(tip_x + 2.0, line_y)
            cr.line_to(tip_x - 6.0, line_y + 4.0)
            cr.stroke()
            cr.restore()

    def _render_cell(
        self,
        cr: cairo.Context,
        *,
        programme: Programme,
        x: float,
        y: float,
        w: float,
        cell_font: str,
        small_font: str,
        chrome_role: tuple[float, float, float, float],
        muted_role: tuple[float, float, float, float],
        bright_role: tuple[float, float, float, float],
        content_role: tuple[float, float, float, float],
        pkg: HomagePackage,
        now: float,
    ) -> None:
        """Render one programme cell — curly chrome + role label + dwell.

        Cell layout::

              { role  }
                12:34
        """
        from agents.studio_compositor.text_render import (
            TextStyle,
            measure_text,
            render_text,
        )

        del muted_role  # currently unused on the cell; reserved for future
        # status-specific tinting (aborted programmes could dim the
        # accent toward muted; left for follow-on visual sign-off).

        role_value = (
            programme.role.value if hasattr(programme.role, "value") else str(programme.role)
        )
        role_colour = _resolve(pkg, _role_palette_role(role_value))
        is_active = programme.status == ProgrammeStatus.ACTIVE
        # Active programmes use the identity-bright colour for the
        # cell label so the eye anchors there even before reading the
        # role accent. Past programmes carry their role accent.
        label_colour = bright_role if is_active else role_colour

        # Cell row 1: { role }
        open_style = TextStyle(
            text="{ ",
            font_description=cell_font,
            color_rgba=chrome_role,
        )
        ow, oh = measure_text(cr, open_style)
        render_text(cr, open_style, x=x + 2.0, y=y)
        role_style = TextStyle(
            text=_short_role(role_value),
            font_description=cell_font,
            color_rgba=label_colour,
        )
        rw, _rh = measure_text(cr, role_style)
        render_text(cr, role_style, x=x + 2.0 + ow, y=y)
        close_style = TextStyle(
            text=" }",
            font_description=cell_font,
            color_rgba=chrome_role,
        )
        render_text(cr, close_style, x=x + 2.0 + ow + rw, y=y)

        # Cell row 2: dwell duration in mm:ss
        dwell_y = y + max(oh, 12.0) + 14.0
        dwell_text = _format_dwell_short(programme, now)
        dwell_style = TextStyle(
            text=dwell_text,
            font_description=small_font,
            color_rgba=content_role,
        )
        # Right-align the dwell text inside the cell so the number sits
        # under the closing brace — keeps the eye on the role label.
        dw, _dh = measure_text(cr, dwell_style)
        target_x = x + max(w * 0.5 - dw * 0.5, 4.0)
        render_text(cr, dwell_style, x=target_x, y=dwell_y)


def _format_dwell_short(programme: Programme, now: float) -> str:
    """Render a programme's dwell as ``MM:SS`` or ``HH:MM`` for long runs.

    Active programmes show wall-clock dwell since ``actual_started_at``.
    Completed programmes show the recorded run length
    (``actual_ended_at - actual_started_at``). Aborted programmes show
    whatever dwell the manager wrote before the abort. Missing data
    falls back to ``"--:--"`` so the row cadence stays stable.
    """
    started = programme.actual_started_at
    ended = programme.actual_ended_at
    if started is None:
        return "--:--"
    if ended is not None:
        elapsed = max(0.0, ended - started)
    else:
        elapsed = max(0.0, now - started)
    elapsed_int = int(math.floor(elapsed))
    if elapsed_int >= 3600:
        return f"{elapsed_int // 3600:02d}:{(elapsed_int % 3600) // 60:02d}"
    return f"{elapsed_int // 60:02d}:{elapsed_int % 60:02d}"


__all__ = ["ProgrammeHistoryCairoSource"]
