"""Tests for DURF (Display Under Reflective Frame) ward — Phase 2.

Phase 2 replaces Phase 1's text-classification + redaction approach with
literal Hyprland window pixel capture (per operator directive 2026-04-24
"BE my term content AS it IS"). Token classification, redaction regex,
and ring buffer tests from Phase 1 are removed because the underlying
``_classify_line_role`` / ``_PaneRing`` / ``_redact`` primitives no
longer exist on ``DURFCairoSource``.

What this file pins now:
- Source registration in the cairo_sources registry
- Construction with explicit + missing config
- Gate behavior (off when desk inactive)
- ``state()`` shape (alpha, now)
- Layout integration (default.json includes durf surface + assignment)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agents.studio_compositor.cairo_sources import get_cairo_source_class
from agents.studio_compositor.durf_source import DURFCairoSource

# ── Source instantiation + registration ──────────────────────────────


@pytest.fixture
def minimal_config(tmp_path):
    """Phase 2 config — same yaml shape as Phase 1, but only the
    ``panes`` block carries forward as the discovery hint list."""
    cfg = {
        "panes": [
            {"role": "alpha", "tmux_target": "nowhere:0.0", "glyph": "A-//"},
            {"role": "beta", "tmux_target": "nowhere:0.1", "glyph": "B-|/"},
        ]
    }
    path = tmp_path / "durf-panes.yaml"
    path.write_text(yaml.dump(cfg))
    return path


class TestDURFSource:
    def test_registered_in_cairo_sources(self):
        cls = get_cairo_source_class("DURFCairoSource")
        assert cls is DURFCairoSource

    def test_instantiates_with_config(self, minimal_config):
        src = DURFCairoSource(config_path=minimal_config)
        try:
            assert src.source_id == "durf"
            assert src._config_path == minimal_config
        finally:
            src.stop()

    def test_gate_false_without_desk_active(self, minimal_config):
        src = DURFCairoSource(config_path=minimal_config)
        try:
            assert src._gate_active() is False
        finally:
            src.stop()

    def test_state_returns_alpha_and_now(self, minimal_config):
        src = DURFCairoSource(config_path=minimal_config)
        try:
            state = src.state()
            assert "alpha" in state
            assert "now" in state
            assert 0.0 <= state["alpha"] <= 1.0
        finally:
            src.stop()

    def test_missing_config_handles_gracefully(self, tmp_path):
        """No yaml file at config_path: source still constructs and
        gates off — the discovery thread starts with no hints, finds
        no sessions, and reports alpha=0.0."""
        src = DURFCairoSource(config_path=tmp_path / "nonexistent.yaml")
        try:
            state = src.state()
            assert state["alpha"] == 0.0
        finally:
            src.stop()


# ── Layout parse ─────────────────────────────────────────────────────


class TestLayoutIntegration:
    def test_default_layout_includes_durf(self):
        import json

        from shared.compositor_model import Layout

        path = (
            Path(__file__).resolve().parent.parent.parent
            / "config"
            / "compositor-layouts"
            / "default.json"
        )
        d = json.loads(path.read_text())
        layout = Layout.model_validate(d)
        assert any(s.id == "durf" for s in layout.sources)
        assert any(s.id == "durf-fullframe" for s in layout.surfaces)
        assert any(a.source == "durf" for a in layout.assignments)

    def test_durf_source_full_frame_geometry(self):
        import json

        path = (
            Path(__file__).resolve().parent.parent.parent
            / "config"
            / "compositor-layouts"
            / "default.json"
        )
        d = json.loads(path.read_text())
        surf = next(s for s in d["surfaces"] if s["id"] == "durf-fullframe")
        assert surf["geometry"]["w"] == 1920
        assert surf["geometry"]["h"] == 1080
        assert surf["z_order"] == 5
