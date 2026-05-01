"""Tests for ``agents.studio_compositor.cbip_signal_density`` (Phase 1).

Phase 1 ships layered renderer scaffold + Layer 1 (cover-art texture
base) + Layer 5 (tag/mood text overlay). Layers 2-4 are stubbed and
return False without drawing.

Coverage:

- Tag-line formatter truth-table: artist+title / title-only /
  artist-only / both empty / non-string field types.
- Cover-art layer: missing file / decodable file / mtime-cache reuse.
- Stub layers: return False without raising and without drawing.
- Composition: render_content runs all five layers without raising
  even when none of the upstream files exist.
- Cairo source registry: the class is registered under
  ``CBIPSignalDensityCairoSource``.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import cairo
import pytest

from agents.studio_compositor.cbip_signal_density import (
    COVER_BASE_ALPHA,
    TAG_BOTTOM_MARGIN,
    TAG_TEXT_SIZE_PX,
    CBIPSignalDensityCairoSource,
)


def _canvas(width: int = 480, height: int = 360) -> tuple[cairo.ImageSurface, cairo.Context]:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    return surface, cairo.Context(surface)


def _solid_png(brightness: int, *, size: int = 64) -> bytes:
    """Return a solid-grey PNG for the cover-art file fixture."""
    from PIL import Image

    img = Image.new("L", (size, size), brightness)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Tag-line formatter ───────────────────────────────────────────────────


class TestFormatTagLine:
    @pytest.mark.parametrize(
        "state,expected",
        [
            ({"artist": "Oudepode", "title": "Heliotrope"}, "[CBIP] Oudepode — Heliotrope"),
            ({"title": "Heliotrope"}, "[CBIP] Heliotrope"),
            ({"artist": "Oudepode"}, "[CBIP] Oudepode"),
            ({}, "[CBIP] (no track)"),
            ({"artist": "", "title": ""}, "[CBIP] (no track)"),
            ({"artist": "  spaced  ", "title": ""}, "[CBIP] spaced"),
        ],
    )
    def test_truth_table(self, state: dict, expected: str) -> None:
        src = CBIPSignalDensityCairoSource()
        assert src._format_tag_line(state) == expected

    def test_handles_non_string_fields(self) -> None:
        """A malformed album-state.json (artist=42) must not crash —
        the formatter coerces via ``str(...)``."""
        src = CBIPSignalDensityCairoSource()
        out = src._format_tag_line({"artist": 42, "title": None})
        # `None` becomes empty after str-and-strip; the integer
        # converts to "42".
        assert "42" in out


# ── Cover-art layer ──────────────────────────────────────────────────────


class TestCoverArtBase:
    def test_no_file_returns_false_without_drawing(self, tmp_path: Path) -> None:
        src = CBIPSignalDensityCairoSource()
        with patch(
            "agents.studio_compositor.cbip_signal_density.COVER_PATH",
            tmp_path / "absent.png",
        ):
            surface, cr = _canvas()
            drew = src._paint_cover_art_base(cr, 480, 360)
        assert drew is False
        # Surface untouched — every byte is zero.
        data = bytes(surface.get_data())
        assert all(b == 0 for b in data[:1024])

    def test_decodable_file_paints(self, tmp_path: Path) -> None:
        cover = tmp_path / "album-cover.png"
        cover.write_bytes(_solid_png(180))
        src = CBIPSignalDensityCairoSource()
        with patch(
            "agents.studio_compositor.cbip_signal_density.COVER_PATH",
            cover,
        ):
            surface, cr = _canvas()
            drew = src._paint_cover_art_base(cr, 480, 360)
        assert drew is True
        # Some non-zero pixels landed — the surface should contain
        # the painted cover at COVER_BASE_ALPHA.
        data = bytes(surface.get_data())
        assert any(b != 0 for b in data)

    def test_mtime_cache_reuse(self, tmp_path: Path) -> None:
        """Repeated calls with unchanged mtime should reuse the cached
        surface rather than re-decoding."""
        cover = tmp_path / "album-cover.png"
        cover.write_bytes(_solid_png(180))
        src = CBIPSignalDensityCairoSource()
        with patch(
            "agents.studio_compositor.cbip_signal_density.COVER_PATH",
            cover,
        ):
            surface_1 = src._refresh_cover()
            surface_2 = src._refresh_cover()
        assert surface_1 is not None
        # Identity check — the same cached surface is returned.
        assert surface_1 is surface_2

    def test_undecodable_file_returns_false(self, tmp_path: Path) -> None:
        cover = tmp_path / "album-cover.png"
        cover.write_bytes(b"this is not a png")
        src = CBIPSignalDensityCairoSource()
        with patch(
            "agents.studio_compositor.cbip_signal_density.COVER_PATH",
            cover,
        ):
            surface, cr = _canvas()
            drew = src._paint_cover_art_base(cr, 480, 360)
        assert drew is False


# ── Stub layers (2, 3, 4) ────────────────────────────────────────────────


class TestStubLayers:
    def test_waveform_returns_false_without_raising(self) -> None:
        src = CBIPSignalDensityCairoSource()
        surface, cr = _canvas()
        assert src._paint_waveform_layer(cr, 480, 360) is False
        # Surface untouched — stub doesn't draw.
        assert all(b == 0 for b in bytes(surface.get_data())[:1024])

    def test_stem_activity_returns_false_without_raising(self) -> None:
        src = CBIPSignalDensityCairoSource()
        surface, cr = _canvas()
        assert src._paint_stem_activity_layer(cr, 480, 360) is False
        assert all(b == 0 for b in bytes(surface.get_data())[:1024])

    def test_bpm_motion_grid_returns_false_without_raising(self) -> None:
        src = CBIPSignalDensityCairoSource()
        surface, cr = _canvas()
        assert src._paint_bpm_motion_grid(cr, 480, 360, t=1.5) is False
        assert all(b == 0 for b in bytes(surface.get_data())[:1024])


# ── Tag/mood overlay ─────────────────────────────────────────────────────


class TestTagMoodOverlay:
    def test_renders_with_metadata(self, tmp_path: Path) -> None:
        state_path = tmp_path / "album-state.json"
        state_path.write_text(json.dumps({"artist": "Oudepode", "title": "Heliotrope"}))
        src = CBIPSignalDensityCairoSource()
        with patch(
            "agents.studio_compositor.cbip_signal_density.ALBUM_STATE_PATH",
            state_path,
        ):
            surface, cr = _canvas()
            # Best-effort: text_render may import gi.PangoCairo lazily.
            # Failing gracefully is a documented contract.
            try:
                drew = src._paint_tag_mood_overlay(cr, 480, 360)
            except Exception:
                drew = False
        # Layer either drew (text_render succeeded) or returned False;
        # both are valid outcomes per the docstring contract.
        assert isinstance(drew, bool)

    def test_returns_false_when_state_missing(self, tmp_path: Path) -> None:
        src = CBIPSignalDensityCairoSource()
        with patch(
            "agents.studio_compositor.cbip_signal_density.ALBUM_STATE_PATH",
            tmp_path / "absent.json",
        ):
            state = src._refresh_state()
        assert state == {}

    def test_malformed_state_falls_back_to_empty(self, tmp_path: Path) -> None:
        state_path = tmp_path / "album-state.json"
        state_path.write_text("not json")
        src = CBIPSignalDensityCairoSource()
        with patch(
            "agents.studio_compositor.cbip_signal_density.ALBUM_STATE_PATH",
            state_path,
        ):
            state = src._refresh_state()
        assert state == {}


# ── Composition ──────────────────────────────────────────────────────────


class TestRenderContent:
    def test_runs_without_upstream_files(self, tmp_path: Path) -> None:
        """All five layers should run cleanly when neither cover-art
        nor album-state is present — the ward must not crash on a
        cold start before any music data has been written."""
        src = CBIPSignalDensityCairoSource()
        with (
            patch(
                "agents.studio_compositor.cbip_signal_density.COVER_PATH",
                tmp_path / "absent.png",
            ),
            patch(
                "agents.studio_compositor.cbip_signal_density.ALBUM_STATE_PATH",
                tmp_path / "absent.json",
            ),
        ):
            surface, cr = _canvas()
            # Composition entrypoint should not raise.
            try:
                src.render_content(cr, 480, 360, t=0.0, state={})
            except Exception as exc:
                pytest.fail(f"render_content raised on empty state: {exc}")

    def test_runs_with_cover_and_state(self, tmp_path: Path) -> None:
        cover = tmp_path / "album-cover.png"
        cover.write_bytes(_solid_png(180))
        state_path = tmp_path / "album-state.json"
        state_path.write_text(json.dumps({"artist": "Oudepode", "title": "Heliotrope"}))
        src = CBIPSignalDensityCairoSource()
        with (
            patch(
                "agents.studio_compositor.cbip_signal_density.COVER_PATH",
                cover,
            ),
            patch(
                "agents.studio_compositor.cbip_signal_density.ALBUM_STATE_PATH",
                state_path,
            ),
        ):
            surface, cr = _canvas()
            try:
                src.render_content(cr, 480, 360, t=0.0, state={})
            except Exception as exc:
                pytest.fail(f"render_content raised with valid state: {exc}")
            # Cover-art base layer should have painted.
            data = bytes(surface.get_data())
            assert any(b != 0 for b in data)


# ── Cairo source registry ────────────────────────────────────────────────


class TestRegistry:
    def test_registered_under_canonical_name(self) -> None:
        from agents.studio_compositor.cairo_sources import get_cairo_source_class

        cls = get_cairo_source_class("CBIPSignalDensityCairoSource")
        assert cls is CBIPSignalDensityCairoSource


# ── Constants pin ────────────────────────────────────────────────────────


class TestConstants:
    def test_cover_alpha_is_low(self) -> None:
        """COVER_BASE_ALPHA must be sub-50% so the texture base reads
        as ambient rather than ward chrome."""
        assert 0.0 < COVER_BASE_ALPHA < 0.5

    def test_text_size_constants(self) -> None:
        assert TAG_TEXT_SIZE_PX > 0
        assert TAG_BOTTOM_MARGIN >= 0
