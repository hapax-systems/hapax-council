"""Regression pin for the CaptionsCairoSource layout registration.

Continuous-Loop Research Cadence §3.4 adds the captions source +
captions_strip surface + assignment to the default layout. These tests
keep future layout edits honest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

LAYOUT_PATH = Path(__file__).resolve().parents[2] / "config" / "compositor-layouts" / "default.json"


@pytest.fixture()
def layout():
    if not LAYOUT_PATH.exists():
        pytest.skip("default layout not present in this checkout")
    return json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))


class TestCaptionsInDefaultLayout:
    def test_captions_source_registered(self, layout):
        source_ids = {s["id"] for s in layout["sources"]}
        assert "captions" in source_ids

    def test_captions_source_points_at_cairo_class(self, layout):
        captions = next(s for s in layout["sources"] if s["id"] == "captions")
        assert captions["kind"] == "cairo"
        assert captions["backend"] == "cairo"
        assert captions["params"]["class_name"] == "CaptionsCairoSource"

    def test_captions_strip_surface_defined(self, layout):
        surface_ids = {s["id"] for s in layout["surfaces"]}
        assert "captions_strip" in surface_ids

    def test_captions_strip_is_bottom_horizontal(self, layout):
        strip = next(s for s in layout["surfaces"] if s["id"] == "captions_strip")
        geom = strip["geometry"]
        assert geom["kind"] == "rect"
        # Horizontal strip, not a PiP
        assert geom["w"] > geom["h"]
        # Bottom placement (y > half the 1080 canvas)
        assert geom["y"] >= 900
        # Full-ish width (>= 1800 of 1920)
        assert geom["w"] >= 1800

    def test_captions_strip_above_video_out(self, layout):
        # z_order comparison: captions must sit above compositor content
        # (PiP z_order 10) but below the video-out sinks (z_order 100+)
        # so OBS/monitoring still captures the band.
        strip = next(s for s in layout["surfaces"] if s["id"] == "captions_strip")
        video_out = next(s for s in layout["surfaces"] if s["id"] == "video_out_v4l2_loopback")
        assert 10 < strip["z_order"] < video_out["z_order"]

    def test_captions_assignment_retired_for_gem(self, layout):
        """At GEM cutover (2026-04-21), captions → captions_strip
        assignment was removed from the default layout. The lower-band
        geometry now belongs to the GEM ward (#191). captions source +
        captions_strip surface remain in the schema as deprecated
        references for backwards compatibility but are not rendered.
        See docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md
        §5."""
        pairs = {(a["source"], a["surface"]) for a in layout["assignments"]}
        assert ("captions", "captions_strip") not in pairs
        assert ("gem", "gem-mural-bottom") in pairs

    def test_other_core_pips_untouched(self, layout):
        """Regression pin: CL §3.4 must not reposition pre-existing PiPs."""
        surface_ids = {s["id"] for s in layout["surfaces"]}
        for required in ("pip-ul", "pip-ur", "pip-ll", "pip-lr"):
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
