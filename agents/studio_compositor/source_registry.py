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

        Stub for Phase A. Task 6 replaces the body with the real dispatcher
        table for ``cairo`` + ``shm_rgba``. The stub raises a specific error
        shape so tests can assert the dispatch path is covered.
        """
        if source.backend == "cairo":
            raise UnknownBackendError(
                f"cairo backend dispatcher not wired yet (source: {source.id})"
            )
        if source.backend == "shm_rgba":
            raise UnknownBackendError(
                f"shm_rgba backend dispatcher not wired yet (source: {source.id})"
            )
        raise UnknownBackendError(f"unknown backend: {source.backend}")
