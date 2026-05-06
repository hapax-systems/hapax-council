"""Chronicle ticker Cairo source — lore-surface MVP ward #1.

ytb-LORE-MVP sub-task A (delta, 2026-04-24). Surfaces Hapax's chronicle
— the unified observability event store — as a viewer-legible ward.
Reads the last N high-salience events in a bounded time window and
renders them in BitchX grammar as a three-line ticker:

    »»» [chronicle]
      HH:MM  source.event_type
      HH:MM  source.event_type
      HH:MM  source.event_type

The ward is the first piece of the lore-surface MVP: internal-universe
signals that were already structured and readable but never surfaced
to livestream viewers. Structural-first per operator directive
2026-04-24 — BitchX/mIRC palette + Px437 IBM VGA typography are
applied through the active HomagePackage (``get_active_package()``),
so the authentic-asset swap (ytb-AUTH-PALETTE + ytb-AUTH1) lands
without ward-code changes.

The ward is feature-flagged OFF by default via
``HAPAX_LORE_CHRONICLE_TICKER_ENABLED=0``. Operator flips after visual
sign-off on a live broadcast. Registered in
``cairo_sources.__init__`` so layout JSON can declare it independent
of the flag.

Read source: ``shared.chronicle.query()`` over
``/dev/shm/hapax-chronicle/events.jsonl``. 10-minute window by default,
salience threshold 0.7, up to 3 rows. All reads are wrapped; a missing
file or malformed content renders the empty state (transparent surface).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.chronicle import CHRONICLE_FILE, ChronicleEvent, query
from shared.homage_package import HomagePackage

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

# Default natural-size footprint; picked so three rows of 14 px text at
# BitchX container spacing render without clipping and the ward is
# comfortably readable as a PiP at 1080p.
_DEFAULT_NATURAL_W: int = 420
_DEFAULT_NATURAL_H: int = 140

# Salience threshold — chronicle events carry an optional ``salience``
# float in their payload. Any event whose payload salience meets this
# bar is accepted regardless of source. After the 2026-05-06 salience
# tagging series (PRs #2637, #2661, #2669, #2682, #2697, #2706, #2717)
# the following emitters tag salience and surface independent of the
# source allow-list: ``stimmung`` (dimension/stance), ``m8_stem_recorder``,
# ``narration_triad``, ``mail_monitor_operational``, and all three
# payment rails (``payment_processors.lightning`` / ``.nostr_zap`` /
# ``.liberapay``). The allow-list still backs sources that emit
# without salience.
_SALIENCE_THRESHOLD: float = 0.7

# Source allow-list — events from these sources surface without a
# salience tag. Picked from the same 12 h scan: the firehose is
# ``visual.*`` (94%) plus ``*.snapshot`` / ``engine.rule.matched``
# routine events; the remainder — ``stimmung``, ``programme``,
# ``director``, ``consent``, ``research_marker``, ``axiom``,
# ``capability``, ``impingement`` — is lore-worthy by source alone.
# Kept generous for MVP so operator sees what the ward actually
# surfaces on broadcast; tightening is a follow-up if the ward reads
# noisy.
_LORE_SOURCES: frozenset[str] = frozenset(
    {
        "stimmung",
        "programme",
        "director",
        "consent",
        "research_marker",
        "axiom",
        "capability",
        "impingement",
    }
)

# Event-type blocklist — specific ``source.event_type`` strings always
# skipped even if the source is in ``_LORE_SOURCES`` or carries
# salience above the threshold. Guards against known high-frequency
# routine events leaking in.
_NOISE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "engine.rule.matched",
        # ``shared/chronicle_sampler.py`` writes ``"*"`` source +
        # ``"snapshot"`` event_type on every periodic stimmung /
        # eigenform / signal-bus capture (the routine-event docstring
        # at the top of this file calls it out alongside
        # ``engine.rule.matched``). It must never surface in the lore
        # strip — even if a future caller starts tagging salience on
        # it.
        "*.snapshot",
    }
)

# 10-minute window on the chronicle. Retention of the chronicle itself
# is 12 h (``RETENTION_S``), but the ward only cares about what's
# currently relevant.
_WINDOW_SECONDS: float = 600.0

# Up to three rows under the header.
_MAX_ROWS: int = 3

# Refresh cadence — the ward's display recomputes the event list at most
# once per second. Cheap, avoids jitter on 30 fps render.
_REFRESH_INTERVAL_S: float = 1.0

_FEATURE_FLAG_ENV: str = "HAPAX_LORE_CHRONICLE_TICKER_ENABLED"


def _feature_flag_enabled() -> bool:
    """Read ``HAPAX_LORE_CHRONICLE_TICKER_ENABLED``. Default OFF."""
    raw = os.environ.get(_FEATURE_FLAG_ENV, "0")
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _fmt_row(event: ChronicleEvent) -> str:
    """Compose a single ticker line from a chronicle event.

    Format: ``HH:MM  source.event_type``. The colon-separated
    ``source.event_type`` is the canonical discriminator already used
    by the chronicle schema; no lossy human-translation needed for MVP.
    """
    when = datetime.fromtimestamp(event.ts).strftime("%H:%M")
    return f"{when}  {event.source}.{event.event_type}"


def _is_lore_worthy(event: ChronicleEvent) -> bool:
    """Return True if ``event`` should surface in the chronicle-ticker ward.

    An event surfaces when EITHER:
      - its payload carries numeric ``salience`` >= ``_SALIENCE_THRESHOLD``
        (forward-compatible path — any emitter that starts tagging
        salience is picked up automatically), OR
      - its ``source`` is in the lore-worthy allow-list
        (current-state path — no emitter sets salience today).

    The allow-list path is further gated by the event-type blocklist
    so specific high-frequency routine events (``engine.rule.matched``)
    stay out even if ``engine`` joins the allow-list.
    """
    if f"{event.source}.{event.event_type}" in _NOISE_EVENT_TYPES:
        return False
    salience = event.payload.get("salience")
    if isinstance(salience, (int, float)) and salience >= _SALIENCE_THRESHOLD:
        return True
    return event.source in _LORE_SOURCES


def _event_rank_key(event: ChronicleEvent) -> tuple[float, float]:
    """Sort key for ranking lore-worthy events.

    Returns ``(-salience, -ts)`` so the highest-salience newest events
    sort first when fed to ``sorted``. Events without a numeric
    ``salience`` field are treated as ``_SALIENCE_THRESHOLD`` (0.7) —
    just enough to clear the floor but never outrank an explicitly
    tagged event of equal age.
    """
    salience = event.payload.get("salience")
    if not isinstance(salience, (int, float)):
        salience = _SALIENCE_THRESHOLD
    return (-float(salience), -event.ts)


def _collect_rows(now: float) -> list[str]:
    """Read the chronicle and return up to ``_MAX_ROWS`` formatted lines.

    Lore-worthy events are ranked by ``(salience desc, ts desc)`` before
    truncation — so a critical stance transition that landed 30s ago
    outranks a 5s-old routine event of the same source. Events without
    salience get a 0.7 floor for ranking; they only displace newer
    salience-tagged events when both share that floor.
    """
    try:
        events = query(
            since=now - _WINDOW_SECONDS,
            until=now,
            limit=200,
            path=CHRONICLE_FILE,
        )
    except Exception:
        log.debug("chronicle query failed", exc_info=True)
        return []

    kept = [event for event in events if _is_lore_worthy(event)]
    kept.sort(key=_event_rank_key)
    return [_fmt_row(event) for event in kept[:_MAX_ROWS]]


def _fallback_package() -> HomagePackage:
    """Return the compiled-in BitchX package when registry resolution fails."""
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _bitchx_font_description(pkg: HomagePackage, size: int, *, bold: bool = False) -> str:
    """Build a Pango font-description string for the active package."""
    weight = " Bold" if bold else ""
    return f"{pkg.typography.primary_font_family}{weight} {int(size)}"


def _resolve(pkg: HomagePackage, role: str) -> tuple[float, float, float, float]:
    """Resolve a HomagePackage palette role with a muted fallback."""
    try:
        return pkg.resolve_colour(role)
    except Exception:
        log.debug("palette role %s unresolved on %s", role, pkg.id, exc_info=True)
        return pkg.resolve_colour("muted")


class ChronicleTickerCairoSource(HomageTransitionalSource):
    """Three-row ticker of recent high-salience chronicle events.

    Default natural size: 420×140 px. Composition:

        »»» [chronicle]                  (header, emissive chevron + muted bracket)
          HH:MM  source.event_type       (content row, content colour)
          HH:MM  source.event_type
          HH:MM  source.event_type

    No background, no border — follows the 2026-04-23 "zero container
    opacity" directive (see legibility_sources). The header chevron is
    the only emphasis; everything else reads via colour role.
    """

    source_id: str = "chronicle_ticker"

    def __init__(self) -> None:
        super().__init__(source_id=self.source_id)
        self._cached_rows: list[str] = []
        self._last_refresh_ts: float = 0.0

    def _maybe_refresh(self, now: float) -> None:
        if now - self._last_refresh_ts >= _REFRESH_INTERVAL_S:
            self._cached_rows = _collect_rows(now)
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

        # Late-imported to keep the module importable in CI harnesses
        # without Pango/PangoCairo typelibs.
        from agents.studio_compositor.text_render import (
            TextStyle,
            measure_text,
            render_text,
        )

        pkg = get_active_package() or _fallback_package()
        header_font = _bitchx_font_description(pkg, 14, bold=True)
        row_font = _bitchx_font_description(pkg, 13)

        chevron_role = _resolve(pkg, "accent_cyan")
        bracket_role = _resolve(pkg, "muted")
        content_role = _resolve(pkg, pkg.grammar.content_colour_role)
        time_role = _resolve(pkg, "muted")

        # Header: emissive chevron + bracketed label.
        chevron = TextStyle(
            text="»»» ",
            font_description=header_font,
            color_rgba=chevron_role,
        )
        cw, ch = measure_text(cr, chevron)
        render_text(cr, chevron, x=8.0, y=8.0)

        bracket = TextStyle(
            text="[chronicle]",
            font_description=header_font,
            color_rgba=bracket_role,
        )
        render_text(cr, bracket, x=8.0 + cw, y=8.0)

        # Rows — fixed line height so cadence jitter cannot resize the
        # ward. Each row: time (muted) + two-space gutter + event text
        # (content colour).
        line_height = 20.0
        row_y = 8.0 + max(ch, 14.0) + 6.0

        for row in self._cached_rows[:_MAX_ROWS]:
            prefix, _sep, body = row.partition("  ")
            time_style = TextStyle(
                text="  " + prefix + "  ",
                font_description=row_font,
                color_rgba=time_role,
            )
            tw, _th = measure_text(cr, time_style)
            render_text(cr, time_style, x=8.0, y=row_y)

            body_style = TextStyle(
                text=body,
                font_description=row_font,
                color_rgba=content_role,
            )
            render_text(cr, body_style, x=8.0 + tw, y=row_y)
            row_y += line_height

        # Empty state: when no salient events in the window, render a
        # single muted ``(quiet)`` line so the ward doesn't strobe between
        # "present with header" and "totally blank".
        if not self._cached_rows:
            quiet = TextStyle(
                text="  (quiet)",
                font_description=row_font,
                color_rgba=bracket_role,
            )
            render_text(cr, quiet, x=8.0, y=row_y)


__all__ = ["ChronicleTickerCairoSource"]
