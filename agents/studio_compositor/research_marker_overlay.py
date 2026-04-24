"""Research marker overlay — LRR Phase 2 item 4.

Renders a visible "Condition: <id>" textual overlay in the HLS stream
for approximately ``MARKER_VISIBILITY_SECONDS`` (default 3 s) after
every condition change. The trigger is the Phase 1 research marker
SHM file at ``/dev/shm/hapax-compositor/research-marker.json`` whose
``written_at`` field is updated by ``scripts/research-registry.py``
on every ``init``, ``open``, and ``close`` invocation.

The overlay is a ``CairoSource`` so it plugs into the existing
compositor rendering cadence. It renders into a 1920x120 strip at
the top-right of the main canvas (the compositor places it at its
assigned surface geometry). When the marker is stale the overlay
renders transparently so the streaming thread can skip the blit.

ytb-LORE-MVP PR C (2026-04-24, delta) — optional context subtext. When
``HAPAX_LORE_RESEARCH_MARKER_CONTEXT_ENABLED=1`` is set, the banner
grows two additional Px437 lines underneath the primary marker row
reporting the current sprint day + measures progress + next-block
title pulled from ``/dev/shm/hapax-sprint/state.json``. The feature
flag defaults OFF so the shipped 3 s banner shape is preserved for
operators who haven't opted in. The fade-in / fade-out envelope
continues to be governed by the existing ``visibility_seconds``
window (default 3 s); the context rows surface only while the marker
itself is visible, then vanish with it.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cairo

from agents.studio_compositor.homage.transitional_source import HomageTransitionalSource

MARKER_VISIBILITY_SECONDS = 3.0
"""How long the overlay stays visible after a marker update."""

DEFAULT_MARKER_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")
"""Phase 1 SHM injection target. Never hard-code elsewhere."""

DEFAULT_SPRINT_STATE_PATH = Path("/dev/shm/hapax-sprint/state.json")
"""Sprint state written by the sprint-tracker timer; cheap re-read path."""

CONTEXT_FEATURE_FLAG_ENV = "HAPAX_LORE_RESEARCH_MARKER_CONTEXT_ENABLED"
"""When truthy (1/true/yes/on), the banner renders the sprint/context subtext."""

log = logging.getLogger(__name__)


def _context_enabled() -> bool:
    """Return True if ``HAPAX_LORE_RESEARCH_MARKER_CONTEXT_ENABLED`` is truthy."""
    raw = os.environ.get(CONTEXT_FEATURE_FLAG_ENV, "0")
    return raw.strip().lower() not in ("", "0", "false", "no", "off")


def _read_sprint_state(path: Path) -> dict[str, Any] | None:
    """Load sprint state.json; ``None`` on any failure so render can fall back."""
    try:
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return None
        return payload
    except (OSError, json.JSONDecodeError):
        log.debug("research-marker: sprint state unavailable", exc_info=True)
        return None


def _format_sprint_line(state: dict[str, Any]) -> str | None:
    """Render the single sprint-progress line, or ``None`` if required fields missing."""
    sprint = state.get("current_sprint")
    day = state.get("current_day")
    completed = state.get("measures_completed")
    total = state.get("measures_total")
    if sprint is None or day is None or completed is None or total is None:
        return None
    return f"sprint {sprint} · day {day}  {completed}/{total} measures"


def _format_next_block_line(state: dict[str, Any]) -> str | None:
    """Render a compact ``next: <measure> <title>`` line, or ``None`` if absent."""
    block = state.get("next_block")
    if not isinstance(block, dict):
        return None
    measure = block.get("measure")
    title = block.get("title")
    if not title:
        return None
    if measure:
        return f"next: [{measure}] {title}"
    return f"next: {title}"


class ResearchMarkerOverlay(HomageTransitionalSource):
    """HomageTransitionalSource that renders the active condition ID for ~3s after a change.

    Each tick reads the marker file, checks whether the last
    ``written_at`` falls within the visibility window, and either
    draws the overlay or clears the canvas to fully transparent.
    """

    def __init__(
        self,
        *,
        marker_path: Path | None = None,
        visibility_seconds: float = MARKER_VISIBILITY_SECONDS,
        now_fn: Any = None,
        sprint_state_path: Path | None = None,
    ) -> None:
        super().__init__(source_id="research_marker_overlay")
        self._marker_path = marker_path or DEFAULT_MARKER_PATH
        if visibility_seconds <= 0:
            raise ValueError(f"visibility_seconds must be > 0, got {visibility_seconds}")
        self._visibility_seconds = visibility_seconds
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._last_rendered_condition: str | None = None
        # ytb-LORE-MVP PR C — sprint-state path is injection-testable.
        # Read-path failures degrade to "no context rows rendered",
        # never raise; the marker itself keeps its legacy shape.
        self._sprint_state_path = sprint_state_path or DEFAULT_SPRINT_STATE_PATH

    def state(self) -> dict[str, Any]:
        """Snapshot the marker state so render() has a coherent view."""
        return self._read_marker()

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Draw the overlay if the marker is fresh; otherwise clear transparent."""
        # Always start with a transparent clear so stale frames don't bleed.
        cr.save()
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.restore()

        if not state.get("visible"):
            return

        condition_id = state.get("condition_id") or ""
        if not condition_id:
            return

        self._draw_banner(cr, canvas_w, canvas_h, condition_id)

    def _read_marker(self) -> dict[str, Any]:
        """Load marker state. Returns ``{"visible": False}`` on any failure."""
        if not self._marker_path.exists():
            return {"visible": False, "reason": "marker file absent"}
        try:
            raw = self._marker_path.read_text(encoding="utf-8")
        except OSError as exc:
            log.debug("research-marker read failed: %s", exc)
            return {"visible": False, "reason": "read error"}

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {"visible": False, "reason": "invalid json"}

        if not isinstance(payload, dict):
            return {"visible": False, "reason": "unexpected payload type"}

        condition_id = payload.get("condition_id")
        written_at_raw = payload.get("written_at")
        if not condition_id or not written_at_raw:
            return {"visible": False, "reason": "missing required fields"}

        written_at = _parse_iso_utc(written_at_raw)
        if written_at is None:
            return {"visible": False, "reason": "unparseable written_at"}

        now = self._now_fn()
        age_seconds = (now - written_at).total_seconds()
        visible = 0.0 <= age_seconds <= self._visibility_seconds
        return {
            "visible": visible,
            "condition_id": condition_id,
            "age_seconds": age_seconds,
            "written_at": written_at_raw,
        }

    def _draw_banner(
        self, cr: cairo.Context, canvas_w: int, canvas_h: int, condition_id: str
    ) -> None:
        """Render the research-marker banner emissively.

        Phase A4: Gruvbox ground + point-of-light glyphs over a
        ``>>> [RESEARCH MARKER] <HH:MM:SS>`` Px437 line via Pango. The
        condition id renders as an emissive glyph row above the main
        line so the marker reads as both timestamp and id.

        PR C: when ``HAPAX_LORE_RESEARCH_MARKER_CONTEXT_ENABLED=1`` the
        banner grows a 32-px subtext band carrying sprint progress +
        next-block title. The core 64-px band (glyphs + main line) is
        positioned identically in both states so the shipped golden
        image stays valid when the flag is off.
        """
        from agents.studio_compositor.homage.emissive_base import (
            GRUVBOX_BG0,
            paint_emissive_bg,
            paint_emissive_point,
        )
        from agents.studio_compositor.homage.rendering import (
            active_package,
            select_bitchx_font_pango,
        )
        from agents.studio_compositor.text_render import TextStyle, render_text

        context_on = _context_enabled()
        core_h = 64
        context_h = 32
        banner_h = core_h + (context_h if context_on else 0)
        banner_w = canvas_w
        padding = 16

        # Ground — Gruvbox bg0 via the shared emissive helper so the
        # ward reads as part of the HOMAGE surface.
        paint_emissive_bg(cr, banner_w, banner_h, ground_rgba=GRUVBOX_BG0)

        try:
            pkg = active_package()
            accent_rgba = pkg.resolve_colour("accent_yellow")
            content_rgba = pkg.resolve_colour(pkg.grammar.content_colour_role)
            muted_rgba = pkg.resolve_colour(pkg.grammar.punctuation_colour_role)
            font_desc = select_bitchx_font_pango(cr, 20, bold=True)
        except Exception:
            accent_rgba = (0.98, 0.74, 0.18, 1.0)
            content_rgba = (0.98, 0.92, 0.78, 1.0)
            muted_rgba = (0.55, 0.55, 0.55, 1.0)
            font_desc = "Px437 IBM VGA 8x16 20"

        # Condition-id glyph row — emissive points with per-char phase so
        # the id reads as a row of lanterns. Positioned above the main
        # text line. Phase is driven by the overlay's injected ``now_fn``
        # so the test harness can pin determinism.
        now_wall = self._now_fn()
        try:
            t_phase = float(now_wall.timestamp())
        except Exception:
            t_phase = 0.0
        glyph_y = int(core_h * 0.28)
        glyph_spacing = 12
        for i, _ch in enumerate(condition_id[:40]):
            cx = padding + i * glyph_spacing
            paint_emissive_point(
                cr,
                cx,
                glyph_y,
                accent_rgba,
                t=t_phase,
                phase=i * 0.21,
                baseline_alpha=0.85,
                centre_radius_px=2.0,
                halo_radius_px=4.5,
                outer_glow_radius_px=6.5,
            )

        # Main Px437 line — ``>>> [RESEARCH MARKER] <HH:MM:SS>``. The
        # marker chevron stays in the muted role so the identity colour
        # belongs to the timestamp.
        now = self._now_fn()
        timestamp = now.strftime("%H:%M:%S") if hasattr(now, "strftime") else ""
        body_text = f">>> [RESEARCH MARKER] {timestamp}  [{condition_id}]"
        body_style = TextStyle(
            text=body_text,
            font_description=font_desc,
            color_rgba=content_rgba,
        )
        render_text(cr, body_style, x=padding, y=int(core_h * 0.50))

        if context_on:
            state = _read_sprint_state(self._sprint_state_path)
            if state is not None:
                try:
                    context_font = select_bitchx_font_pango(cr, 14, bold=False)
                except Exception:
                    context_font = "Px437 IBM VGA 8x16 14"
                sprint_line = _format_sprint_line(state)
                next_line = _format_next_block_line(state)
                if sprint_line:
                    render_text(
                        cr,
                        TextStyle(
                            text=sprint_line,
                            font_description=context_font,
                            color_rgba=muted_rgba,
                        ),
                        x=padding,
                        y=core_h + 2,
                    )
                if next_line:
                    render_text(
                        cr,
                        TextStyle(
                            text=next_line,
                            font_description=context_font,
                            color_rgba=muted_rgba,
                        ),
                        x=padding,
                        y=core_h + 16,
                    )

        # Muted 1-px baseline stroke at the foot of the banner, echoing
        # the accent-bar role from the prior design.
        mr, mg, mb, _ = muted_rgba
        cr.save()
        cr.set_source_rgba(mr, mg, mb, 0.55)
        cr.rectangle(0, banner_h - 2, banner_w, 1)
        cr.fill()
        cr.restore()


def _parse_iso_utc(value: str) -> datetime | None:
    """Parse an ISO8601 UTC timestamp, tolerating both ``Z`` and ``+00:00``."""
    if not isinstance(value, str):
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


__all__ = [
    "CONTEXT_FEATURE_FLAG_ENV",
    "DEFAULT_MARKER_PATH",
    "DEFAULT_SPRINT_STATE_PATH",
    "MARKER_VISIBILITY_SECONDS",
    "ResearchMarkerOverlay",
]
