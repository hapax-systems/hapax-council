"""ResearchMarkerFrameSource — 3s fullscreen overlay on condition transitions.

LRR Phase 2 item 4 (spec §3.4). A ``CairoSource`` subclass that watches
``/dev/shm/hapax-compositor/research-marker.json`` for condition changes
and, on each change, renders a high-opacity fullscreen banner announcing
the new ``condition_id`` for ~3 seconds. After the 3-second window, the
source renders transparent (no-op) until the next change.

The goal is **frame-accurate boundary detection** in the archived HLS
stream: a reviewer scrubbing through the archive can see a large
"CONDITION CHANGE → <condition_id>" overlay exactly at the moment the
research registry transitioned, without consulting an out-of-band log.

Implementation notes:

- **Change detection uses epoch polling, not inotify.** The marker
  file's ``epoch`` field is incremented on every ``write_marker`` call
  (see ``shared/research_marker``). Polling is simpler than inotify and
  the cost is negligible: the source's ``render`` runs at the existing
  ``CairoSourceRunner`` cadence (typically 10 fps), and ``read_marker``
  reads a small JSON file from ``/dev/shm``. No extra threads, no
  watcher lifecycle to manage.
- **Fallback when marker is missing or stale** — the source renders
  transparent (nothing drawn). A missing marker means no active
  condition, which is not a transition, so no banner fires.
- **3-second window** is measured from the first render tick that
  observed the new epoch, using the ``t`` argument passed by the runner.
  Wall-clock would work too but ``t`` is monotonic and avoids clock
  skew between the runner and the marker writer.
- **Registration** — HSEA Phase 1 will register a higher-priority
  source for ``condition_transition_banner`` zone; this Phase 2 source
  registers at priority 1000 (top override) so any future override has
  to beat it explicitly. Note that the Phase 2 item 10b zone catalog
  also declares ``condition_transition_banner`` with priority 1000 +
  null default source; this module registers the concrete class that
  fills that declaration.

Spec: docs/superpowers/specs/2026-04-15-lrr-phase-2-archive-research-instrument-design.md §3.4
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage.transitional_source import (
    HomageTransitionalSource,
    TransitionState,
)
from shared.research_marker import MarkerState, read_marker

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

BANNER_VISIBLE_SECONDS = 3.0
"""How long the condition-change banner stays visible after a transition."""

BANNER_OPACITY = 0.88
"""High but not opaque — livestream underneath is still dimly visible."""

BANNER_BG_COLOR = (0.08, 0.08, 0.12)
"""Dark cool background for the banner. RGB 0..1."""

BANNER_ACCENT_COLOR = (1.0, 0.42, 0.0)
"""Accent stripe at the top + bottom of the banner. Orange for contrast."""

BANNER_TEXT_COLOR = (0.96, 0.96, 0.96)
"""Off-white text color."""

HEADER_FONT_SIZE_RATIO = 0.045
"""Header font size as a fraction of canvas height."""

CONDITION_FONT_SIZE_RATIO = 0.065
"""condition_id font size as a fraction of canvas height — larger so the
reviewer can read the id from a scrubbed frame."""


class ResearchMarkerFrameSource(HomageTransitionalSource):
    """HOMAGE Phase 11c-batch-3 — 3s research-condition banner ward.

    Renders a high-opacity fullscreen banner announcing the new
    ``condition_id`` for ~3 seconds after a research-marker transition,
    then renders transparent until the next change. Migrated to inherit
    :class:`HomageTransitionalSource` so the banner participates in the
    FSM — the banner is ward-scope content (a text overlay), not chrome,
    and should honour package grammar once ``HAPAX_HOMAGE_ACTIVE=1``.

    Internal state:
        ``_last_epoch`` — the most recent epoch observed from the marker.
            None until the first read. Updated on every transition.
        ``_banner_start_t`` — the runner-supplied monotonic time at which
            the current banner started rendering. None when no banner is
            active.
        ``_banner_condition_id`` — the condition_id being displayed by
            the active banner.
    """

    def __init__(self) -> None:
        # Banner is conditional content (active only for 3s after a
        # research-marker transition). ``HOLD`` is the natural initial
        # state because render_content is self-gating via the banner
        # visibility window — the choreographer doesn't need to toggle
        # the banner in/out, it just applies package grammar if active.
        super().__init__(
            source_id="research_marker_frame",
            initial_state=TransitionState.HOLD,
        )
        self._last_epoch: int | None = None
        self._banner_start_t: float | None = None
        self._banner_condition_id: str | None = None

    def _poll_marker(self) -> MarkerState | None:
        """Safe wrapper around ``read_marker`` — never raises."""
        try:
            return read_marker()
        except Exception:  # pragma: no cover — defensive
            log.exception("research-marker read failed; treating as missing")
            return None

    def _check_for_transition(self, current_t: float) -> None:
        """Poll the marker + start a new banner if the epoch advanced."""
        state = self._poll_marker()
        if state is None:
            if self._last_epoch is not None:
                log.debug("research-marker went missing; clearing stored epoch")
                self._last_epoch = None
            return

        if self._last_epoch is None:
            # First observation — initialize without firing a banner.
            # Firing on first observation would overlay the banner on
            # every compositor restart, which is visual noise, not a
            # real transition signal.
            self._last_epoch = state.epoch
            return

        if state.epoch != self._last_epoch:
            # Transition detected. Start the banner.
            log.info(
                "research-marker transition: epoch %d → %d, condition_id=%s",
                self._last_epoch,
                state.epoch,
                state.condition_id,
            )
            self._last_epoch = state.epoch
            self._banner_start_t = current_t
            self._banner_condition_id = state.condition_id

    def _banner_is_visible(self, current_t: float) -> bool:
        if self._banner_start_t is None:
            return False
        elapsed = current_t - self._banner_start_t
        return 0 <= elapsed < BANNER_VISIBLE_SECONDS

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        # Check for new transitions each tick. This runs at the existing
        # CairoSourceRunner cadence (typically 10 fps) so the detection
        # latency is one tick period, well under the 3-second banner
        # window.
        self._check_for_transition(t)

        if not self._banner_is_visible(t):
            return  # No banner; render is a no-op.

        # Draw a centered banner occupying the middle vertical third.
        banner_h = int(canvas_h * 0.34)
        banner_y = (canvas_h - banner_h) // 2

        # Background rectangle
        cr.save()
        cr.set_source_rgba(
            BANNER_BG_COLOR[0],
            BANNER_BG_COLOR[1],
            BANNER_BG_COLOR[2],
            BANNER_OPACITY,
        )
        cr.rectangle(0, banner_y, canvas_w, banner_h)
        cr.fill()
        cr.restore()

        # Top + bottom accent stripes
        stripe_h = max(4, int(banner_h * 0.03))
        cr.save()
        cr.set_source_rgba(
            BANNER_ACCENT_COLOR[0],
            BANNER_ACCENT_COLOR[1],
            BANNER_ACCENT_COLOR[2],
            BANNER_OPACITY,
        )
        cr.rectangle(0, banner_y, canvas_w, stripe_h)
        cr.fill()
        cr.rectangle(0, banner_y + banner_h - stripe_h, canvas_w, stripe_h)
        cr.fill()
        cr.restore()

        # Header text
        header_text = "CONDITION CHANGE"
        header_font_size = max(12, int(canvas_h * HEADER_FONT_SIZE_RATIO))
        cr.save()
        cr.set_source_rgba(
            BANNER_TEXT_COLOR[0],
            BANNER_TEXT_COLOR[1],
            BANNER_TEXT_COLOR[2],
            BANNER_OPACITY,
        )
        cr.select_font_face("sans", 0, 1)  # 0=normal slant, 1=bold
        cr.set_font_size(header_font_size)
        header_ext = cr.text_extents(header_text)
        header_x = (canvas_w - header_ext.width) / 2
        header_y = banner_y + int(banner_h * 0.38)
        cr.move_to(header_x, header_y)
        cr.show_text(header_text)
        cr.restore()

        # condition_id text (larger, more prominent)
        condition_text = self._banner_condition_id or "(unknown)"
        condition_font_size = max(16, int(canvas_h * CONDITION_FONT_SIZE_RATIO))
        cr.save()
        cr.set_source_rgba(
            BANNER_TEXT_COLOR[0],
            BANNER_TEXT_COLOR[1],
            BANNER_TEXT_COLOR[2],
            BANNER_OPACITY,
        )
        cr.select_font_face("monospace", 0, 1)
        cr.set_font_size(condition_font_size)
        cond_ext = cr.text_extents(condition_text)
        cond_x = (canvas_w - cond_ext.width) / 2
        cond_y = banner_y + int(banner_h * 0.72)
        cr.move_to(cond_x, cond_y)
        cr.show_text(condition_text)
        cr.restore()
