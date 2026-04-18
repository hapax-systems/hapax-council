"""Tests for LRR Phase 9 §3.6 — scientific-register caption source."""

from __future__ import annotations

from pathlib import Path


class TestStyleForStreamMode:
    def test_public_uses_display_style(self):
        from agents.studio_compositor.captions_source import STYLE_PUBLIC, style_for_stream_mode

        assert style_for_stream_mode("public") is STYLE_PUBLIC

    def test_public_research_uses_scientific(self):
        from agents.studio_compositor.captions_source import (
            STYLE_SCIENTIFIC,
            style_for_stream_mode,
        )

        assert style_for_stream_mode("public_research") is STYLE_SCIENTIFIC

    def test_private_uses_scientific(self):
        from agents.studio_compositor.captions_source import (
            STYLE_SCIENTIFIC,
            style_for_stream_mode,
        )

        assert style_for_stream_mode("private") is STYLE_SCIENTIFIC

    def test_fortress_uses_scientific(self):
        from agents.studio_compositor.captions_source import (
            STYLE_SCIENTIFIC,
            style_for_stream_mode,
        )

        assert style_for_stream_mode("fortress") is STYLE_SCIENTIFIC

    def test_none_defaults_to_scientific(self):
        from agents.studio_compositor.captions_source import (
            STYLE_SCIENTIFIC,
            style_for_stream_mode,
        )

        assert style_for_stream_mode(None) is STYLE_SCIENTIFIC


class TestStyleShape:
    def test_public_larger_than_scientific(self):
        from agents.studio_compositor.captions_source import STYLE_PUBLIC, STYLE_SCIENTIFIC

        assert STYLE_PUBLIC.font_size_px > STYLE_SCIENTIFIC.font_size_px

    def test_public_uses_sans_display_font(self):
        from agents.studio_compositor.captions_source import STYLE_PUBLIC

        assert "Display" in STYLE_PUBLIC.font_description or "Bold" in STYLE_PUBLIC.font_description

    def test_scientific_uses_monospace(self):
        from agents.studio_compositor.captions_source import STYLE_SCIENTIFIC

        assert "Mono" in STYLE_SCIENTIFIC.font_description


class TestReadLatestCaption:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        from agents.studio_compositor.captions_source import _read_latest_caption

        assert _read_latest_caption(tmp_path / "nope.txt") == ""

    def test_empty_file_returns_empty(self, tmp_path: Path):
        from agents.studio_compositor.captions_source import _read_latest_caption

        p = tmp_path / "stt.txt"
        p.write_text("", encoding="utf-8")
        assert _read_latest_caption(p) == ""

    def test_returns_last_nonempty_line(self, tmp_path: Path):
        from agents.studio_compositor.captions_source import _read_latest_caption

        p = tmp_path / "stt.txt"
        p.write_text("first\nsecond line\n\n  \n", encoding="utf-8")
        assert _read_latest_caption(p) == "second line"

    def test_whitespace_only_file_returns_empty(self, tmp_path: Path):
        from agents.studio_compositor.captions_source import _read_latest_caption

        p = tmp_path / "stt.txt"
        p.write_text("   \n\t\n  \n", encoding="utf-8")
        assert _read_latest_caption(p) == ""


class TestCaptionsCairoSourceState:
    def test_state_shape(self, tmp_path: Path):
        from agents.studio_compositor.captions_source import CaptionsCairoSource

        p = tmp_path / "stt.txt"
        p.write_text("hello there\n", encoding="utf-8")

        src = CaptionsCairoSource(
            caption_path=p,
            stream_mode_reader=lambda: "public_research",
        )
        state = src.state()
        assert state["text"] == "hello there"
        assert state["mode"] == "public_research"

    def test_state_without_reader_uses_shared_default(self, tmp_path: Path, monkeypatch):
        from agents.studio_compositor.captions_source import CaptionsCairoSource

        # With no reader injected, the source delegates to
        # shared.stream_mode.get_stream_mode(), which fail-closes to
        # PUBLIC when the state file is absent. Pin the reader so this
        # test doesn't depend on the host's /dev/shm state.
        from shared.stream_mode import StreamMode

        monkeypatch.setattr(
            "shared.stream_mode.get_stream_mode", lambda path=None: StreamMode.PUBLIC
        )

        p = tmp_path / "stt.txt"
        p.write_text("content\n", encoding="utf-8")

        src = CaptionsCairoSource(caption_path=p)
        state = src.state()
        assert state["mode"] == "public"

    def test_state_reader_exception_falls_back(self, tmp_path: Path):
        from agents.studio_compositor.captions_source import CaptionsCairoSource

        p = tmp_path / "stt.txt"
        p.write_text("content\n", encoding="utf-8")

        def boom():
            raise RuntimeError("reader exploded")

        src = CaptionsCairoSource(caption_path=p, stream_mode_reader=boom)
        state = src.state()
        assert state["mode"] == "private"

    def test_state_reader_non_string_falls_back(self, tmp_path: Path):
        from agents.studio_compositor.captions_source import CaptionsCairoSource

        p = tmp_path / "stt.txt"
        p.write_text("content\n", encoding="utf-8")

        src = CaptionsCairoSource(caption_path=p, stream_mode_reader=lambda: 42)
        state = src.state()
        assert state["mode"] == "private"

    def test_state_switches_style_with_mode(self, tmp_path: Path):
        from agents.studio_compositor.captions_source import (
            STYLE_PUBLIC,
            STYLE_SCIENTIFIC,
            CaptionsCairoSource,
        )

        p = tmp_path / "stt.txt"
        p.write_text("hello\n", encoding="utf-8")

        current_mode = {"v": "public_research"}
        src = CaptionsCairoSource(
            caption_path=p,
            stream_mode_reader=lambda: current_mode["v"],
        )
        src.state()
        assert src._current_style is STYLE_SCIENTIFIC

        current_mode["v"] = "public"
        src.state()
        assert src._current_style is STYLE_PUBLIC


class TestRenderNoOpOnEmpty:
    def test_render_returns_early_on_empty_text(self, tmp_path: Path):
        """No text → render is a no-op; the fake cr must see zero calls."""
        from agents.studio_compositor.captions_source import CaptionsCairoSource

        p = tmp_path / "stt.txt"
        p.write_text("", encoding="utf-8")

        class FakeCr:
            def __init__(self):
                self.calls = 0

            def set_source_surface(self, *a, **kw):
                self.calls += 1

            def paint(self):
                self.calls += 1

        src = CaptionsCairoSource(caption_path=p)
        state = src.state()  # empty text
        cr = FakeCr()
        src.render(cr, 1920, 1080, 0.0, state)
        assert cr.calls == 0
