"""SourceRegistry tests — thin source_id → backend map for the compositor.

Plan task 3/29. See
``docs/superpowers/plans/2026-04-12-compositor-source-registry-foundation-plan.md``
§ Phase A Task 3.
"""

from __future__ import annotations

import cairo
import pytest

from agents.studio_compositor.source_registry import (
    SourceRegistry,
    UnknownBackendError,
    UnknownSourceError,
)
from shared.compositor_model import SourceSchema


class _FakeBackend:
    def __init__(self, surface: cairo.ImageSurface) -> None:
        self._surface = surface

    def get_current_surface(self) -> cairo.ImageSurface:
        return self._surface


def _make_source(id: str, backend: str, params: dict | None = None) -> SourceSchema:
    return SourceSchema(id=id, kind="cairo", backend=backend, params=params or {})


class TestSourceRegistryLookup:
    def test_get_current_surface_returns_backend_output(self):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
        registry = SourceRegistry()
        registry.register("src1", _FakeBackend(surf))
        assert registry.get_current_surface("src1") is surf

    def test_get_current_surface_unknown_raises(self):
        registry = SourceRegistry()
        with pytest.raises(UnknownSourceError, match="bogus"):
            registry.get_current_surface("bogus")

    def test_register_duplicate_rejected(self):
        registry = SourceRegistry()
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
        registry.register("src1", _FakeBackend(surf))
        with pytest.raises(ValueError, match="already registered"):
            registry.register("src1", _FakeBackend(surf))

    def test_ids_returns_registered_source_ids(self):
        registry = SourceRegistry()
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)
        registry.register("src1", _FakeBackend(surf))
        registry.register("src2", _FakeBackend(surf))
        assert set(registry.ids()) == {"src1", "src2"}


class TestSourceRegistryDispatch:
    """Dispatch stubs — actual backends wired in Task 6."""

    def test_dispatch_raises_for_unknown_backend(self):
        registry = SourceRegistry()
        src = _make_source("src1", "not_a_backend")
        with pytest.raises(UnknownBackendError, match="not_a_backend"):
            registry.construct_backend(src)

    def test_dispatch_cairo_stub_raises_not_yet_wired(self):
        """Task 3 ships the stub; Task 6 wires the real dispatcher."""
        registry = SourceRegistry()
        src = _make_source("src1", "cairo", {"class_name": "X"})
        with pytest.raises(UnknownBackendError, match="not wired"):
            registry.construct_backend(src)

    def test_dispatch_shm_rgba_stub_raises_not_yet_wired(self):
        registry = SourceRegistry()
        src = SourceSchema(
            id="src1",
            kind="external_rgba",
            backend="shm_rgba",
            params={"natural_w": 100, "natural_h": 100, "shm_path": "/tmp/x.rgba"},
        )
        with pytest.raises(UnknownBackendError, match="not wired"):
            registry.construct_backend(src)
