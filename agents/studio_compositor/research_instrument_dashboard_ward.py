"""Research-instrument-dashboard ward — HYBRID Moksha+BitchX aesthetic.

ytb-LORE-EXT KEYSTONE — the operator's specific interest. Multi-cell
grid surfacing research conditions × claims × status in the hybrid
aesthetic mode the cc-task names a *keystone*: an outer Moksha-chrome
bordered frame containing an inner BitchX-styled mIRC-palette grid.

The frame establishes "instrument panel" feel via the Moksha
HomagePackage's steel-grey muted bracket and dim chrome accents. The
interior cells use the BitchX HomagePackage's mIRC emphasis palette
to read like a live data terminal — green for passing claims, red for
failing, yellow for unverified. That juxtaposition (deliberate panel
chrome wrapping fast terminal data) is what makes the ward "hybrid"
in the family with its three pure-aesthetic siblings (chronicle-ticker
BitchX, programme-history Moksha, ...).

Data sources:

* Active research condition: ``shared.research_marker.read_marker()``
  reads ``/dev/shm/hapax-compositor/research-marker.json``. A missing
  / stale marker resolves to "no active condition" — the ward renders
  the panel header alone, no rows.
* Claims: ``~/hapax-state/research-claims.yaml`` (operator-authored).
  Schema: ``claims: [{id, metric, target_condition, status}]`` where
  status ∈ {``passing``, ``failing``, ``unverified``}. A missing /
  malformed file is empty — no claims, panel header only.

Per cc-task constraints:

* No hardcoded hex — all colours flow through the active HomagePackage.
* Cadence 0.5 Hz — recomputed at most once every 2 s.
* Redaction-safe — aggregates only, no chat IDs / operator PII.
* Smooth envelopes per ``feedback_no_blinking_homage_wards`` — the
  ward inherits ``HomageTransitionalSource``'s 200-600 ms entry/exit
  envelope.

Feature flag default OFF:
``HAPAX_LORE_RESEARCH_INSTRUMENT_DASHBOARD_ENABLED``. Operator flips
after live visual sign-off.

Spec: ``docs/superpowers/specs/...future-wards.md`` (ytb-LORE-EXT
hybrid keystone).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource
from shared.homage_package import HomagePackage
from shared.research_marker import read_marker

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)


# ── Layout constants ────────────────────────────────────────────────────
#
# Natural-size footprint sized so a 3-row grid at 13 px text renders
# without clipping at typical PiP placement (lower-right slot or
# objective_strip-style band). Tests pin these so layout JSON
# revisions are explicit.
DEFAULT_NATURAL_W: int = 540
DEFAULT_NATURAL_H: int = 220

# Frame border thickness — Moksha-chrome looks deliberate at 2 px;
# 1 px reads as an accident, 3+ px reads as Windows 95.
FRAME_BORDER_PX: float = 2.0

# Frame inner padding so grid doesn't kiss the chrome.
FRAME_INNER_PADDING_PX: float = 12.0

# Grid row height including padding. Operator wants no blinking →
# rows compute against actual font ascent at draw time, not against
# this constant; this is the *minimum* row size for layout planning.
GRID_ROW_HEIGHT_PX: float = 28.0

# Panel header height (the "[ research instrument ]" cap).
HEADER_HEIGHT_PX: float = 24.0

# Up to this many rows render. Operator can grow the data model
# without ward churn; rows beyond this are silently truncated and the
# header notes "+N more" so the operator sees data is flowing.
MAX_ROWS: int = 5

# Column proportions (must sum ≤ 1.0). The remainder is split as a
# soft inter-column gutter.
COL_CONDITION_FRACTION: float = 0.50
COL_METRIC_FRACTION: float = 0.30
COL_STATUS_FRACTION: float = 0.16
COL_GUTTER_FRACTION: float = 1.0 - (
    COL_CONDITION_FRACTION + COL_METRIC_FRACTION + COL_STATUS_FRACTION
)


# ── Data source ─────────────────────────────────────────────────────────


CLAIMS_FILE: Path = Path.home() / "hapax-state" / "research-claims.yaml"

# Map status → palette role (BitchX accent slots) + glyph. The glyph is
# the only ASCII the ward emits; it falls within the BitchX grammar
# without leaning on emoji.
_STATUS_GLYPHS: dict[str, str] = {
    "passing": "+ pass",
    "failing": "x fail",
    "unverified": "? unver",
}
_STATUS_PALETTE_ROLES: dict[str, str] = {
    "passing": "accent_green",
    "failing": "accent_red",
    "unverified": "accent_yellow",
}
_STATUS_FALLBACK_ROLE: str = "muted"
_STATUS_FALLBACK_GLYPH: str = "- ?"


@dataclass(frozen=True)
class ClaimRow:
    """One row of the dashboard grid — one claim observation."""

    condition_id: str
    metric: str
    status: str

    @property
    def status_palette_role(self) -> str:
        return _STATUS_PALETTE_ROLES.get(self.status, _STATUS_FALLBACK_ROLE)

    @property
    def status_glyph(self) -> str:
        return _STATUS_GLYPHS.get(self.status, _STATUS_FALLBACK_GLYPH)


def load_claims(path: Path = CLAIMS_FILE) -> list[ClaimRow]:
    """Read research-claims.yaml. Returns ``[]`` on any failure mode.

    Defensive across:

    * file missing (operator hasn't authored claims yet)
    * PyYAML missing (CI minimal install)
    * malformed YAML
    * unexpected schema (top-level not dict, claims not list, etc.)

    Each loaded entry must carry ``condition_id`` (or ``target_condition``
    accepted as alias), ``metric``, and ``status``. Rows missing any of
    these are skipped — partial schema is operator data-entry error,
    not a ward bug.
    """
    if not path.exists():
        return []
    try:
        import yaml
    except ImportError:
        log.debug("PyYAML unavailable; research claims unread")
        return []
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        log.debug("research-claims.yaml malformed; treating as empty", exc_info=True)
        return []
    if not isinstance(raw, dict):
        return []
    entries = raw.get("claims") or []
    if not isinstance(entries, list):
        return []
    out: list[ClaimRow] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        condition = entry.get("condition_id") or entry.get("target_condition")
        metric = entry.get("metric")
        status = entry.get("status")
        if not (isinstance(condition, str) and isinstance(metric, str) and isinstance(status, str)):
            continue
        out.append(
            ClaimRow(
                condition_id=condition.strip(),
                metric=metric.strip(),
                status=status.strip().lower(),
            )
        )
    return out


# ── Feature flag + cadence ──────────────────────────────────────────────


_FEATURE_FLAG_ENV: str = "HAPAX_LORE_RESEARCH_INSTRUMENT_DASHBOARD_ENABLED"

# 0.5 Hz refresh — claims rarely change in real time; the panel chrome
# is supposed to feel deliberate, not jumpy.
_REFRESH_INTERVAL_S: float = 2.0


def _feature_flag_enabled() -> bool:
    """Read ``HAPAX_LORE_RESEARCH_INSTRUMENT_DASHBOARD_ENABLED``.

    Default OFF — operator flips on after a live visual sign-off so
    the ward doesn't surprise viewers mid-broadcast on first deploy.
    """
    raw = os.environ.get(_FEATURE_FLAG_ENV, "0")
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


# ── Package resolution ──────────────────────────────────────────────────
#
# Two packages drive this ward:
#   - Moksha: outer frame (steel-grey bracket, dim chrome), supplied
#     via ``ENLIGHTENMENT_MOKSHA_PACKAGE``.
#   - BitchX: interior grid (mIRC accents), supplied via the active
#     HomagePackage if BitchX-aligned; otherwise we fall through to the
#     compiled-in BitchX defaults.
#
# Resolution is per-frame so an operator changing the active package
# on the fly is reflected on the next render tick.


def _moksha_package() -> HomagePackage:
    """Always returns the Moksha package — the frame is non-negotiable."""
    from agents.studio_compositor.homage.enlightenment_moksha import (
        ENLIGHTENMENT_MOKSHA_PACKAGE,
    )

    return ENLIGHTENMENT_MOKSHA_PACKAGE


def _bitchx_package() -> HomagePackage:
    """BitchX package for the grid interior.

    Tries the active package first (so a BitchX-aligned active package
    flows through unmodified); falls back to the compiled-in BitchX
    defaults when the active package's grammar doesn't fit grid cells
    (e.g. when Moksha is itself the active package).
    """
    active = get_active_package()
    if active is not None and active.grammar.container_shape != "curly":
        # BitchX uses bracket/chevron container_shape; Moksha uses
        # curly. Active package is BitchX-shaped → use it.
        return active
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


def _resolve(pkg: HomagePackage, role: str) -> tuple[float, float, float, float]:
    """Resolve a palette role on ``pkg`` with a muted fallback."""
    try:
        return pkg.resolve_colour(role)
    except Exception:
        log.debug("palette role %s unresolved on %s", role, pkg.id, exc_info=True)
        return pkg.resolve_colour("muted")


def _font_description(pkg: HomagePackage, size: int, *, bold: bool = False) -> str:
    """Build a Pango font-description string for ``pkg``."""
    weight = " Bold" if bold else ""
    return f"{pkg.typography.primary_font_family}{weight} {int(size)}"


# ── Renderer ────────────────────────────────────────────────────────────


class ResearchInstrumentDashboardCairoSource(HomageTransitionalSource):
    """Hybrid Moksha+BitchX dashboard ward (cc-task keystone).

    Default natural footprint: 540×220 px. Composition:

        Moksha-chrome bordered frame
        ┌──[ research instrument ]─────────────────────────────┐
        │ condition           metric         status            │   ← BitchX header (muted)
        │ cond-A              latency_p50    + pass            │   ← row, accent_green
        │ cond-A              uptime_min     ? unver           │   ← accent_yellow
        │ cond-B              throughput     x fail            │   ← accent_red
        └──────────────────────────────────────────────────────┘

    Frame is Moksha-curly chrome, header + interior text use the
    BitchX-aligned active package. Status glyphs are bracket-grammar
    ASCII — no emoji, fits BitchX grammar.

    The ward renders transparent when the feature flag is off OR
    there is no active research marker AND no claims. Empty state
    with an active marker but zero claims renders the chrome + header
    + the active condition line, no grid — this is correct: it tells
    the viewer "research is configured but no claims are being
    tracked yet."
    """

    source_id: str = "research_instrument_dashboard"

    def __init__(self) -> None:
        super().__init__(source_id=self.source_id)
        self._cached_marker_id: str | None = None
        self._cached_claims: list[ClaimRow] = []
        self._last_refresh_ts: float = 0.0

    def _maybe_refresh(self, now: float) -> None:
        if now - self._last_refresh_ts < _REFRESH_INTERVAL_S:
            return
        try:
            marker = read_marker()
            self._cached_marker_id = marker.condition_id if marker else None
        except Exception:
            log.debug("research_marker read failed", exc_info=True)
            self._cached_marker_id = None
        try:
            self._cached_claims = load_claims()
        except Exception:
            log.debug("research-claims read failed", exc_info=True)
            self._cached_claims = []
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

        # Empty state: no marker, no claims → don't paint at all so the
        # ward doesn't squat on screen with a useless chrome.
        if self._cached_marker_id is None and not self._cached_claims:
            return

        moksha = _moksha_package()
        bitchx = _bitchx_package()

        self._render_frame(cr, canvas_w, canvas_h, moksha)
        self._render_grid(cr, canvas_w, canvas_h, bitchx, moksha)

    def _render_frame(
        self,
        cr: cairo.Context,
        w: int,
        h: int,
        moksha: HomagePackage,
    ) -> None:
        """Outer Moksha-chrome bracket frame + header label."""
        # Soft dark backing — same alpha as Moksha's background colour
        # so the shader surface shows through.
        bg = _resolve(moksha, "background")
        cr.set_source_rgba(*bg)
        cr.rectangle(0, 0, w, h)
        cr.fill()

        # Steel-grey bracket border.
        chrome = _resolve(moksha, "muted")
        cr.set_source_rgba(*chrome)
        cr.set_line_width(FRAME_BORDER_PX)
        cr.rectangle(
            FRAME_BORDER_PX / 2,
            FRAME_BORDER_PX / 2,
            w - FRAME_BORDER_PX,
            h - FRAME_BORDER_PX,
        )
        cr.stroke()

        # Header label — Moksha curly bracket grammar.
        from agents.studio_compositor.text_render import (
            TextStyle,
            measure_text,
            render_text,
        )

        label = "[ research instrument ]"
        header_color = _resolve(moksha, "bright")
        header_font = _font_description(moksha, 13, bold=True)
        style = TextStyle(text=label, font_description=header_font, color_rgba=header_color)
        text_w, text_h = measure_text(cr, style)
        # Centered on top edge, cuts the bracket chrome.
        text_x = (w - text_w) / 2
        text_y = -text_h / 2 + FRAME_BORDER_PX / 2
        # Gap-fill behind the label so the bracket chrome doesn't show
        # through the glyphs.
        cr.set_source_rgba(*bg)
        cr.rectangle(text_x - 6, text_y, text_w + 12, text_h)
        cr.fill()
        render_text(cr, style, x=text_x, y=text_y)

    def _render_grid(
        self,
        cr: cairo.Context,
        w: int,
        h: int,
        bitchx: HomagePackage,
        moksha: HomagePackage,
    ) -> None:
        """Interior BitchX-grid: header row + claim rows."""
        from agents.studio_compositor.text_render import (
            TextStyle,
            render_text,
        )

        inner_x = FRAME_BORDER_PX + FRAME_INNER_PADDING_PX
        inner_y = FRAME_BORDER_PX + FRAME_INNER_PADDING_PX + HEADER_HEIGHT_PX
        inner_w = max(0, w - 2 * inner_x)

        # Render the active condition line under the chrome header.
        # If the marker is missing this resolves to a muted "(no active
        # condition)" — operator-readable empty state.
        active_text = (
            f"active: {self._cached_marker_id}"
            if self._cached_marker_id
            else "(no active research condition)"
        )
        active_color = _resolve(moksha, "terminal_default" if self._cached_marker_id else "muted")
        active_font = _font_description(moksha, 12)
        render_text(
            cr,
            TextStyle(
                text=active_text,
                font_description=active_font,
                color_rgba=active_color,
            ),
            x=inner_x,
            y=inner_y - HEADER_HEIGHT_PX + 4,
        )

        # Column geometry derived from inner_w.
        col_condition_w = inner_w * COL_CONDITION_FRACTION
        col_metric_w = inner_w * COL_METRIC_FRACTION
        gutter = inner_w * COL_GUTTER_FRACTION / 2

        # Header row.
        header_color = _resolve(bitchx, "muted")
        header_font = _font_description(bitchx, 12, bold=True)
        cell_x_condition = inner_x
        cell_x_metric = cell_x_condition + col_condition_w + gutter
        cell_x_status = cell_x_metric + col_metric_w + gutter
        row_y = inner_y
        for x, label in (
            (cell_x_condition, "condition"),
            (cell_x_metric, "metric"),
            (cell_x_status, "status"),
        ):
            render_text(
                cr,
                TextStyle(
                    text=label,
                    font_description=header_font,
                    color_rgba=header_color,
                ),
                x=x,
                y=row_y,
            )

        # Data rows. Truncated to MAX_ROWS; if more exist we add a
        # muted "+N more" hint so the operator sees data is flowing.
        rows = self._cached_claims[:MAX_ROWS]
        overflow = max(0, len(self._cached_claims) - MAX_ROWS)

        condition_color = _resolve(bitchx, "terminal_default")
        metric_color = _resolve(bitchx, "terminal_default")
        cell_font = _font_description(bitchx, 12)

        for i, row in enumerate(rows, start=1):
            row_y = inner_y + i * GRID_ROW_HEIGHT_PX
            if row_y > h - FRAME_BORDER_PX - FRAME_INNER_PADDING_PX:
                # Out of canvas — stop drawing rather than render
                # half a row; layout JSON owns sizing decisions.
                break
            render_text(
                cr,
                TextStyle(
                    text=row.condition_id,
                    font_description=cell_font,
                    color_rgba=condition_color,
                ),
                x=cell_x_condition,
                y=row_y,
            )
            render_text(
                cr,
                TextStyle(
                    text=row.metric,
                    font_description=cell_font,
                    color_rgba=metric_color,
                ),
                x=cell_x_metric,
                y=row_y,
            )
            status_color = _resolve(bitchx, row.status_palette_role)
            render_text(
                cr,
                TextStyle(
                    text=row.status_glyph,
                    font_description=cell_font,
                    color_rgba=status_color,
                ),
                x=cell_x_status,
                y=row_y,
            )

        if overflow > 0:
            footer_y = inner_y + (len(rows) + 1) * GRID_ROW_HEIGHT_PX
            footer_color = _resolve(bitchx, "muted")
            render_text(
                cr,
                TextStyle(
                    text=f"+{overflow} more",
                    font_description=_font_description(bitchx, 11),
                    color_rgba=footer_color,
                ),
                x=inner_x,
                y=footer_y,
            )


__all__ = [
    "CLAIMS_FILE",
    "DEFAULT_NATURAL_H",
    "DEFAULT_NATURAL_W",
    "ClaimRow",
    "ResearchInstrumentDashboardCairoSource",
    "load_claims",
]
