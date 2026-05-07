"""Regression pin for captions retirement from the production layout.

GEM owns the lower-band geometry in ``default.json``. The captions
source implementation remains importable for legacy rollback layouts,
but the production layout must not declare or render it.
"""

from __future__ import annotations

import json
from pathlib import Path

import cairo
import pytest

from shared.compositor_model import Layout

LAYOUT_PATH = Path(__file__).resolve().parents[2] / "config" / "compositor-layouts" / "default.json"


@pytest.fixture()
def layout():
    if not LAYOUT_PATH.exists():
        pytest.skip("default layout not present in this checkout")
    return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))


class TestCaptionsRetiredFromDefaultLayout:
    def test_default_layout_still_parses(self, layout):
        parsed = Layout.model_validate(layout)
        assert parsed.name == "default"

    def test_captions_source_absent(self, layout):
        source_ids = {s["id"] for s in layout["sources"]}
        assert "captions" not in source_ids

    def test_captions_strip_surface_absent(self, layout):
        surface_ids = {s["id"] for s in layout["surfaces"]}
        assert "captions_strip" not in surface_ids

    def test_captions_assignment_retired_for_gem(self, layout):
        """At GEM cutover (2026-04-21), the lower-band geometry moved
        fully to GEM. The retired captions source/surface must not be
        reintroduced into the production assignment graph.
        See docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md
        §5."""
        pairs = {(a["source"], a["surface"]) for a in layout["assignments"]}
        assert ("captions", "captions_strip") not in pairs
        assert ("gem", "gem-mural-bottom") in pairs

    def test_default_layout_render_path_smoke_without_captions(self, layout):
        from agents.studio_compositor.fx_chain import pip_draw_from_layout
        from agents.studio_compositor.layout_state import LayoutState
        from agents.studio_compositor.source_registry import SourceRegistry

        class _SurfaceBackend:
            def __init__(self, surface: cairo.ImageSurface) -> None:
                self._surface = surface

            def get_current_surface(self) -> cairo.ImageSurface:
                return self._surface

        parsed = Layout.model_validate(layout)
        registry = SourceRegistry()
        source_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
        source_cr = cairo.Context(source_surface)
        source_cr.set_source_rgba(1.0, 1.0, 1.0, 1.0)
        source_cr.paint()
        for source_id in {a.source for a in parsed.assignments}:
            registry.register(source_id, _SurfaceBackend(source_surface))

        canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 1080)
        cr = cairo.Context(canvas)
        pip_draw_from_layout(cr, LayoutState(parsed), registry, stage="pre_fx")

    def test_other_core_surfaces_untouched(self, layout):
        """Regression pin: garage-door core surfaces must be present."""
        surface_ids = {s["id"] for s in layout["surfaces"]}
        for required in ("upper-left-vitruvian", "lower-left-album", "sierpinski-overlay"):
            assert required in surface_ids


class TestCaptionsSourceStreamModeDefault:
    def test_default_reader_uses_shared_stream_mode(self, monkeypatch, tmp_path):
        """CaptionsCairoSource default reader should call
        shared.stream_mode.get_stream_mode() when no reader is injected.
        """
        from agents.studio_compositor import captions_source

        # Create an empty STT file so the source doesn't render text anyway
        stt = tmp_path / "stt.txt"
        stt.write_text("hello\n", encoding="utf-8")

        calls = []

        def fake_get_stream_mode():
            calls.append("called")
            return "public_research"

        # Patch the import target so the default path invokes our fake
        import sys
        import types

        fake_mod = types.ModuleType("shared.stream_mode")
        fake_mod.get_stream_mode = fake_get_stream_mode
        monkeypatch.setitem(sys.modules, "shared.stream_mode", fake_mod)

        src = captions_source.CaptionsCairoSource(caption_path=stt)
        state = src.state()
        assert state["mode"] == "public_research"
        assert calls == ["called"]
