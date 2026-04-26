"""Tests for ``agents.studio_compositor.scribble_strip_source``."""

from __future__ import annotations

import pytest

cairo = pytest.importorskip("cairo")

from agents.studio_compositor.scribble_strip_source import (
    DEFAULT_ROUTING_TABLE,
    ScribbleStripSource,
    StripAssertion,
)


class TestRoutingTable:
    def test_default_table_has_18_strips(self) -> None:
        # 12 channels + AUX A-E (5) + EFX = 18
        assert len(DEFAULT_ROUTING_TABLE) == 18

    def test_first_12_are_channels(self) -> None:
        for i, strip in enumerate(DEFAULT_ROUTING_TABLE[:12]):
            assert strip.strip == f"CH {i + 1}"

    def test_aux_strips_present(self) -> None:
        labels = [s.strip for s in DEFAULT_ROUTING_TABLE]
        for aux in ("AUX A", "AUX B", "AUX C", "AUX D", "AUX E"):
            assert aux in labels
        assert "EFX" in labels

    def test_aux_c_carries_scene_8_indicator(self) -> None:
        aux_c = next(s for s in DEFAULT_ROUTING_TABLE if s.strip == "AUX C")
        assert aux_c.signal == "operator monitor mix"
        assert "Scene-8 indicator" in aux_c.flags

    def test_ch_2_has_phantom_power(self) -> None:
        ch2 = DEFAULT_ROUTING_TABLE[1]
        assert ch2.signal == "Cortado contact mic"
        assert "+48V" in ch2.flags

    def test_ch_11_routes_to_master(self) -> None:
        ch11 = DEFAULT_ROUTING_TABLE[10]
        assert "Hapax voice (broadcast)" in ch11.signal
        assert "→ MASTER" in ch11.flags

    def test_ch_12_routes_to_phones_c(self) -> None:
        ch12 = DEFAULT_ROUTING_TABLE[11]
        assert "Hapax voice (private)" in ch12.signal
        assert any("PHONES C" in flag for flag in ch12.flags)


class TestStripAssertion:
    def test_construction(self) -> None:
        s = StripAssertion("CH 1", "test", ("flag-a", "flag-b"))
        assert s.strip == "CH 1"
        assert s.signal == "test"
        assert s.flags == ("flag-a", "flag-b")

    def test_frozen(self) -> None:
        s = StripAssertion("CH 1", "test", ())
        with pytest.raises((AttributeError, TypeError)):
            s.signal = "mutated"  # type: ignore[misc]


class TestScribbleStripSourceRender:
    """Verify the Phase 1 framework draws without crashing.

    Smoke test only — the per-strip indicator art is Phase 2 work.
    These tests confirm the CairoSource contract is honoured (no
    exception during render, declared routing table reachable).
    """

    def test_render_does_not_raise(self) -> None:
        source = ScribbleStripSource()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1280, 80)
        cr = cairo.Context(surface)
        source.render(cr, 1280, 80, t=0.0, state={})

    def test_render_handles_zero_width(self) -> None:
        # Edge case: degenerate canvas. Should not divide-by-zero or
        # render anything meaningful, but must not raise.
        source = ScribbleStripSource(routing_table=())
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
        cr = cairo.Context(surface)
        source.render(cr, 1, 1, t=0.0, state={})

    def test_routing_table_property_returns_default(self) -> None:
        source = ScribbleStripSource()
        assert source.routing_table == DEFAULT_ROUTING_TABLE

    def test_custom_routing_table(self) -> None:
        custom = (StripAssertion("X", "y", ()),)
        source = ScribbleStripSource(routing_table=custom)
        assert source.routing_table == custom
