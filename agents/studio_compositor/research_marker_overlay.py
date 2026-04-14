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
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cairo

from agents.studio_compositor.cairo_source import CairoSource

MARKER_VISIBILITY_SECONDS = 3.0
"""How long the overlay stays visible after a marker update."""

DEFAULT_MARKER_PATH = Path("/dev/shm/hapax-compositor/research-marker.json")
"""Phase 1 SHM injection target. Never hard-code elsewhere."""

log = logging.getLogger(__name__)


class ResearchMarkerOverlay(CairoSource):
    """Cairo source that renders the active condition ID for ~3s after a change.

    The render function is called every tick by ``CairoSourceRunner`` on
    a background thread. Each tick reads the marker file, checks whether
    the last ``written_at`` falls within the visibility window, and
    either draws the overlay or clears the canvas to fully transparent.
    """

    def __init__(
        self,
        *,
        marker_path: Path | None = None,
        visibility_seconds: float = MARKER_VISIBILITY_SECONDS,
        now_fn: Any = None,
    ) -> None:
        self._marker_path = marker_path or DEFAULT_MARKER_PATH
        if visibility_seconds <= 0:
            raise ValueError(f"visibility_seconds must be > 0, got {visibility_seconds}")
        self._visibility_seconds = visibility_seconds
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._last_rendered_condition: str | None = None

    def state(self) -> dict[str, Any]:
        """Snapshot the marker state so render() has a coherent view."""
        return self._read_marker()

    def render(
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
        """Render a high-contrast banner at the top of the canvas."""
        banner_h = 64
        banner_w = canvas_w
        padding = 16

        # Semi-opaque dark background (Gruvbox hard dark bg0)
        cr.save()
        cr.set_source_rgba(0.10, 0.10, 0.10, 0.85)
        cr.rectangle(0, 0, banner_w, banner_h)
        cr.fill()

        # High-contrast accent bar along the bottom of the banner
        cr.set_source_rgba(0.98, 0.74, 0.18, 1.0)  # Gruvbox yellow
        cr.rectangle(0, banner_h - 4, banner_w, 4)
        cr.fill()

        # Text
        cr.set_source_rgba(0.98, 0.92, 0.78, 1.0)  # Gruvbox fg1
        cr.select_font_face(
            "JetBrainsMono Nerd Font",
            cairo.FONT_SLANT_NORMAL,
            cairo.FONT_WEIGHT_BOLD,
        )
        cr.set_font_size(28)
        text = f"RESEARCH CONDITION: {condition_id}"
        _, _, text_w, text_h, _, _ = cr.text_extents(text)
        cr.move_to(padding, banner_h / 2 + text_h / 2 - 2)
        cr.show_text(text)

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
    "MARKER_VISIBILITY_SECONDS",
    "DEFAULT_MARKER_PATH",
    "ResearchMarkerOverlay",
]
