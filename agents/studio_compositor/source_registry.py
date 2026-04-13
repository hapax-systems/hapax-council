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
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import cairo

    from shared.compositor_model import SourceSchema

log = logging.getLogger(__name__)


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

    def construct_backend(self, source: SourceSchema) -> SourceBackend:
        """Instantiate a backend for ``source`` using its ``backend`` dispatcher.

        ``cairo`` backends are looked up in
        :mod:`agents.studio_compositor.cairo_sources` by ``params.class_name``
        and wrapped in a
        :class:`~agents.studio_compositor.cairo_source.CairoSourceRunner`
        configured at the source's natural dimensions.

        ``shm_rgba`` backends resolve directly to a
        :class:`~agents.studio_compositor.shm_rgba_reader.ShmRgbaReader`
        pointing at ``params.shm_path``.

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
            target_fps = float(source.params.get("fps", 10.0))
            return CairoSourceRunner(
                source_id=source.id,
                source=source_obj,
                canvas_w=natural_w,
                canvas_h=natural_h,
                target_fps=target_fps,
                natural_w=natural_w,
                natural_h=natural_h,
            )
        if source.backend == "shm_rgba":
            from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader

            shm_path = source.params.get("shm_path")
            if not shm_path:
                raise UnknownBackendError(f"shm_rgba source {source.id}: missing params.shm_path")
            return ShmRgbaReader(Path(shm_path))
        raise UnknownBackendError(f"unknown backend: {source.backend}")
