"""SourceRegistry — thin map from source_id to backend handles.

Backends expose ``get_current_surface() -> cairo.ImageSurface | None`` and
(once Phase H lands) ``gst_appsrc() -> Gst.Element | None``. The render loop
and fx_chain both consult this registry and don't care whether the pixels
came from a CairoSourceRunner or a ShmRgbaReader.

Part of the compositor source-registry epic PR 1. See
``docs/superpowers/specs/2026-04-12-compositor-source-registry-foundation-design.md``
§ "Source backends".
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import cairo

    from agents.studio_compositor.budget import BudgetTracker
    from shared.compositor_model import SourceSchema

log = logging.getLogger(__name__)

_DEFAULT_NON_SUBSTRATE_SHM_RGBA_MAX_AGE_S = 30.0


class UnknownSourceError(KeyError):
    """Raised when a lookup references a source_id that isn't registered."""


class UnknownBackendError(ValueError):
    """Raised when a SourceSchema.backend has no dispatcher wired up."""


class SourceBackend(Protocol):
    """Minimum contract for anything the SourceRegistry hands out.

    Phase H will extend this with ``gst_appsrc()`` so fx_chain can build
    persistent appsrc branches per source without caring about backend type.
    """

    def get_current_surface(self) -> cairo.ImageSurface | None:  # pragma: no cover
        ...


