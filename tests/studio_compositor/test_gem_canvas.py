"""Tests for GEM CP437 glyph canvas — raster grid renderer.

Design spec: docs/research/2026-04-19-gem-ward-design.md sections 3, 4, 5, 8.
"""

from __future__ import annotations

import json
from pathlib import Path

from agents.studio_compositor.gem_canvas import (
    BLOCK_CHARS,
    BOX_DRAW_CHARS,
    CELL_SIZE_PX,
    GEM_SPEAKING_BRIGHTNESS_MULT,
    GRID_COLS,
    GRID_ROWS,
    MAX_DENSITY,
    MAX_KEYFRAMES,
    CompositionFrame,
    GemComposition,
    GemSubState,
    GlyphCanvas,
    GlyphCell,
    classify_glyph,
    is_box_draw,
    is_braille,
    read_composition,
)

# ── GlyphCell ─────────────────────────────────────────────────────────────


def test_glyph_cell_defaults() -> None:
    cell = GlyphCell()
    assert cell.glyph == ""
    assert cell.role == "content"
    assert cell.size_class == "normal"
    assert cell.opacity == 1.0


def test_glyph_cell_frozen() -> None:
    cell = GlyphCell(glyph="█", role="emphasis")
    assert cell.glyph == "█"
    assert cell.role == "emphasis"


# ── GlyphCanvas ──────────────────────────────────────────────────────────


def test_glyph_canvas_dimensions() -> None:
    canvas = GlyphCanvas()
    assert canvas.cols == GRID_COLS
    assert canvas.rows == GRID_ROWS
    assert len(canvas.cells) == GRID_ROWS
    assert len(canvas.cells[0]) == GRID_COLS


def test_glyph_canvas_starts_empty() -> None:
    canvas = GlyphCanvas()
    assert canvas.density() == 0.0


def test_glyph_canvas_set_cell() -> None:
    canvas = GlyphCanvas()
    canvas.set_cell(0, 0, "█", role="content")
    assert canvas.cells[0][0].glyph == "█"
    assert canvas.cells[0][0].role == "content"


def test_glyph_canvas_set_cell_clips_oob() -> None:
    canvas = GlyphCanvas()
    canvas.set_cell(-1, 0, "x")
    canvas.set_cell(0, -1, "x")
    canvas.set_cell(999, 0, "x")
    canvas.set_cell(0, 999, "x")
    assert canvas.density() == 0.0


def test_glyph_canvas_write_text() -> None:
    canvas = GlyphCanvas()
    written = canvas.write_text(0, 0, "ACID", role="emphasis")
    assert written == 4
    assert canvas.cells[0][0].glyph == "A"
    assert canvas.cells[0][3].glyph == "D"
    assert canvas.cells[0][0].role == "emphasis"


def test_glyph_canvas_write_text_clips() -> None:
    canvas = GlyphCanvas()
    written = canvas.write_text(0, GRID_COLS - 2, "LONG", role="content")
    assert written == 2


def test_glyph_canvas_write_box_single() -> None:
    canvas = GlyphCanvas()
    canvas.write_box(0, 0, 5, 3)
    assert canvas.cells[0][0].glyph == "┌"
    assert canvas.cells[0][4].glyph == "┐"
    assert canvas.cells[2][0].glyph == "└"
    assert canvas.cells[2][4].glyph == "┘"
    assert canvas.cells[0][2].glyph == "─"
    assert canvas.cells[1][0].glyph == "│"
    assert canvas.cells[0][0].role == "box_draw"


def test_glyph_canvas_write_box_double() -> None:
    canvas = GlyphCanvas()
    canvas.write_box(0, 0, 5, 3, double=True)
    assert canvas.cells[0][0].glyph == "╔"
    assert canvas.cells[0][4].glyph == "╗"
    assert canvas.cells[2][0].glyph == "╚"
    assert canvas.cells[2][4].glyph == "╝"
    assert canvas.cells[0][2].glyph == "═"
    assert canvas.cells[1][0].glyph == "║"


