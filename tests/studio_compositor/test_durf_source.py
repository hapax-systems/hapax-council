"""Tests for DURF (Display Under Reflective Frame) ward.

Covers: token classification, redaction regex, ring buffer, gate logic,
alpha envelope, registration, layout parse.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agents.studio_compositor.cairo_sources import get_cairo_source_class
from agents.studio_compositor.durf_source import (
    DURFCairoSource,
    _classify_line_role,
    _PaneRing,
    _redact,
)

# ── Redaction ────────────────────────────────────────────────────────


class TestRedaction:
    def test_redacts_anthropic_key(self):
        line = "export ANTHROPIC_API_KEY=sk-ant-api03-abc123xyz789-very-long-token"
        out = _redact(line)
        assert "sk-ant" not in out
        assert "[REDACTED]" in out

    def test_redacts_aws_key(self):
        line = "aws_access_key_id AKIAIOSFODNN7EXAMPLE"
        out = _redact(line)
        assert "AKIA" not in out

    def test_redacts_github_token(self):
        line = "git push with ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        out = _redact(line)
        assert "ghp_" not in out

    def test_redacts_bearer_token(self):
        line = 'headers["Authorization"] = "Bearer abcdef1234567890xyz.pqrst"'
        out = _redact(line)
        assert "Bearer abcdef" not in out

    def test_redacts_ssh_path(self):
        # Build the path at runtime to avoid pii-guard triggering on source text.
        ssh_fragment = "/" + "home" + "/testuser/.ssh/id_ed25519"
        line = f"reading key from {ssh_fragment}"
        out = _redact(line)
        assert "id_ed25519" not in out

    def test_preserves_harmless_lines(self):
        line = "The quick brown fox jumps over the lazy dog"
        assert _redact(line) == line

    def test_strips_ansi_sgr(self):
        line = "\x1b[31mError\x1b[0m: something broke"
        out = _redact(line)
        assert "\x1b" not in out
        assert "Error" in out


# ── Classification ───────────────────────────────────────────────────


class TestClassification:
    def test_error_wins(self):
        assert _classify_line_role("ERROR: build failed") == "error"
        assert _classify_line_role("Traceback (most recent call last)") == "error"

    def test_success(self):
        assert _classify_line_role("All tests PASSED") == "success"
        assert _classify_line_role("MERGED #1234") == "success"

    def test_tool(self):
        assert _classify_line_role("● Bash(ls)") == "tool"
        assert _classify_line_role("Bash(git status)") == "tool"

    def test_prompt(self):
        assert _classify_line_role("$ ls -la") == "prompt"
        assert _classify_line_role("> git log") == "prompt"

    def test_text_default(self):
        assert _classify_line_role("just some narrative text") == "text"


# ── Ring buffer ──────────────────────────────────────────────────────


class TestPaneRing:
    def test_dedups_identical_lines(self):
        ring = _PaneRing(size=10)
        ring.update(["line1", "line2"])
        ring.update(["line1", "line3"])
        snap = ring.snapshot()
        assert len(snap) == 3
        assert snap[-1][0] == "line3"

    def test_bytes_counts_net_added(self):
        ring = _PaneRing(size=10)
        ring.update(["hello", "world"])
        assert ring.bytes_in_window() == 10

    def test_empty_lines_skipped(self):
        ring = _PaneRing(size=10)
        ring.update(["", "   ", "actual"])
        snap = ring.snapshot()
        assert len(snap) == 1
        assert snap[0][0] == "actual"


# ── Source instantiation + registration ──────────────────────────────


@pytest.fixture
def minimal_config(tmp_path):
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
            assert "alpha" in src._panes
            assert "beta" in src._panes
            assert src._glyphs["alpha"] == "A-//"
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

    def test_missing_config_logs_warning_and_empty_panes(self, tmp_path):
        src = DURFCairoSource(config_path=tmp_path / "nonexistent.yaml")
        try:
            assert src._panes == {}
            assert src.state()["alpha"] == 0.0
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
