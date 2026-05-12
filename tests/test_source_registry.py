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
    """Backend dispatch — cairo via cairo_sources.class_name, shm_rgba via path."""

    def test_dispatch_raises_for_unknown_backend(self):
        registry = SourceRegistry()
        src = _make_source("src1", "not_a_backend")
        with pytest.raises(UnknownBackendError, match="not_a_backend"):
            registry.construct_backend(src)

    def test_dispatch_cairo_resolves_to_cairo_source_runner(self):
        from agents.studio_compositor.cairo_source import CairoSourceRunner

        registry = SourceRegistry()
        src = _make_source(
            "token_pole",
            "cairo",
            {
                "class_name": "TokenPoleCairoSource",
                "natural_w": 300,
                "natural_h": 300,
            },
        )
        backend = registry.construct_backend(src)
        assert isinstance(backend, CairoSourceRunner)

    def test_dispatch_cairo_missing_class_name_raises(self):
        registry = SourceRegistry()
        src = _make_source("src1", "cairo", {})
        with pytest.raises(UnknownBackendError, match="class_name"):
            registry.construct_backend(src)

    def test_dispatch_cairo_unknown_class_name_raises(self):
        registry = SourceRegistry()
        src = _make_source("src1", "cairo", {"class_name": "NotARealClass"})
        with pytest.raises(KeyError, match="NotARealClass"):
            registry.construct_backend(src)

    def test_dispatch_shm_rgba_resolves_to_shm_rgba_reader(self):
        from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader

        registry = SourceRegistry()
        src = SourceSchema(
            id="reverie",
            kind="external_rgba",
            backend="shm_rgba",
            params={
                "natural_w": 640,
                "natural_h": 360,
                "shm_path": "/tmp/reverie.rgba",
            },
        )
        backend = registry.construct_backend(src)
        assert isinstance(backend, ShmRgbaReader)
        assert backend._max_age_s is None

    def test_dispatch_non_substrate_shm_rgba_gets_default_stale_gate(self, monkeypatch):
        from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader

        monkeypatch.delenv("HAPAX_SHM_RGBA_MAX_AGE_S", raising=False)
        registry = SourceRegistry()
        src = SourceSchema(
            id="m8-display",
            kind="external_rgba",
            backend="shm_rgba",
            params={
                "natural_w": 320,
                "natural_h": 240,
                "shm_path": "/tmp/m8-display.rgba",
            },
        )
        backend = registry.construct_backend(src)
        assert isinstance(backend, ShmRgbaReader)
        assert backend._max_age_s == 30.0

    def test_dispatch_non_substrate_shm_rgba_invalid_env_uses_default(self, monkeypatch):
        from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader

        monkeypatch.setenv("HAPAX_SHM_RGBA_MAX_AGE_S", "not-a-number")
        registry = SourceRegistry()
        src = SourceSchema(
            id="m8-display",
            kind="external_rgba",
            backend="shm_rgba",
            params={
                "natural_w": 320,
                "natural_h": 240,
                "shm_path": "/tmp/m8-display.rgba",
            },
        )
        backend = registry.construct_backend(src)
        assert isinstance(backend, ShmRgbaReader)
        assert backend._max_age_s == 30.0

    def test_dispatch_non_substrate_shm_rgba_honors_explicit_max_age(self):
        from agents.studio_compositor.shm_rgba_reader import ShmRgbaReader

        registry = SourceRegistry()
        src = SourceSchema(
            id="m8-display",
            kind="external_rgba",
            backend="shm_rgba",
            params={
                "natural_w": 320,
                "natural_h": 240,
                "shm_path": "/tmp/m8-display.rgba",
                "max_age_seconds": 5,
            },
        )
        backend = registry.construct_backend(src)
        assert isinstance(backend, ShmRgbaReader)
        assert backend._max_age_s == 5.0

    def test_dispatch_shm_rgba_missing_path_raises(self):
        registry = SourceRegistry()
        src = SourceSchema(
            id="reverie",
            kind="external_rgba",
            backend="shm_rgba",
            params={"natural_w": 640, "natural_h": 360},
        )
        with pytest.raises(UnknownBackendError, match="shm_path"):
            registry.construct_backend(src)


class TestSourceRegistryBudgetWiring:
    """Phase 10: registry-constructed cairo runners must forward budget_tracker.

    Per delta 2026-04-14-compositor-frame-budget-forensics.md: the Phase 7
    BudgetTracker was installed but never reached any CairoSourceRunner —
    construct_backend fell through to CairoSourceRunner() with budget_tracker
    defaulted to None. This test pins the wiring so the dead path stays dead.
    """

    def test_cairo_backend_receives_budget_tracker_when_provided(self):
        from agents.studio_compositor.budget import BudgetTracker

        registry = SourceRegistry()
        tracker = BudgetTracker()
        src = _make_source(
            "token_pole",
            "cairo",
            {"class_name": "TokenPoleCairoSource", "natural_w": 300, "natural_h": 300},
        )
        backend = registry.construct_backend(src, budget_tracker=tracker)
        assert backend._budget_tracker is tracker

    def test_cairo_backend_tracker_defaults_to_none(self):
        registry = SourceRegistry()
        src = _make_source(
            "token_pole",
            "cairo",
            {"class_name": "TokenPoleCairoSource", "natural_w": 300, "natural_h": 300},
        )
        backend = registry.construct_backend(src)
        assert backend._budget_tracker is None

    def test_cairo_runner_records_into_tracker_on_tick(self):
        """After one successful render, the tracker must have a sample."""
        from agents.studio_compositor.budget import BudgetTracker

        registry = SourceRegistry()
        tracker = BudgetTracker()
        src = _make_source(
            "token_pole",
            "cairo",
            {"class_name": "TokenPoleCairoSource", "natural_w": 300, "natural_h": 300},
        )
        runner = registry.construct_backend(src, budget_tracker=tracker)
        runner.tick_once()
        snap = tracker.snapshot()
        assert "token_pole" in snap
        assert snap["token_pole"].sample_count == 1
        assert snap["token_pole"].last_ms >= 0.0
