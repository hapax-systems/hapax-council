"""CairoSource protocol — content sources that render via Cairo.

A CairoSource subclass owns the per-tick draw logic for a single Cairo
content type (Sierpinski, AlbumOverlay, OverlayZones, TokenPole, etc.).
The CairoSourceRunner wraps it in a daemon background thread and ticks
at the declared cadence, holding the most recently rendered surface
under a lock for synchronous consumers.

Phase 3b of the compositor unification epic. The runner is the polymorphic
mechanism the GStreamer cairooverlay (synchronous) and future wgpu source-
protocol consumers can both read from.

See: docs/superpowers/specs/2026-04-12-phase-3-executor-polymorphism-design.md
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import cairo

if TYPE_CHECKING:
    from agents.studio_compositor.budget import BudgetTracker

log = logging.getLogger(__name__)


class CairoSource(ABC):
    """Abstract base for Python Cairo content sources.

    Subclasses provide ``render()``. The runner owns the surface
    allocation, the cadence loop, and (optionally) bridges to the
    shared-memory source protocol.
    """

    @abstractmethod
    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Draw into the Cairo context. Called once per tick.

        Implementations should not allocate the underlying surface — the
        runner owns that. Implementations must not retain references to
        the context after returning.
        """

    def state(self) -> dict[str, Any]:
        """Return per-tick state passed into render(). Override if needed.

        Default returns an empty dict — most sources keep their state on
        ``self``. The state hook exists for sources whose render needs to
        snapshot fast-changing inputs (audio energy, slot index, etc.)
        from another thread without locking.
        """
        return {}

    def cleanup(self) -> None:  # noqa: B027 — intentional no-op default
        """Release any resources. Called when the runner stops.

        Default is a no-op. Subclasses can override to flush caches,
        close files, etc.
        """


