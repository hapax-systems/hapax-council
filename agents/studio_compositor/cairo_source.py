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

from agents.studio_compositor.gst_appsrc_limits import configure_live_appsrc_queue

if TYPE_CHECKING:
    from agents.studio_compositor.budget import BudgetTracker

log = logging.getLogger(__name__)


# Task #122 — Gruvbox-dark background for the fallback degraded hold
# frame when a source has no cached last-good surface to replay. Chosen
# from ``docs/logos-design-language.md`` §3.1 (Gruvbox Hard Dark ``bg0``
# = ``#1d2021``) so the idle surface matches the operator's R&D palette
# rather than stark black.
_GRUVBOX_BG0_RGB: tuple[float, float, float] = (0x1D / 255.0, 0x20 / 255.0, 0x21 / 255.0)


def _degraded_mode_active() -> bool:
    """Hot-path DEGRADED check for cairo source runners (task #122).

    Lazy import so test envs without the metrics registry can still
    instantiate a runner.
    """
    try:
        from agents.studio_compositor.degraded_mode import get_controller

        return get_controller().is_active()
    except Exception:
        log.debug("degraded-mode check failed in cairo_source", exc_info=True)
        return False


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
        natural_w: int | None = None,
        natural_h: int | None = None,
    ) -> None:
        if target_fps <= 0:
            raise ValueError(f"target_fps must be > 0, got {target_fps}")
        if budget_ms is not None and budget_ms <= 0:
            raise ValueError(f"budget_ms must be > 0 when set, got {budget_ms}")
        self._source_id = source_id
        self._source = source
        self._canvas_w = canvas_w
        self._canvas_h = canvas_h
        # Source-registry epic PR 1: natural_w/natural_h decouple render
        # resolution from canvas dimensions. A source declares its natural
        # content size (e.g. 300×300 for TokenPole, 640×360 for reverie),
        # the runner allocates the render surface at that size, and the
        # compositor places it at the assigned SurfaceSchema.geometry via
        # scale-on-blit. Defaults to canvas dims for backward compat so
        # existing callers (including set_canvas_size users) keep working
        # unchanged — we track whether natural was explicitly set so that
        # set_canvas_size() can update natural dims only for implicit cases.
        self._natural_explicit = natural_w is not None or natural_h is not None
        self._natural_w = natural_w if natural_w is not None else canvas_w
        self._natural_h = natural_h if natural_h is not None else canvas_h
        self._period = 1.0 / target_fps
        self._publish = publish_to_source_protocol
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._output_surface: cairo.ImageSurface | None = None
        self._output_lock = threading.Lock()
        # A+ Stage 3 (2026-04-17): double-buffered ImageSurface reuse.
        # Before: the render loop allocated a fresh cairo.ImageSurface
        # on every tick (natural_w × natural_h × 4 bytes). Across 23
        # sources at 2-30 fps each, allocation churn on the Cairo +
        # Python + libc allocator paths was measurable in vmstat and
        # held the GIL on allocation. Now: two pre-allocated surfaces
        # per runner; the render loop CLEARs + renders into the
        # inactive one, then atomically swaps the output pointer under
        # _output_lock. The active surface (what the streaming-thread
        # cairooverlay callback reads) is never mutated mid-blit.
        # Surfaces are (re)allocated only when natural_w / natural_h
        # change via set_canvas_size for implicit-natural sources.
        self._surfaces: list[cairo.ImageSurface] = []
        self._surface_active_idx = 0
        self._surface_dims: tuple[int, int] = (0, 0)
        self._frame_count = 0
        self._last_render_ms = 0.0
        # Phase C1 (homage-completion-plan §2): per-ward render cadence
        # gauge. We retain the monotonic timestamp of the previous
        # successful render and compute ``1.0 / (now - prev)`` after
        # every subsequent successful render. ``None`` until the first
        # render — the gauge stays unpublished until we have a real
        # interval measurement rather than emitting a fabricated value.
        self._last_successful_render_at: float | None = None
        # Phase 7: budget enforcement. Defaults preserve pre-Phase-7
        # behavior — no tracker, no budget, no skips.
        self._budget_tracker = budget_tracker
        self._budget_ms = budget_ms
        self._consecutive_skips = 0
        # Phase 6 (source-registry epic H23): lazy GStreamer appsrc for
        # the main-layer path. Built on first ``gst_appsrc()`` call and
        # reused for every successful render-tick push. Stays None if
        # GStreamer isn't importable (unit tests without gi).
        self._gst_appsrc: Any = None
        # Post-epic audit Phase 1 finding #3: Phase 8 wired
        # FreshnessGauge into imagination_loop and ShmRgbaReader but
        # not into CairoSourceRunner, leaving AC-10
        # ("compositor_source_frame_age_seconds for every registered
        # source") unsatisfied for cairo sources. The gauge is built
        # eagerly so every runner (token_pole, album, stream_overlay,
        # sierpinski) exposes a heartbeat metric named after its
        # source id.
        try:
            from shared.freshness_gauge import FreshnessGauge

            # The compositor's /metrics HTTP server at :9482 uses a
            # custom CollectorRegistry (``metrics.REGISTRY``). Passing
            # it through here is what makes the cairo source gauges
            # scrape-visible — without it the metrics register to the
            # default prometheus_client REGISTRY and never appear on
            # the exporter. This fix also extends to the
            # ``compositor_publish_{costs,degraded}`` gauges in
            # ``budget.py`` / ``budget_signal.py``.
            try:
                from agents.studio_compositor.metrics import (
                    REGISTRY as _COMPOSITOR_METRICS_REGISTRY,
                )
            except ImportError:
                _COMPOSITOR_METRICS_REGISTRY = None

            # Base name is ``compositor_source_frame_{id}`` — FreshnessGauge
            # appends ``_published_total`` / ``_failed_total`` / ``_age_seconds``
            # suffixes, yielding the three metrics the AC requires.
            #
            # Livestream-performance-map Sprint 2 F5: Prometheus metric names
            # must match ``[a-z_][a-z0-9_]*``. Source ids with hyphens
            # (``overlay-zones``, ``sierpinski-lines``, and any future
            # ``brio-operator`` / ``c920-desk`` style camera source) would
            # otherwise raise ``ValueError`` at FreshnessGauge construction
            # and silently disable observability for the affected source —
            # the failure would be caught by the outer ``except`` below and
            # only log a warning at startup. Substitute ``-`` → ``_`` so
            # every registered source gets a live gauge. The raw source id
            # is preserved on ``self._source_id`` for logging and lookups.
            _metric_suffix = source_id.replace("-", "_")
            self._freshness_gauge = FreshnessGauge(
                name=f"compositor_source_frame_{_metric_suffix}",
                expected_cadence_s=self._period,
                registry=_COMPOSITOR_METRICS_REGISTRY,
            )
        except Exception:
            log.warning(
                "FreshnessGauge unavailable for cairo source %s; continuing without metric",
                source_id,
                exc_info=True,
            )
            self._freshness_gauge = None

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
        """Update the canvas size. Picked up on the next tick.

        If the runner was constructed without explicit ``natural_w``/``natural_h``,
        the natural dims were auto-derived from canvas and are updated too so
        legacy callers that use ``set_canvas_size`` to resize the output continue
        to work. If natural dims were set explicitly at construction, they are
        left alone (the source declares its own content resolution).

        A+ Stage 3 audit fix (2026-04-17): dimension writes are taken
        under ``_output_lock`` so the render loop cannot observe a
        torn (old_w, new_h) mid-update. The render loop reads both
        dimensions inside the same lock acquisition block so the
        allocation decision sees a consistent pair.
        """
        with self._output_lock:
            self._canvas_w = w
            self._canvas_h = h
            if not self._natural_explicit:
                self._natural_w = w
                self._natural_h = h

    def get_output_surface(self) -> cairo.ImageSurface | None:
        """Return the most recent rendered surface, or None.

        Thread-safe. Synchronous consumers (cairooverlay callbacks) call
        this from their draw thread and ``cr.set_source_surface(...)``
        the result. The returned surface must not be mutated by the
        caller.
        """
        with self._output_lock:
            return self._output_surface

    # ``get_current_surface`` is the ``SourceBackend`` protocol contract
    # that :class:`~agents.studio_compositor.source_registry.SourceRegistry`
    # depends on. Alias the existing ``get_output_surface`` so cairo
    # backends satisfy the protocol without requiring callers of the
    # legacy facade method to change.
    def get_current_surface(self) -> cairo.ImageSurface | None:
        """Alias of :meth:`get_output_surface` for the SourceBackend protocol."""
        return self.get_output_surface()

    def gst_appsrc(self) -> Any:
        """Return (or lazily create) a GStreamer appsrc element for this source.

        Phase 6 (parent task H23). The element is configured with the
        source's natural width/height and BGRA caps (cairo FORMAT_ARGB32
        is little-endian BGRA on every target we care about). Consumers
        call this once at pipeline construction time; the runner pushes
        buffers into the element from its render thread on every
        successful tick.

        Returns ``None`` if GStreamer isn't importable in the current
        environment (e.g. unit-test sandboxes without ``gi``) — callers
        should treat ``None`` as "this source has no main-layer pad in
        this process" and skip main-layer wiring for it.
        """
        if self._gst_appsrc is not None:
            return self._gst_appsrc
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst  # type: ignore[import-not-found]
        except (ImportError, ValueError):
            log.debug("CairoSourceRunner %s: gst_appsrc unavailable (no gi)", self._source_id)
            return None
        Gst.init(None)
        elem = Gst.ElementFactory.make("appsrc", f"appsrc-{self._source_id}")
        if elem is None:
            return None
        caps = Gst.Caps.from_string(
            f"video/x-raw,format=BGRA,width={self._natural_w},"
            f"height={self._natural_h},framerate=0/1"
        )
        elem.set_property("caps", caps)
        elem.set_property("format", Gst.Format.TIME)
        elem.set_property("is-live", True)
        elem.set_property("do-timestamp", True)
        configure_live_appsrc_queue(elem)
        self._gst_appsrc = elem
        log.info(
            "CairoSourceRunner %s: gst_appsrc created (%dx%d BGRA)",
            self._source_id,
            self._natural_w,
            self._natural_h,
        )
        return elem

    def _push_buffer_to_appsrc(self, surface: cairo.ImageSurface) -> None:
        """Push the latest rendered surface into the lazy appsrc, if built."""
        appsrc = self._gst_appsrc
        if appsrc is None:
            return
        try:
            import gi

            gi.require_version("Gst", "1.0")
            from gi.repository import Gst  # type: ignore[import-not-found]
        except (ImportError, ValueError):
            return
        try:
            data = bytes(surface.get_data())
            buf = Gst.Buffer.new_wrapped(data)
            appsrc.emit("push-buffer", buf)
        except Exception:
            log.debug(
                "CairoSourceRunner %s: push-buffer failed",
                self._source_id,
                exc_info=True,
            )

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

    def _render_degraded_hold(self) -> None:
        """Task #122: hold the last-good surface (or paint Gruvbox-dark fallback).

        Behavior:

        - If a cached ``_output_surface`` exists: do nothing. Synchronous
          consumers keep blitting the cached surface so the stream
          visually freezes on the last-good frame instead of showing the
          partial/broken state the source would produce mid-live-change.
        - If no cache exists: allocate (or reuse) the inactive
          double-buffered surface, paint Gruvbox-dark bg0, and publish
          it. Never calls ``self._source.render()``.

        The freshness gauge is marked ``failed`` in both branches so
        ``age_seconds()`` climbs during the hold — the operator-visible
        "stream is degraded" signal mirrors the internal state rather
        than looking healthy while actually frozen.
        """
        if self._output_surface is not None:
            if self._freshness_gauge is not None:
                self._freshness_gauge.mark_failed()
            try:
                from agents.studio_compositor.degraded_mode import get_controller

                get_controller().record_hold(f"cairo_source:{self._source_id}")
            except Exception:
                log.debug("degraded hold record failed", exc_info=True)
            return

        # No cache yet — render a Gruvbox-dark solid fill as the
        # fallback last-good frame.
        try:
            with self._output_lock:
                dims = (self._natural_w, self._natural_h)
                active_idx = self._surface_active_idx
            if self._surface_dims != dims or len(self._surfaces) < 2:
                self._surfaces = [
                    cairo.ImageSurface(cairo.FORMAT_ARGB32, dims[0], dims[1]) for _ in range(2)
                ]
                active_idx = 0
                with self._output_lock:
                    self._surface_active_idx = 0
                self._surface_dims = dims
            inactive_idx = 1 - active_idx
            surface = self._surfaces[inactive_idx]
            cr = cairo.Context(surface)
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(*_GRUVBOX_BG0_RGB, 1.0)
            cr.paint()
            surface.flush()
            with self._output_lock:
                self._output_surface = surface
                self._surface_active_idx = inactive_idx
        except Exception:
            log.debug(
                "CairoSource %s degraded Gruvbox-dark fallback failed",
                self._source_id,
                exc_info=True,
            )
        if self._freshness_gauge is not None:
            self._freshness_gauge.mark_failed()
        try:
            from agents.studio_compositor.degraded_mode import get_controller

            get_controller().record_hold(f"cairo_source:{self._source_id}")
        except Exception:
            log.debug("degraded hold record failed", exc_info=True)

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
        # Task #122 DEGRADED mode. When the stream is degraded (e.g.
        # during a service restart), skip the source's render() and
        # re-serve the cached last-good surface. If no cache exists
        # yet (source has not rendered once), paint a Gruvbox-dark
        # solid fill so the surface is non-empty and non-broken.
        if _degraded_mode_active():
            self._render_degraded_hold()
            return
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
            # Budget skips still represent a "no new frame was
            # published this tick" event — mark the gauge failed so
            # the age_seconds() series crosses its staleness tolerance
            # during a sustained over-budget run, exactly matching the
            # operator-visible degraded state.
            if self._freshness_gauge is not None:
                self._freshness_gauge.mark_failed()
            return

        t0 = time.monotonic()
        try:
            # A+ Stage 3: double-buffered surfaces. The streaming-thread
            # cairooverlay callback reads _output_surface under _output_lock;
            # we render into the OTHER surface, then swap atomically.
            # Surfaces are (re)allocated only when dimensions change.
            # Audit fix (2026-04-17): read dims + active idx inside
            # _output_lock so a concurrent set_canvas_size cannot tear
            # the (width, height) pair.
            with self._output_lock:
                dims = (self._natural_w, self._natural_h)
                active_idx = self._surface_active_idx
            if self._surface_dims != dims or len(self._surfaces) < 2:
                self._surfaces = [
                    cairo.ImageSurface(cairo.FORMAT_ARGB32, dims[0], dims[1]) for _ in range(2)
                ]
                active_idx = 0
                with self._output_lock:
                    self._surface_active_idx = 0
                self._surface_dims = dims
            # Write into the inactive buffer (whichever one the streaming
            # thread is NOT currently pointing at).
            inactive_idx = 1 - active_idx
            surface = self._surfaces[inactive_idx]
            # Clear the reused surface to fully transparent so the new
            # render starts from a known state (equivalent to a fresh
            # ImageSurface which is zeroed at allocation time).
            cr = cairo.Context(surface)
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            # Runner-level ward modulation: every CairoSource automatically
            # honors per-ward visibility + alpha (and any future per-source
            # property the Cairo blit can apply) without per-source code
            # changes. ``visible=False`` short-circuits the source's render
            # so the surface stays transparent (gst mixer composites
            # nothing); ``alpha < 1`` wraps the draw in a Cairo group so
            # the entire composition fades uniformly. Each runner reads the
            # 200ms-cached ward-properties.json — sub-ms even with 16+
            # runners since they share the module-level cache.
            from .ward_properties import ward_render_scope

            ward_gated = False
            # Cascade-delta (2026-04-18): passing canvas_w/canvas_h lets
            # ward_render_scope composite the emphasis overlay (glow,
            # border-pulse, scale-bump) around the source's render
            # without each source re-implementing the plumbing. Without
            # this, structural-intent emphasis was written to
            # ward-properties.json but never surfaced on the livestream —
            # the flat-text-on-black look the operator flagged.
            with ward_render_scope(
                cr,
                self._source_id,
                canvas_w=self._natural_w,
                canvas_h=self._natural_h,
            ) as _ward_props:
                if _ward_props is None:
                    ward_gated = True
                else:
                    self._source.render(
                        cr,
                        self._natural_w,
                        self._natural_h,
                        t0,
                        self._source.state(),
                    )
            surface.flush()
        except Exception:
            log.exception("CairoSource %s render failed", self._source_id)
            if self._freshness_gauge is not None:
                self._freshness_gauge.mark_failed()
            return

        with self._output_lock:
            self._output_surface = surface
            self._surface_active_idx = inactive_idx
        self._frame_count += 1
        self._last_render_ms = (time.monotonic() - t0) * 1000.0
        # Phase C1 (homage-completion-plan §2): publish the
        # ``hapax_homage_render_cadence_hz`` gauge with the instantaneous
        # rate computed from the monotonic delta between consecutive
        # successful renders. Skipped when the ward was gated
        # (``visible=False``) — a gated tick is not a real render so
        # the gauge retains its previous value. Failure is silently
        # swallowed: the gauge is diagnostic and must not propagate
        # into the streaming-thread hot path.
        if not ward_gated:
            now_ts = time.monotonic()
            prev_ts = self._last_successful_render_at
            self._last_successful_render_at = now_ts
            if prev_ts is not None:
                delta = now_ts - prev_ts
                if delta > 0:
                    try:
                        from shared.director_observability import (
                            emit_homage_render_cadence,
                        )

                        emit_homage_render_cadence(self._source_id, 1.0 / delta)
                    except Exception:
                        log.debug(
                            "emit_homage_render_cadence failed for %s",
                            self._source_id,
                            exc_info=True,
                        )
        # Skip the freshness publish when the ward was gated (visible=False).
        # A transparent buffer is technically "published" but operationally
        # it represents "deliberately hidden", not "source healthy and
        # producing". Letting age_seconds() climb during a gated period
        # lets the operator distinguish a gated ward from a stalled one.
        if self._freshness_gauge is not None and not ward_gated:
            self._freshness_gauge.mark_published()
        # Phase 6 H23: push the same rendered surface into the
        # main-layer appsrc if one has been built. No-op when
        # ``gst_appsrc()`` was never called.
        self._push_buffer_to_appsrc(surface)
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
            # First-call soft import failure is an expected degradation
            # path — the module may be deliberately absent on hosts that
            # don't run the wgpu visual surface. Logging at debug keeps
            # the signal out of the normal ops log.
            log.debug(
                "imagination_source_protocol unavailable; CairoSource %s output not published",
                self._source_id,
            )
        except Exception:
            # Audit follow-up: was log.debug, which hid actual publish
            # failures (socket path changed, permissions, malformed
            # buffer). Promoted to warning so the operator sees a
            # broken publish instead of a stalled wgpu consumer.
            log.warning("CairoSource %s publish failed", self._source_id, exc_info=True)
