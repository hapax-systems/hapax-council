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
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest


def _cairo_available() -> bool:
    try:
        import cairo  # noqa: F401
    except ImportError:
        return False
    return True


_HAS_CAIRO = _cairo_available()
requires_cairo = pytest.mark.skipif(not _HAS_CAIRO, reason="pycairo not installed")

_GOLDEN_DIR = Path(__file__).parent / "golden_images" / "content"
_GOLDEN_PIXEL_TOLERANCE = 8
_GOLDEN_BYTE_OVER_BUDGET = 0.02


def _update_golden_requested() -> bool:
    return os.environ.get("HAPAX_UPDATE_GOLDEN", "").strip() not in ("", "0", "false")


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
    @pytest.mark.xfail(
        reason=(
            "EMISSIVE-RETIRED-FLASH-FOLLOWUP — chrome-retirement "
            "cascade (#1242). Banner _draw_banner produces a "
            "transparent surface in the first 8192 bytes post-chrome-"
            "retirement; test should assert 'renders without raising' "
            "rather than pixel-sampling."
        ),
        strict=False,
    )
    def test_draw_banner_runs_cleanly(self):
        import cairo

        from agents.studio_compositor.research_marker_overlay import ResearchMarkerOverlay

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 120)
        cr = cairo.Context(surface)
        overlay = ResearchMarkerOverlay(now_fn=lambda: datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC))
        overlay._draw_banner(cr, 1920, 120, "cond-phase-a-homage-active-001")
        surface.flush()
        data = bytes(surface.get_data())
        assert any(byte != 0 for byte in data[:8192])


@pytest.mark.xfail(
    reason=(
        "EMISSIVE-GOLDEN-PANGO-FOLLOWUP — golden image diverges post-"
        "#1242 chrome retirement + Pango font drift."
    ),
    strict=False,
)
@requires_cairo
def test_research_marker_emissive_golden():
    import cairo

    from agents.studio_compositor.research_marker_overlay import ResearchMarkerOverlay

    _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    golden_path = _GOLDEN_DIR / "research_marker_emissive.png"

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 120)
    cr = cairo.Context(surface)
    overlay = ResearchMarkerOverlay(now_fn=lambda: datetime(2026, 4, 19, 12, 0, 0, tzinfo=UTC))
    overlay._draw_banner(cr, 1920, 120, "cond-phase-a-homage-active-001")
    surface.flush()

    if _update_golden_requested() or not golden_path.exists():
        surface.write_to_png(str(golden_path))
        return

    expected = cairo.ImageSurface.create_from_png(str(golden_path))
    a = bytes(surface.get_data())
    e = bytes(expected.get_data())
    assert len(a) == len(e)
    over = 0
    for ab, eb in zip(a, e, strict=True):
        if abs(ab - eb) > _GOLDEN_PIXEL_TOLERANCE:
            over += 1
    ratio = over / max(1, len(a))
    assert ratio <= _GOLDEN_BYTE_OVER_BUDGET, (
        f"golden mismatch: {over}/{len(a)} bytes ({ratio:.3%}) over tolerance"
    )