class CairoSourceRunner:
    """Drives a CairoSource at the declared cadence on a background thread.

    Renders into a Cairo ImageSurface every tick, swaps the cached output
    surface under a lock, and (optionally) pushes the result through the
    shared-memory source protocol so wgpu consumers can sample it.

    Synchronous consumers (e.g. the GStreamer cairooverlay draw callback)
    can read the cached surface via ``get_output_surface()`` for a
    sub-millisecond blit on the streaming thread.
    """

    def __init__(
        self,
        source_id: str,
        source: CairoSource,
        canvas_w: int = 1920,
        canvas_h: int = 1080,
        target_fps: float = 10.0,
        publish_to_source_protocol: bool = False,
        budget_tracker: BudgetTracker | None = None,
        budget_ms: float | None = None,
    ) -> None:
        if target_fps <= 0:
            raise ValueError(f"target_fps must be > 0, got {target_fps}")
        if budget_ms is not None and budget_ms <= 0:
            raise ValueError(f"budget_ms must be > 0 when set, got {budget_ms}")
        self._source_id = source_id
        self._source = source
        self._canvas_w = canvas_w
        self._canvas_h = canvas_h
        self._period = 1.0 / target_fps
        self._publish = publish_to_source_protocol
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._output_surface: cairo.ImageSurface | None = None
        self._output_lock = threading.Lock()
        self._frame_count = 0
        self._last_render_ms = 0.0
        # Phase 7: budget enforcement. Defaults preserve pre-Phase-7
        # behavior — no tracker, no budget, no skips.
        self._budget_tracker = budget_tracker
        self._budget_ms = budget_ms
        self._consecutive_skips = 0

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def last_render_ms(self) -> float:
        return self._last_render_ms

    @property
    def consecutive_skips(self) -> int:
        """Number of consecutive ticks skipped due to over-budget previous frame.

        Reset to zero on the first successful render after a skip
        run. The operator can read this for the source-cost JSON or
        for stimmung gating ("is the stream running degraded?").
        """
        return self._consecutive_skips

    @property
    def degraded(self) -> bool:
        """True iff at least one tick has been skipped in a row.

        Useful as a coarse "is this source struggling" signal for
        operator UIs. The threshold is intentionally low (>= 1) so
        any over-budget event surfaces immediately.
        """
        return self._consecutive_skips > 0

    def set_canvas_size(self, w: int, h: int) -> None:
        """Update the canvas size. Picked up on the next tick."""
        self._canvas_w = w
        self._canvas_h = h

    def get_output_surface(self) -> cairo.ImageSurface | None:
        """Return the most recent rendered surface, or None.

        Thread-safe. Synchronous consumers (cairooverlay callbacks) call
        this from their draw thread and ``cr.set_source_surface(...)``
        the result. The returned surface must not be mutated by the
        caller.
        """
        with self._output_lock:
            return self._output_surface

    def start(self) -> None:
        """Start the background render thread. Idempotent."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"cairo-source-{self._source_id}",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "CairoSourceRunner started: source_id=%s fps=%.1f canvas=%dx%d",
            self._source_id,
            1.0 / self._period,
            self._canvas_w,
            self._canvas_h,
        )

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the loop to exit and join the thread."""
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
        self._thread = None
        try:
            self._source.cleanup()
        except Exception:
            log.debug("CairoSource %s cleanup failed", self._source_id, exc_info=True)

    def tick_once(self) -> None:
        """Render exactly one frame inline. Used by tests and one-shot sources."""
        self._render_one_frame()

    def _loop(self) -> None:
        next_tick = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now < next_tick:
                self._stop.wait(min(next_tick - now, 0.1))
                continue
            next_tick = now + self._period
            self._render_one_frame()

    def _render_one_frame(self) -> None:
        # Phase 7b: skip-if-over-budget. If a budget is configured AND
        # we have a tracker AND the most recent recorded frame for
        # this source exceeded budget, skip this tick. The cached
        # surface from the previous successful render stays in place
        # so synchronous consumers (cairooverlay) keep blitting
        # something valid.
        if (
            self._budget_ms is not None
            and self._budget_tracker is not None
            and self._budget_tracker.over_budget(self._source_id, self._budget_ms)
        ):
            self._budget_tracker.record_skip(self._source_id)
            self._consecutive_skips += 1
            log.debug(
                "CairoSource %s over budget (%.2fms > %.2fms); skipping tick (run=%d)",
                self._source_id,
                self._budget_tracker.last_frame_ms(self._source_id),
                self._budget_ms,
                self._consecutive_skips,
            )
            return

        t0 = time.monotonic()
        try:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self._canvas_w, self._canvas_h)
            cr = cairo.Context(surface)
            self._source.render(
                cr,
                self._canvas_w,
                self._canvas_h,
                t0,
                self._source.state(),
            )
            surface.flush()
        except Exception:
            log.exception("CairoSource %s render failed", self._source_id)
            return

        with self._output_lock:
            self._output_surface = surface
        self._frame_count += 1
        self._last_render_ms = (time.monotonic() - t0) * 1000.0
        # Phase 7a: report this frame's elapsed time to the budget
        # tracker if one is wired up. The tracker is the rolling
        # source of truth for cross-frame stats; _last_render_ms is
        # this thread's instant snapshot.
        if self._budget_tracker is not None:
            self._budget_tracker.record(self._source_id, self._last_render_ms)
        # A successful render clears the consecutive-skip run.
        self._consecutive_skips = 0

        if self._publish:
            self._publish_to_source_protocol(surface)

    def _publish_to_source_protocol(self, surface: cairo.ImageSurface) -> None:
        """Write the surface bytes to the shared-memory source protocol.

        Imported lazily so tests don't need the imagination_source_protocol
        module installed and the source protocol writer can be replaced
        in future phases without churning every CairoSource.
        """
        try:
            from agents.imagination_source_protocol import inject_rgba

            rgba_bytes = bytes(surface.get_data())
            inject_rgba(
                self._source_id,
                rgba_bytes,
                self._canvas_w,
                self._canvas_h,
            )
        except ImportError:
            log.debug(
                "imagination_source_protocol unavailable; CairoSource %s output not published",
                self._source_id,
            )
        except Exception:
            log.debug("CairoSource %s publish failed", self._source_id, exc_info=True)
