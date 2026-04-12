"""Tests for the shared Pango text helper.

Phase 3c of the compositor unification epic — the single source of
truth for text-on-Cairo rendering used by AlbumOverlay and OverlayZone.

Skips render-path tests when the GI Pango/PangoCairo typelibs aren't
installed (CI containers ship without GTK). The dataclass and
content-hash tests still run unconditionally because they have no
GI dependency.
"""

from __future__ import annotations

import cairo
import pytest

from agents.studio_compositor.text_render import (
    OUTLINE_OFFSETS_4,
    OUTLINE_OFFSETS_8,
    TextChange,
    TextContent,
    TextStyle,
    measure_text,
    render_text,
    render_text_to_surface,
)


def _pango_available() -> bool:
    """True iff the GI Pango/PangoCairo typelibs are importable.

    The text_render helper imports them lazily inside _build_layout so
    a missing typelib only fails at draw time. CI containers without
    GTK should skip the render-path tests rather than fail them.
    """
    try:
        import gi  # noqa: PLC0415

        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


_HAS_PANGO = _pango_available()
requires_pango = pytest.mark.skipif(
    not _HAS_PANGO, reason="GI Pango/PangoCairo typelibs not installed"
)


def _ctx(w: int = 256, h: int = 64) -> cairo.Context:
    """Build a fresh ARGB context for measurements/draws."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    return cairo.Context(surface)


# ---------------------------------------------------------------------------
# TextStyle dataclass
# ---------------------------------------------------------------------------


def test_text_style_is_frozen():
    style = TextStyle(text="hello")
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        style.text = "boom"  # type: ignore[misc]


def test_text_style_is_hashable():
    a = TextStyle(text="hello", font_description="Sans 12")
    b = TextStyle(text="hello", font_description="Sans 12")
    assert hash(a) == hash(b)
    assert {a} == {b}


def test_outline_offsets_constants_have_expected_count():
    assert len(OUTLINE_OFFSETS_4) == 4
    assert len(OUTLINE_OFFSETS_8) == 8


# ---------------------------------------------------------------------------
# measure_text / render_text
# ---------------------------------------------------------------------------


@requires_pango
def test_measure_text_returns_positive_dimensions():
    cr = _ctx()
    style = TextStyle(text="hello world", font_description="Sans 14")
    w, h = measure_text(cr, style)
    assert w > 0
    assert h > 0


@requires_pango
def test_measure_text_empty_string_zero_width():
    cr = _ctx()
    style = TextStyle(text="", font_description="Sans 14")
    w, _h = measure_text(cr, style)
    # Pango lays out empty text as a zero-width line; height is the
    # font's leading. We assert width is zero (the contract callers
    # depend on for layout decisions).
    assert w == 0


@requires_pango
def test_render_text_returns_dimensions():
    cr = _ctx()
    style = TextStyle(text="hello", font_description="Sans 14")
    w, h = render_text(cr, style, x=0, y=0)
    assert w > 0
    assert h > 0


@requires_pango
def test_render_text_draws_pixels():
    cr = _ctx(w=256, h=32)
    style = TextStyle(
        text="ABC",
        font_description="Sans 16",
        color_rgba=(1.0, 1.0, 1.0, 1.0),
    )
    render_text(cr, style, x=2, y=2)
    surface = cr.get_target()
    assert isinstance(surface, cairo.ImageSurface)
    surface.flush()
    data = bytes(surface.get_data())
    # At least one non-zero pixel was drawn.
    assert any(b != 0 for b in data)


@requires_pango
def test_render_text_with_outline_draws_more_pixels_than_without():
    """Outline + foreground produces strictly more painted pixels than
    foreground alone, since the outline expands the visual footprint."""

    def count_nonzero(style: TextStyle) -> int:
        cr = _ctx(w=256, h=32)
        render_text(cr, style, x=8, y=4)
        surface = cr.get_target()
        assert isinstance(surface, cairo.ImageSurface)
        surface.flush()
        return sum(1 for b in bytes(surface.get_data()) if b != 0)

    plain = TextStyle(text="ABC", font_description="Sans 14")
    with_outline = TextStyle(
        text="ABC",
        font_description="Sans 14",
        outline_offsets=OUTLINE_OFFSETS_4,
        outline_color_rgba=(0.0, 0.0, 0.0, 1.0),
    )
    assert count_nonzero(with_outline) > count_nonzero(plain)


@requires_pango
def test_render_text_with_max_width_wraps():
    """A long string with a small max_width must produce a taller layout
    than the same string at full width."""
    cr = _ctx(w=512, h=256)
    long = "the quick brown fox jumps over the lazy dog " * 4
    narrow = TextStyle(text=long, font_description="Sans 14", max_width_px=100)
    wide = TextStyle(text=long, font_description="Sans 14", max_width_px=2000)
    _, narrow_h = measure_text(cr, narrow)
    _, wide_h = measure_text(cr, wide)
    assert narrow_h > wide_h


@requires_pango
def test_render_text_markup_mode_uses_pango_markup():
    """Markup mode should accept Pango markup tags without raising and
    produce a different visual result than text mode for the same input.
    """
    cr1 = _ctx(w=256, h=32)
    cr2 = _ctx(w=256, h=32)

    text_style = TextStyle(text="<b>bold</b>", font_description="Sans 14")
    markup_style = TextStyle(text="<b>bold</b>", font_description="Sans 14", markup_mode=True)

    render_text(cr1, text_style, x=2, y=2)
    render_text(cr2, markup_style, x=2, y=2)
    s1 = cr1.get_target()
    s2 = cr2.get_target()
    assert isinstance(s1, cairo.ImageSurface)
    assert isinstance(s2, cairo.ImageSurface)
    s1.flush()
    s2.flush()
    assert bytes(s1.get_data()) != bytes(s2.get_data())


# ---------------------------------------------------------------------------
# render_text_to_surface
# ---------------------------------------------------------------------------


@requires_pango
def test_render_text_to_surface_pads_around_outline():
    style = TextStyle(
        text="X",
        font_description="Sans 24",
        outline_offsets=OUTLINE_OFFSETS_8,
    )
    surface, sw, sh = render_text_to_surface(style, padding_px=4)
    # Surface dimensions == measured text + 2 * padding.
    measure_cr = _ctx()
    text_w, text_h = measure_text(measure_cr, style)
    assert sw == text_w + 8
    assert sh == text_h + 8
    assert surface.get_width() == sw
    assert surface.get_height() == sh


@requires_pango
def test_render_text_to_surface_draws_into_returned_surface():
    style = TextStyle(
        text="hello",
        font_description="Sans 18",
        color_rgba=(1.0, 1.0, 1.0, 1.0),
    )
    surface, _, _ = render_text_to_surface(style)
    surface.flush()
    assert any(b != 0 for b in bytes(surface.get_data()))


# ---------------------------------------------------------------------------
# TextContent change-detection
# ---------------------------------------------------------------------------


def test_text_content_initial_hash_set():
    content = TextContent(style=TextStyle(text="hello"))
    # Same style → no change.
    result = content.update(TextStyle(text="hello"))
    assert isinstance(result, TextChange)
    assert result.changed is False


def test_text_content_detects_text_change():
    content = TextContent(style=TextStyle(text="hello"))
    result = content.update(TextStyle(text="world"))
    assert result.changed is True


def test_text_content_detects_color_change():
    content = TextContent(style=TextStyle(text="hello", color_rgba=(1, 1, 1, 1)))
    result = content.update(TextStyle(text="hello", color_rgba=(0, 0, 0, 1)))
    assert result.changed is True


def test_text_content_detects_font_change():
    content = TextContent(style=TextStyle(text="hello", font_description="Sans 12"))
    result = content.update(TextStyle(text="hello", font_description="Sans 16"))
    assert result.changed is True


def test_text_content_update_persists_new_style():
    content = TextContent(style=TextStyle(text="hello"))
    content.update(TextStyle(text="world"))
    assert content.style.text == "world"


# ---------------------------------------------------------------------------
# Migration smoke checks — refactored callers still produce surfaces
# ---------------------------------------------------------------------------


@requires_pango
def test_overlay_zone_rebuild_surface_via_helper():
    """OverlayZone._rebuild_surface should populate _cached_surface using
    the shared text_render helper after the Phase 3c migration."""
    from agents.studio_compositor.overlay_zones import OverlayZone

    config = {
        "id": "test-zone",
        "file": "/tmp/nonexistent-file-for-test.md",
        "x": 10,
        "y": 10,
        "max_width": 200,
        "font_desc": "Sans 14",
        "color": (1.0, 1.0, 1.0, 1.0),
    }
    zone = OverlayZone(config)
    zone._pango_markup = "hello world"  # noqa: SLF001 — direct state setup
    cr = _ctx()
    zone._rebuild_surface(cr)  # noqa: SLF001
    assert zone._cached_surface is not None  # noqa: SLF001
    sw, sh = zone._cached_surface_size  # noqa: SLF001
    assert sw > 0
    assert sh > 0