def test_glyph_canvas_density() -> None:
    canvas = GlyphCanvas()
    total = GRID_ROWS * GRID_COLS
    canvas.write_text(0, 0, "X" * GRID_COLS)
    assert abs(canvas.density() - GRID_COLS / total) < 0.001


def test_glyph_canvas_clear() -> None:
    canvas = GlyphCanvas()
    canvas.write_text(0, 0, "test")
    assert canvas.density() > 0
    canvas.clear()
    assert canvas.density() == 0.0


def test_glyph_canvas_from_row_strings() -> None:
    rows = [
        "┌─ test ─┐",
        "│ hello  │",
        "└────────┘",
    ]
    canvas = GlyphCanvas.from_row_strings(rows)
    assert canvas.cells[0][0].glyph == "┌"
    assert canvas.cells[0][0].role == "box_draw"
    assert canvas.cells[1][2].glyph == "h"
    assert canvas.cells[1][2].role == "content"


def test_glyph_canvas_from_row_strings_emphasis() -> None:
    rows = ["ACIDIC drift"]
    canvas = GlyphCanvas.from_row_strings(
        rows,
        emphasis_words=("drift",),
        banner_word="ACIDIC",
    )
    # Banner word should have banner role.
    assert canvas.cells[0][0].role == "banner"
    # Emphasis word should have emphasis role.
    # "drift" starts at column 7
    assert canvas.cells[0][7].role == "emphasis"


def test_glyph_canvas_from_row_strings_clips() -> None:
    rows = ["x" * 200]  # Much wider than GRID_COLS.
    canvas = GlyphCanvas.from_row_strings(rows)
    assert canvas.density() == GRID_COLS / (GRID_ROWS * GRID_COLS)


# ── CP437 glyph classification ───────────────────────────────────────────


def test_box_draw_chars_set() -> None:
    for ch in "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬":
        assert ch in BOX_DRAW_CHARS


def test_block_chars_set() -> None:
    for ch in "░▒▓█":
        assert ch in BLOCK_CHARS


def test_classify_glyph_box_draw() -> None:
    assert classify_glyph("─") == "box_draw"
    assert classify_glyph("╔") == "box_draw"


def test_classify_glyph_blocks() -> None:
    assert classify_glyph("█") == "content"
    assert classify_glyph("░") == "content"


def test_classify_glyph_braille() -> None:
    assert classify_glyph("⠿") == "muted"
    assert is_braille("⠿")
    assert not is_braille("A")


def test_classify_glyph_ascii() -> None:
    assert classify_glyph("A") == "content"
    assert classify_glyph(" ") == "content"


def test_is_box_draw() -> None:
    assert is_box_draw("║")
    assert not is_box_draw("A")


# ── GemComposition schema ────────────────────────────────────────────────


def test_gem_composition_defaults() -> None:
    comp = GemComposition()
    assert comp.composition_id == ""
    assert comp.keyframes == ()
    assert comp.compose_hold_s == 3.0
    assert comp.anchor == "cc"


def test_composition_frame_defaults() -> None:
    frame = CompositionFrame()
    assert frame.glyphs == ()
    assert frame.duration_ms == 1000
    assert frame.transition_from_prev == "zero-cut"


