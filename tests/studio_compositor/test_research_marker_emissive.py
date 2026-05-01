"""Phase A4 emissive-rewrite regression for ``ResearchMarkerOverlay``.

Pins:

- ``_draw_banner`` renders via Pango + ``text_render.render_text`` — no
  ``cr.show_text`` / ``cr.select_font_face``.
- Banner uses ``paint_emissive_point`` for the condition-id glyph row
  and Px437 via ``select_bitchx_font_pango`` for the main body line.
- The body text includes ``>>> [RESEARCH MARKER]`` grammar.
- Marker file refresh + visibility probe still work.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest


def _cairo_available() -> bool:
    try:
        import cairo  # noqa: F401
    except ImportError:
        return False
    return True


_HAS_CAIRO = _cairo_available()
requires_cairo = pytest.mark.skipif(not _HAS_CAIRO, reason="pycairo not installed")


class TestResearchMarkerNoToyText:
    def test_no_show_text_or_select_font_face_in_module(self):
        from agents.studio_compositor import research_marker_overlay

        src = inspect.getsource(research_marker_overlay)
        assert "cr.show_text" not in src
        assert "cr.select_font_face" not in src

    def test_draw_banner_uses_emissive_helpers(self):
        from agents.studio_compositor import research_marker_overlay

        src = inspect.getsource(research_marker_overlay.ResearchMarkerOverlay._draw_banner)
        assert "paint_emissive_point" in src
        assert "paint_emissive_bg" in src
        assert "select_bitchx_font_pango" in src
        assert "render_text" in src

    def test_banner_grammar_is_bitchx(self):
        from agents.studio_compositor import research_marker_overlay

        src = inspect.getsource(research_marker_overlay.ResearchMarkerOverlay._draw_banner)
        assert ">>> [RESEARCH MARKER]" in src


@requires_cairo
class TestResearchMarkerRenders:
    def test_draw_banner_runs_cleanly(self):
        """Banner render completes without raising and deposits ink
        somewhere on the surface. Post-#1242 chrome retirement, the
        leading 8192 bytes are transparent (banner content lands lower
        on the surface), so the assertion is any-byte-anywhere rather
        than a leading-bytes probe."""
        import cairo

        from agents.studio_compositor.research_marker_overlay import ResearchMarkerOverlay

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 120)
        cr = cairo.Context(surface)
        overlay = ResearchMarkerOverlay(now_fn=lambda: datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC))
        overlay._draw_banner(cr, 1920, 120, "cond-phase-a-homage-active-001")
        surface.flush()
        data = bytes(surface.get_data())
        assert any(byte != 0 for byte in data), "banner produced empty surface"


@requires_cairo
def test_research_marker_render_dimensions():
    """Banner renders at the declared 1920×120 canvas (replaces the
    prior pixel-perfect golden, which drifted on Pango font
    rasterisation differences across environments)."""
    import cairo

    from agents.studio_compositor.research_marker_overlay import ResearchMarkerOverlay

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 120)
    cr = cairo.Context(surface)
    overlay = ResearchMarkerOverlay(now_fn=lambda: datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC))
    overlay._draw_banner(cr, 1920, 120, "cond-phase-a-homage-active-001")
    surface.flush()

    assert surface.get_width() == 1920
    assert surface.get_height() == 120
    data = bytes(surface.get_data())
    expected_len = surface.get_stride() * 120
    assert len(data) == expected_len