class SourceRegistry:
    """Maps ``source_id -> backend handle``. Single lookup entry point."""

    def __init__(self) -> None:
        self._backends: dict[str, SourceBackend] = {}

    def register(self, source_id: str, backend: SourceBackend) -> None:
        """Register a backend under ``source_id``. Duplicate IDs are rejected."""
        if source_id in self._backends:
            raise ValueError(f"source_id already registered: {source_id}")
        self._backends[source_id] = backend

    def get_current_surface(self, source_id: str) -> cairo.ImageSurface | None:
        """Return the backend's current rendered surface, or None if not ready.

        Raises :class:`UnknownSourceError` if ``source_id`` isn't registered.
        """
        try:
            return self._backends[source_id].get_current_surface()
        except KeyError:
            raise UnknownSourceError(source_id) from None

    def ids(self) -> list[str]:
        """Return the list of registered source_ids in insertion order."""
        return list(self._backends.keys())

    def start_all(self) -> None:
        """Start every registered backend that exposes a ``start()`` method.

        Drop #41 BT-1 fix: Phase 9 Task 29 of the compositor unification
        epic removed the legacy Cairo-source facades' draw calls but
        left the replacement path unwired. Layout-declared Cairo
        sources (``token_pole``, ``album``, ``stream_overlay``,
        ``reverie``) were constructed via :meth:`construct_backend` and
        :meth:`register`-ed, but nothing ever called ``start()`` on the
        resulting :class:`CairoSourceRunner` instances — so the
        background render threads never ran,
        ``get_current_surface()`` always returned ``None``, and
        ``pip_draw_from_layout`` silently skipped every source
        (``if src is None: continue``). The operator-visible symptom
        was "PiP content missing from the livestream output" —
        ``costs.json`` only recorded the two legacy facades
        (``sierpinski-lines`` + ``overlay-zones``), confirming the
        other 4 sources had never ticked.

        This method is idempotent and type-tolerant: any backend with
        a ``start()`` attribute gets called. ``ShmRgbaReader`` and
        similar passive backends that don't expose ``start()`` are
        left alone. Per-backend start failures are logged and
        swallowed — a broken cairo class must not take down the
        compositor's layout wiring. ``CairoSourceRunner.start()`` is
        itself idempotent (the runner tracks its own thread state),
        so calling ``start_all()`` twice is safe.

        Called at the end of
        :meth:`StudioCompositor.start_layout_only`, after all
        registrations complete.
        """
        for source_id, backend in self._backends.items():
            start = getattr(backend, "start", None)
            if start is None:
                continue
            try:
                start()
                log.info("SourceRegistry.start_all: started %s", source_id)
            except Exception:
                log.exception(
                    "SourceRegistry.start_all: failed to start %s",
                    source_id,
                )

    def construct_backend(
        self,
        source: SourceSchema,
        *,
        budget_tracker: BudgetTracker | None = None,
    ) -> SourceBackend:
        """Instantiate a backend for ``source`` using its ``backend`` dispatcher.

        ``cairo`` backends are looked up in
        :mod:`agents.studio_compositor.cairo_sources` by ``params.class_name``
        and wrapped in a
        :class:`~agents.studio_compositor.cairo_source.CairoSourceRunner`
        configured at the source's natural dimensions.

        ``shm_rgba`` backends resolve directly to a
        :class:`~agents.studio_compositor.shm_rgba_reader.ShmRgbaReader`
        pointing at ``params.shm_path``.

        When ``budget_tracker`` is provided, cairo backends record their
        per-frame render time into the tracker so the compositor's cost
        snapshot publisher has live samples. Phase 10 wire-up for the
        previously dead-path BudgetTracker — T1/T2/T3 findings from
        delta's 2026-04-14 compositor frame budget forensics drop.

        Raises :class:`UnknownBackendError` for any other backend string,
        missing ``class_name`` on cairo, or missing ``shm_path`` on shm_rgba.
        Raises :class:`KeyError` (from the cairo_sources lookup) if
        ``class_name`` is not registered.
        """
        from pathlib import Path

        if source.backend == "cairo":
            from agents.studio_compositor.cairo_source import CairoSourceRunner
            from agents.studio_compositor.cairo_sources import get_cairo_source_class

            class_name = source.params.get("class_name")
            if not class_name:
                raise UnknownBackendError(f"cairo source {source.id}: missing params.class_name")
            source_cls = get_cairo_source_class(class_name)
            source_obj = source_cls()
            natural_w = int(source.params.get("natural_w", 1920))
            natural_h = int(source.params.get("natural_h", 1080))
            # Precedence for render cadence:
            # 1. params.fps (explicit override at the source level)
            # 2. source.rate_hz (layout JSON's ``rate_hz`` field — the
            #    canonical authoring slot). Before the 2026-04-17 perf
            #    pass this was silently ignored.
            # 3. 10 fps fallback for everything else (including
            #    ``update_cadence=="always"``). A brief 30fps bump on
            #    2026-04-17 drove studio-compositor to 214% CPU and
            #    made cameras jank; reverted. Rate-limited surfaces
            #    still honor their declared rate_hz per (2).
            params_fps = source.params.get("fps")
            if params_fps is not None:
                target_fps = float(params_fps)
            elif source.rate_hz is not None:
                target_fps = float(source.rate_hz)
            else:
                target_fps = 10.0
            return CairoSourceRunner(
                source_id=source.id,
                source=source_obj,
                canvas_w=natural_w,
                canvas_h=natural_h,
                target_fps=target_fps,
                natural_w=natural_w,
                natural_h=natural_h,
                budget_tracker=budget_tracker,
            )
        if source.backend == "shm_rgba":
            from agents.studio_compositor.homage.substrate_source import (
                SUBSTRATE_SOURCE_REGISTRY,
            )
            from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader

            shm_path = source.params.get("shm_path")
            if not shm_path:
                raise UnknownBackendError(f"shm_rgba source {source.id}: missing params.shm_path")
            # HOMAGE #124: the Reverie ``external_rgba`` slot is the
            # always-on generative substrate — its backend carries the
            # ``HomageSubstrateSource`` marker so the choreographer
            # filters it out of the transition queue. Non-Reverie
            # shm_rgba sources (e.g. future YouTube slot PRs) stay
            # opt-out-by-default.
            is_substrate = source.id in SUBSTRATE_SOURCE_REGISTRY or bool(
                source.params.get("is_substrate")
            )
            max_age_raw = source.params.get("max_age_s", source.params.get("max_age_seconds"))
            if max_age_raw is None and not is_substrate:
                max_age_raw = os.environ.get(
                    "HAPAX_SHM_RGBA_MAX_AGE_S",
                    str(_DEFAULT_NON_SUBSTRATE_SHM_RGBA_MAX_AGE_S),
                )
            max_age_s = float(max_age_raw) if max_age_raw not in (None, "") else None
            return ShmRgbaReader(
                Path(shm_path),
                is_substrate=is_substrate,
                max_age_s=max_age_s,
            )
        raise UnknownBackendError(f"unknown backend: {source.backend}")