def _write_composition(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_read_composition_valid(tmp_path: Path) -> None:
    path = tmp_path / "comp.json"
    _write_composition(
        path,
        {
            "composition_id": "test-1",
            "keyframes": [
                {"glyphs": ["hello", "world"], "duration_ms": 500},
            ],
            "emphasis_words": ["hello"],
            "banner_word": "world",
            "compose_hold_s": 2.0,
            "anchor": "tl",
            "created_at": 1000.0,
        },
    )
    comp = read_composition(path)
    assert comp is not None
    assert comp.composition_id == "test-1"
    assert len(comp.keyframes) == 1
    assert comp.keyframes[0].glyphs == ("hello", "world")
    assert comp.emphasis_words == ("hello",)
    assert comp.banner_word == "world"
    assert comp.compose_hold_s == 2.0
    assert comp.anchor == "tl"


def test_read_composition_missing_file(tmp_path: Path) -> None:
    assert read_composition(tmp_path / "missing.json") is None


def test_read_composition_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not json")
    assert read_composition(path) is None


def test_read_composition_no_keyframes(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    _write_composition(path, {"keyframes": []})
    assert read_composition(path) is None


def test_read_composition_too_many_keyframes(tmp_path: Path) -> None:
    path = tmp_path / "many.json"
    kfs = [{"glyphs": [f"frame-{i}"], "duration_ms": 100} for i in range(MAX_KEYFRAMES + 1)]
    _write_composition(path, {"keyframes": kfs})
    assert read_composition(path) is None


def test_read_composition_banner_word_length_limit(tmp_path: Path) -> None:
    path = tmp_path / "long_banner.json"
    _write_composition(
        path,
        {
            "keyframes": [{"glyphs": ["test"]}],
            "banner_word": "VERYLONGWORD1",  # 13 chars, > 12 limit
        },
    )
    comp = read_composition(path)
    assert comp is not None
    assert comp.banner_word is None  # Rejected by I10


def test_read_composition_clamps_hold(tmp_path: Path) -> None:
    path = tmp_path / "clamp.json"
    _write_composition(
        path,
        {
            "keyframes": [{"glyphs": ["test"]}],
            "compose_hold_s": 99.0,
        },
    )
    comp = read_composition(path)
    assert comp is not None
    assert comp.compose_hold_s == 10.0


def test_read_composition_invalid_transition(tmp_path: Path) -> None:
    path = tmp_path / "bad_trans.json"
    _write_composition(
        path,
        {
            "keyframes": [{"glyphs": ["test"], "transition_from_prev": "fade"}],
        },
    )
    comp = read_composition(path)
    assert comp is not None
    assert comp.keyframes[0].transition_from_prev == "zero-cut"


def test_read_composition_clamps_duration(tmp_path: Path) -> None:
    path = tmp_path / "dur.json"
    _write_composition(
        path,
        {
            "keyframes": [{"glyphs": ["test"], "duration_ms": 50}],
        },
    )
    comp = read_composition(path)
    assert comp is not None
    assert comp.keyframes[0].duration_ms == 100  # Clamped to min


# ── GemSubState ──────────────────────────────────────────────────────────


def test_gem_sub_state_values() -> None:
    assert GemSubState.FILL == "fill"
    assert GemSubState.EMERGING == "emerging"
    assert GemSubState.PLAYING == "playing"
    assert GemSubState.RESOLVING == "resolving"
    assert GemSubState.DECAYING == "decaying"


# ── Constants ────────────────────────────────────────────────────────────


def test_grid_dimensions_match_spec() -> None:
    """Design spec section 3.1: 115 cols x 15 rows at 16 px cell pitch."""
    assert GRID_COLS == 115
    assert GRID_ROWS == 15
    assert CELL_SIZE_PX == 16
    assert GRID_COLS * CELL_SIZE_PX == 1840
    assert GRID_ROWS * CELL_SIZE_PX == 240


def test_max_density_matches_spec() -> None:
    """Design spec section 5, I6: 45% density ceiling."""
    assert MAX_DENSITY == 0.45


def test_max_keyframes_matches_spec() -> None:
    """Design spec section 5, I7: 12 keyframes max."""
    assert MAX_KEYFRAMES == 12


def test_speaking_brightness_mult() -> None:
    """Design spec section 3.5: 1.22x brightness when speaking."""
    assert GEM_SPEAKING_BRIGHTNESS_MULT == 1.22
