"""Tests for the cairo_sources class-name dispatch package.

Plan task 7/29. The compositor source-registry epic uses a class_name
dispatch table so new cairo sources can be declared in default.json without
editing a hardcoded dict. This package owns that registry.

The three migrated classes (TokenPoleCairoSource, AlbumOverlayCairoSource,
SierpinskiCairoSource) were built by the compositor unification epic's
Phase 3b migration and live in their legacy modules. This package imports
and registers them so SourceRegistry.construct_backend can look them up.
"""

from __future__ import annotations

import pytest

from agents.studio_compositor.cairo_source import CairoSource
from agents.studio_compositor.cairo_sources import (
    get_cairo_source_class,
    list_classes,
    register,
)


class TestCairoSourcesRegistry:
    def test_registered_classes_include_migrated_trio(self):
        names = list_classes()
        assert "TokenPoleCairoSource" in names
        assert "AlbumOverlayCairoSource" in names
        assert "SierpinskiCairoSource" in names
        assert "PolyendInstrumentReveal" in names

    def test_lookup_returns_a_cairo_source_subclass(self):
        cls = get_cairo_source_class("TokenPoleCairoSource")
        assert issubclass(cls, CairoSource)

    def test_lookup_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="NotARealClass"):
            get_cairo_source_class("NotARealClass")

    def test_register_idempotent_on_same_class(self):
        cls = get_cairo_source_class("TokenPoleCairoSource")
        register("TokenPoleCairoSource", cls)  # should not raise

    def test_register_rejects_name_collision_with_different_class(self):
        class _Other(CairoSource):
            def render(self, cr, w, h, t, state):  # noqa: D401
                pass

        with pytest.raises(ValueError, match="already bound"):
            register("TokenPoleCairoSource", _Other)
