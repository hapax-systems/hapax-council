"""Tests for agents/studio_compositor/cairo_source_registry.py.

LRR Phase 2 item 10a regression pin. Covers register/get_for_zone/
all_sources/clear semantics, priority ordering, tie-breaking via
registration order, and type guards on the register API.

Spec: docs/superpowers/specs/2026-04-15-lrr-phase-2-archive-research-instrument-design.md §3.10
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from agents.studio_compositor.cairo_source import CairoSource
from agents.studio_compositor.cairo_source_registry import (
    CairoSourceBinding,
    CairoSourceRegistry,
    load_zone_defaults,
)

if TYPE_CHECKING:
    import cairo


class _DummySource(CairoSource):
    """Minimal CairoSource subclass for registry tests."""

    def render(self, ctx: cairo.Context, width: int, height: int) -> None:  # noqa: D401
        return None


class _OtherSource(CairoSource):
    def render(self, ctx: cairo.Context, width: int, height: int) -> None:
        return None


class _ThirdSource(CairoSource):
    def render(self, ctx: cairo.Context, width: int, height: int) -> None:
        return None


@pytest.fixture(autouse=True)
def _clear_registry():
    """Each test runs against an empty registry."""
    CairoSourceRegistry.clear()
    yield
    CairoSourceRegistry.clear()


class TestRegister:
    def test_register_returns_binding_with_defaults(self):
        binding = CairoSourceRegistry.register(
            source_cls=_DummySource,
            zone="hud_top_left",
        )
        assert isinstance(binding, CairoSourceBinding)
        assert binding.source_cls is _DummySource
        assert binding.zone == "hud_top_left"
        assert binding.priority == 0
        assert binding.registration_index == 0

    def test_register_assigns_sequential_registration_index(self):
        b1 = CairoSourceRegistry.register(source_cls=_DummySource, zone="a")
        b2 = CairoSourceRegistry.register(source_cls=_OtherSource, zone="a")
        b3 = CairoSourceRegistry.register(source_cls=_ThirdSource, zone="b")
        assert b1.registration_index == 0
        assert b2.registration_index == 1
        assert b3.registration_index == 2

    def test_register_rejects_non_class(self):
        with pytest.raises(TypeError, match="must be a CairoSource subclass"):
            CairoSourceRegistry.register(source_cls="not-a-class", zone="a")  # type: ignore[arg-type]

    def test_register_rejects_non_cairo_subclass(self):
        class _NotASource:
            pass

        with pytest.raises(TypeError, match="must be a CairoSource subclass"):
            CairoSourceRegistry.register(source_cls=_NotASource, zone="a")  # type: ignore[arg-type]

    def test_register_rejects_empty_zone(self):
        with pytest.raises(ValueError, match="zone must be non-empty"):
            CairoSourceRegistry.register(source_cls=_DummySource, zone="")


class TestGetForZone:
    def test_empty_registry_returns_empty_list(self):
        assert CairoSourceRegistry.get_for_zone("nope") == []

    def test_single_registration_returns_single_binding(self):
        CairoSourceRegistry.register(source_cls=_DummySource, zone="hud")
        bindings = CairoSourceRegistry.get_for_zone("hud")
        assert len(bindings) == 1
        assert bindings[0].source_cls is _DummySource

    def test_priority_sort_highest_first(self):
        CairoSourceRegistry.register(source_cls=_DummySource, zone="z", priority=1)
        CairoSourceRegistry.register(source_cls=_OtherSource, zone="z", priority=10)
        CairoSourceRegistry.register(source_cls=_ThirdSource, zone="z", priority=5)
        bindings = CairoSourceRegistry.get_for_zone("z")
        assert [b.source_cls for b in bindings] == [_OtherSource, _ThirdSource, _DummySource]

    def test_priority_ties_break_by_registration_order(self):
        CairoSourceRegistry.register(source_cls=_DummySource, zone="z", priority=5)
        CairoSourceRegistry.register(source_cls=_OtherSource, zone="z", priority=5)
        CairoSourceRegistry.register(source_cls=_ThirdSource, zone="z", priority=5)
        bindings = CairoSourceRegistry.get_for_zone("z")
        assert [b.source_cls for b in bindings] == [_DummySource, _OtherSource, _ThirdSource]

    def test_different_zones_are_isolated(self):
        CairoSourceRegistry.register(source_cls=_DummySource, zone="a", priority=10)
        CairoSourceRegistry.register(source_cls=_OtherSource, zone="b", priority=1)
        assert len(CairoSourceRegistry.get_for_zone("a")) == 1
        assert len(CairoSourceRegistry.get_for_zone("b")) == 1
        assert CairoSourceRegistry.get_for_zone("a")[0].source_cls is _DummySource
        assert CairoSourceRegistry.get_for_zone("b")[0].source_cls is _OtherSource

    def test_returned_list_is_a_snapshot_not_live(self):
        CairoSourceRegistry.register(source_cls=_DummySource, zone="z")
        bindings = CairoSourceRegistry.get_for_zone("z")
        bindings.clear()
        # Mutating the returned list must NOT affect the registry.
        assert len(CairoSourceRegistry.get_for_zone("z")) == 1


class TestAllSources:
    def test_empty_registry_returns_empty(self):
        assert CairoSourceRegistry.all_sources() == []

    def test_all_sources_sorted_by_zone_then_priority(self):
        CairoSourceRegistry.register(source_cls=_DummySource, zone="zebra", priority=1)
        CairoSourceRegistry.register(source_cls=_OtherSource, zone="alpha", priority=1)
        CairoSourceRegistry.register(source_cls=_ThirdSource, zone="alpha", priority=10)
        all_b = CairoSourceRegistry.all_sources()
        # alpha comes before zebra; within alpha priority 10 before priority 1
        assert all_b[0].source_cls is _ThirdSource
        assert all_b[1].source_cls is _OtherSource
        assert all_b[2].source_cls is _DummySource

    def test_all_sources_includes_every_registered_entry(self):
        for i in range(5):
            cls = type(f"_T{i}", (CairoSource,), {"render": lambda self, c, w, h: None})
            CairoSourceRegistry.register(source_cls=cls, zone=f"zone{i}")
        assert len(CairoSourceRegistry.all_sources()) == 5


class TestZones:
    def test_zones_returns_sorted_unique(self):
        CairoSourceRegistry.register(source_cls=_DummySource, zone="c")
        CairoSourceRegistry.register(source_cls=_OtherSource, zone="a")
        CairoSourceRegistry.register(source_cls=_ThirdSource, zone="b")
        CairoSourceRegistry.register(source_cls=_DummySource, zone="a")  # dup zone
        assert CairoSourceRegistry.zones() == ["a", "b", "c"]

    def test_zones_empty_when_registry_empty(self):
        assert CairoSourceRegistry.zones() == []


class TestClear:
    def test_clear_removes_all_bindings(self):
        CairoSourceRegistry.register(source_cls=_DummySource, zone="a")
        CairoSourceRegistry.register(source_cls=_OtherSource, zone="b")
        CairoSourceRegistry.clear()
        assert CairoSourceRegistry.all_sources() == []
        assert CairoSourceRegistry.get_for_zone("a") == []

    def test_clear_resets_registration_counter(self):
        CairoSourceRegistry.register(source_cls=_DummySource, zone="a")
        CairoSourceRegistry.register(source_cls=_OtherSource, zone="a")
        CairoSourceRegistry.clear()
        b = CairoSourceRegistry.register(source_cls=_DummySource, zone="a")
        assert b.registration_index == 0


class TestThreadSafety:
    def test_concurrent_register_produces_unique_indices(self):
        """100 threads each register once — every registration_index must be unique."""
        CairoSourceRegistry.clear()
        N = 100

        def _register():
            CairoSourceRegistry.register(source_cls=_DummySource, zone="shared")

        threads = [threading.Thread(target=_register) for _ in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        bindings = CairoSourceRegistry.get_for_zone("shared")
        assert len(bindings) == N
        indices = {b.registration_index for b in bindings}
        assert len(indices) == N  # all unique


class TestLoadZoneDefaults:
    def test_missing_file_returns_zero_zero(self, tmp_path: Path):
        registered, skipped = load_zone_defaults(tmp_path / "does-not-exist.yaml")
        assert registered == 0
        assert skipped == 0

    def test_malformed_yaml_returns_zero_zero(self, tmp_path: Path):
        p = tmp_path / "z.yaml"
        p.write_text("{not valid yaml")
        registered, skipped = load_zone_defaults(p)
        assert registered == 0
        assert skipped == 0

    def test_non_list_zones_returns_zero_zero(self, tmp_path: Path):
        p = tmp_path / "z.yaml"
        p.write_text("schema_version: 1\nzones: not-a-list\n")
        registered, skipped = load_zone_defaults(p)
        assert registered == 0
        assert skipped == 0

    def test_placeholder_entries_count_as_skipped_not_error(self, tmp_path: Path):
        p = tmp_path / "z.yaml"
        p.write_text(
            "schema_version: 1\n"
            "zones:\n"
            "  - name: future_zone\n"
            "    default_source: null\n"
            "    default_source_module: null\n"
            "    default_priority: 100\n"
        )
        registered, skipped = load_zone_defaults(p)
        assert registered == 0
        assert skipped == 1

    def test_production_zone_catalog_populates_real_registry(self):
        """Integration — loads `config/compositor-zones.yaml` and verifies
        the 5 real existing CairoSource classes register correctly."""
        catalog_path = (
            Path(__file__).resolve().parent.parent.parent / "config" / "compositor-zones.yaml"
        )
        assert catalog_path.exists(), f"production catalog missing at {catalog_path}"
        CairoSourceRegistry.clear()
        registered, skipped = load_zone_defaults(catalog_path)
        # 5 real sources + 6 placeholders (reverie + 5 HSEA Phase 1 zones)
        assert registered == 5, f"expected 5 real registrations, got {registered}"
        assert skipped == 6
        # Verify a few specific registrations
        token_bindings = CairoSourceRegistry.get_for_zone("token_pole_slot")
        assert len(token_bindings) == 1
        assert token_bindings[0].source_cls.__name__ == "TokenPoleCairoSource"
        assert token_bindings[0].priority == 10
        album_bindings = CairoSourceRegistry.get_for_zone("album_slot")
        assert len(album_bindings) == 1
        assert album_bindings[0].source_cls.__name__ == "AlbumOverlayCairoSource"
        sierpinski_bindings = CairoSourceRegistry.get_for_zone("sierpinski_slot")
        assert len(sierpinski_bindings) == 1
        assert sierpinski_bindings[0].source_cls.__name__ == "SierpinskiCairoSource"
        # HSEA Phase 1 placeholder zones should NOT have registrations
        assert CairoSourceRegistry.get_for_zone("hud_top_left") == []
        assert CairoSourceRegistry.get_for_zone("condition_transition_banner") == []

    def test_unresolvable_module_is_skipped_not_raised(self, tmp_path: Path):
        p = tmp_path / "z.yaml"
        p.write_text(
            "schema_version: 1\n"
            "zones:\n"
            "  - name: broken\n"
            "    default_source: DoesNotExist\n"
            "    default_source_module: this.module.does.not.exist\n"
            "    default_priority: 10\n"
            "  - name: also_broken\n"
            "    default_source: AlsoNope\n"
            "    default_source_module: agents.studio_compositor.cairo_source\n"
            "    default_priority: 10\n"
        )
        registered, skipped = load_zone_defaults(p)
        assert registered == 0
        assert skipped == 2
