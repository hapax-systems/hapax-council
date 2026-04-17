"""Objectives overlay — LRR Phase 8 item 4.

Renders the operator's currently-active research objectives as a Cairo
overlay on the compositor, so the livestream audience can see what
Hapax is oriented toward. Fits the objective-visibility content
programming spec: the stream is the research instrument, and the
research objectives should be *visible* to both the operator and the
audience.

Reads the same vault-native objective files the director loop uses
(``~/Documents/Personal/30-areas/hapax-objectives/obj-*.md``), parsed
through the canonical ``Objective`` Pydantic schema from
``shared.objective_schema``. Active objectives sort by priority then
recency; top N render as a stacked list with title + advancement
hints.

Broadcast-safety: objective titles + advancement hints are safe for
public rendering per operator's LRR framing (objectives are *the
research*). If any objective's ``broadcast_safe`` field is ever set
to False (future Phase 7 integration), the overlay must skip that
entry. Currently: all objectives treated as broadcast-safe.

If the objectives directory is missing or empty, the overlay renders
transparent (no banner).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import cairo

from agents.studio_compositor.cairo_source import CairoSource

log = logging.getLogger(__name__)

DEFAULT_OBJECTIVES_DIR = Path.home() / "Documents" / "Personal" / "30-areas" / "hapax-objectives"
"""Vault path — source of truth for active objectives, shared with the director loop."""

DEFAULT_MAX_VISIBLE = 3
"""Top-N objectives rendered. Beyond 3 → overlay too tall at broadcast res."""


class ObjectivesOverlay(CairoSource):
    """CairoSource rendering active research objectives as a stacked panel.

    ``state()`` reads the vault directory and returns a frozen list of
    objective summaries; ``render()`` draws them. The two-phase pattern
    matches the rest of the compositor's background-thread rendering
    (consistent with ``ResearchMarkerOverlay`` + ``TokenPole``).
    """

    def __init__(
        self,
        *,
        objectives_dir: Path | None = None,
        max_visible: int = DEFAULT_MAX_VISIBLE,
    ) -> None:
        self._objectives_dir = objectives_dir or DEFAULT_OBJECTIVES_DIR
        if max_visible <= 0:
            raise ValueError(f"max_visible must be > 0, got {max_visible}")
        self._max_visible = max_visible

    # ── CairoSource protocol ───────────────────────────────────────────────

    def state(self) -> dict[str, Any]:
        """Snapshot the current active-objective list."""
        return {"objectives": self._read_active_objectives()}

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Draw the stacked panel or clear transparent when no objectives."""
        # Start transparent so stale frames don't linger
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.restore()

        objectives: list[dict[str, Any]] = state.get("objectives") or []
        if not objectives:
            return

        self._draw_panel(cr, canvas_w, canvas_h, objectives)

    # ── Read path ──────────────────────────────────────────────────────────

    def _read_active_objectives(self) -> list[dict[str, Any]]:
        """Load active objectives + sort, return stable list of dicts.

        Swallows any per-file parse failure (best-effort — one bad file
        shouldn't blank the overlay). If the directory itself doesn't
        exist, returns empty list.
        """
        if not self._objectives_dir.exists():
            return []

        try:
            from shared.frontmatter import parse_frontmatter
            from shared.objective_schema import (
                Objective,
                ObjectivePriority,
                ObjectiveStatus,
            )
        except Exception:
            # Missing deps — render nothing rather than crash the thread
            log.debug("objective schema imports failed", exc_info=True)
            return []

        priority_rank = {
            ObjectivePriority.high: 3,
            ObjectivePriority.normal: 2,
            ObjectivePriority.low: 1,
        }

        active: list[Objective] = []
        for path in sorted(self._objectives_dir.glob("obj-*.md")):
            try:
                fm, _body = parse_frontmatter(path)
                if not fm:
                    continue
                obj = Objective(**fm)
                if obj.status == ObjectiveStatus.active:
                    active.append(obj)
            except Exception:
                continue

        if not active:
            return []

        active.sort(
            key=lambda o: (priority_rank[o.priority], -o.opened_at.timestamp()),
            reverse=True,
        )

        summaries: list[dict[str, Any]] = []
        for obj in active[: self._max_visible]:
            summaries.append(
                {
                    "title": obj.title,
                    "priority": obj.priority.value,
                    "activities": list(obj.activities_that_advance),
                }
            )
        return summaries

    # ── Cairo rendering ────────────────────────────────────────────────────

    def _draw_panel(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        objectives: list[dict[str, Any]],
    ) -> None:
        """Render a left-aligned stacked panel of active objectives.

        Layout:
          - Header bar ("Active objectives") at the top of the panel
          - Per-objective row: priority tag + title + advancement hints
          - Semi-opaque dark background (Gruvbox hard dark bg0 / bg1)
        """
        padding = 20
        row_h = 72
        header_h = 40
        panel_w = 560
        panel_h = header_h + row_h * len(objectives) + padding
        # Anchor to top-left; compositor may re-position via its surface layout.
        x, y = padding, padding

        cr.save()

        # Panel background
        cr.set_source_rgba(0.10, 0.10, 0.10, 0.88)
        cr.rectangle(x, y, panel_w, panel_h)
        cr.fill()

        # Yellow accent bar (Gruvbox hard dark bright-yellow)
        cr.set_source_rgba(0.98, 0.74, 0.18, 1.0)
        cr.rectangle(x, y, 4, panel_h)
        cr.fill()

        # Header
        cr.set_source_rgba(0.98, 0.92, 0.78, 1.0)  # fg1
        cr.select_font_face(
            "JetBrainsMono Nerd Font",
            cairo.FONT_SLANT_NORMAL,
            cairo.FONT_WEIGHT_BOLD,
        )
        cr.set_font_size(20)
        cr.move_to(x + 16, y + 28)
        cr.show_text("ACTIVE OBJECTIVES")

        # Rows
        cr.set_font_size(18)
        for i, obj in enumerate(objectives):
            row_y = y + header_h + i * row_h
            # Priority tag (colored pill)
            priority = obj.get("priority", "normal")
            r, g, b = _priority_color(priority)
            cr.set_source_rgba(r, g, b, 1.0)
            cr.rectangle(x + 16, row_y + 12, 80, 24)
            cr.fill()
            cr.set_source_rgba(0.10, 0.10, 0.10, 1.0)  # bg0 text
            cr.select_font_face(
                "JetBrainsMono Nerd Font", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD
            )
            cr.set_font_size(13)
            cr.move_to(x + 24, row_y + 28)
            cr.show_text(priority.upper())

            # Title
            cr.set_source_rgba(0.98, 0.92, 0.78, 1.0)
            cr.select_font_face(
                "JetBrainsMono Nerd Font",
                cairo.FONT_SLANT_NORMAL,
                cairo.FONT_WEIGHT_NORMAL,
            )
            cr.set_font_size(18)
            title = _truncate(obj.get("title", "") or "(untitled)", 48)
            cr.move_to(x + 112, row_y + 32)
            cr.show_text(title)

            # Activities (subtle, comma-joined)
            activities = obj.get("activities") or []
            if activities:
                cr.set_source_rgba(0.66, 0.60, 0.52, 1.0)  # gray1
                cr.set_font_size(14)
                acts_str = _truncate(" • ".join(activities), 60)
                cr.move_to(x + 112, row_y + 54)
                cr.show_text(acts_str)

        cr.restore()


def _priority_color(priority: str) -> tuple[float, float, float]:
    """Map objective priority to pill background color (Gruvbox hard dark palette)."""
    if priority == "high":
        return (0.80, 0.26, 0.11)  # bright-red
    if priority == "normal":
        return (0.98, 0.74, 0.18)  # bright-yellow
    if priority == "low":
        return (0.60, 0.59, 0.10)  # bright-green (dim)
    return (0.50, 0.50, 0.50)


def _truncate(s: str, max_chars: int) -> str:
    """Terse truncation with ellipsis — broadcast width-aware."""
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1].rstrip() + "…"


__all__ = [
    "DEFAULT_MAX_VISIBLE",
    "DEFAULT_OBJECTIVES_DIR",
    "ObjectivesOverlay",
]
