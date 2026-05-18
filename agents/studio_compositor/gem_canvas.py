"""GEM CP437 glyph canvas — raster grid renderer for the GEM ward.

Design spec: ``docs/research/2026-04-19-gem-ward-design.md`` sections 3, 4, 8.

The ``GlyphCanvas`` is a 2D grid of ``GlyphCell`` objects, each holding a
single CP437 glyph with a palette role and size class. The canvas maps
directly to the ward geometry: at 16 px cell pitch on a 1840x240 band,
the grid is 115 cols x 15 rows (1725 cells of raster potential).

Content arrives via ``GemComposition`` payloads written atomically to
``/dev/shm/hapax-compositor/gem-composition.json``. Each composition
carries keyframes whose ``glyphs`` field is a list of row strings that
map cell-by-cell onto the canvas. Palette roles are resolved from the
active ``HomagePackage`` — no hardcoded colours.

This module is intentionally separate from ``gem_source.py`` so the data
types and canvas logic can be tested and imported without pulling in the
full CairoSource/HomageTransitionalSource dependency chain.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

# ── Constants (design spec section 3) ─────────────────────────────────────

# Cell pitch in pixels. Px437 IBM VGA 8x16 at "normal" size class renders
# an 8x16 glyph; we use 16x16 cells so the glyph sits centred with
# horizontal padding. Matches HARDM's cell size.
CELL_SIZE_PX = 16

# Approximate glyph width in px for the Px437 IBM VGA font at normal size.
GLYPH_W_PX = 8

# Grid dimensions from ward geometry (1840x240 band).
GRID_COLS = 115  # 1840 / 16
GRID_ROWS = 15  # 240 / 16

# Max density (design spec section 5, I6).
MAX_DENSITY = 0.45

# Max keyframes per composition (design spec section 5, I7).
MAX_KEYFRAMES = 12

# Speaking emphasis brightness multiplier (design spec section 3.5).
GEM_SPEAKING_BRIGHTNESS_MULT = 1.22

# SHM paths.
COMPOSITION_PATH = Path("/dev/shm/hapax-compositor/gem-composition.json")
EMPHASIS_PATH = Path("/dev/shm/hapax-compositor/hardm-emphasis.json")

# ── CP437 glyph vocabulary (design spec section 4.1) ─────────────────────

# Box-drawing characters (U+2500-U+257F).
BOX_DRAW_CHARS = frozenset("─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬╌╎")

# Block elements (U+2580-U+259F).
BLOCK_CHARS = frozenset("▀▁▂▃▄▅▆▇█▉▊▋▌▍▎▏▐░▒▓")

# Shaded/geometric (U+25A0-U+25FF selected).
GEOMETRIC_CHARS = frozenset("■□▣▤▥▦▧▨▩▲▼◆◇○●")

_BRAILLE_START = 0x2800
_BRAILLE_END = 0x28FF


def is_braille(ch: str) -> bool:
    """True if ``ch`` is a single Braille pattern character."""
    return len(ch) == 1 and _BRAILLE_START <= ord(ch) <= _BRAILLE_END


def is_box_draw(ch: str) -> bool:
    """True if ``ch`` is a CP437 box-drawing character."""
    return ch in BOX_DRAW_CHARS


def classify_glyph(ch: str) -> str:
    """Return the palette role key for a single glyph character.

    Role mapping follows design spec section 4.4:
    - Box-draw -> ``box_draw`` (punctuation_colour_role / accent_green)
    - Block elements / geometric -> ``content`` (content_colour_role)
    - Braille density -> ``muted``
    - Printable ASCII -> ``content`` (content_colour_role)
    """
    if is_box_draw(ch):
        return "box_draw"
    if ch in BLOCK_CHARS or ch in GEOMETRIC_CHARS:
        return "content"
    if is_braille(ch):
        return "muted"
    return "content"


# ── Sub-state machine (design spec section 6.2) ──────────────────────────


class GemSubState(StrEnum):
    """Inner sub-states while the outer FSM is in HOLD."""

    FILL = "fill"
    EMERGING = "emerging"
    PLAYING = "playing"
    RESOLVING = "resolving"
    DECAYING = "decaying"


# Sub-state durations (ms).
EMERGING_DURATION_MS = 300
DECAY_DURATION_MS = 1500


# ── Data types ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GlyphCell:
    """A single cell in the CP437 raster grid.

    Each cell holds one glyph character, a palette role for colour
    resolution, and a size class for Pango font selection. Empty cells
    (``glyph == ""`` or ``glyph == " "``) are skipped during rendering.

    Valid roles per design spec section 4.4:
    - ``"content"`` -> content_colour_role (terminal_default)
    - ``"emphasis"`` -> identity_colour_role (bright)
    - ``"banner"`` -> accent_cyan or accent_magenta
    - ``"box_draw"`` -> punctuation_colour_role (accent_green)
    - ``"revision"`` -> accent_red
    - ``"muted"`` -> muted
    """

    glyph: str = ""
    role: str = "content"
    size_class: str = "normal"
    opacity: float = 1.0


@dataclass
class GlyphCanvas:
    """A 2D raster grid of CP437 glyph cells.

    The grid is addressed as ``cells[row][col]``. Empty cells are
    transparent. ``cols`` and ``rows`` default to the ward's standard
    geometry (115x15 at 16 px cell pitch on a 1840x240 band).
    """

    cols: int = GRID_COLS
    rows: int = GRID_ROWS
    cells: list[list[GlyphCell]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.cells:
            self.cells = [
                [GlyphCell() for _ in range(self.cols)] for _ in range(self.rows)
            ]

    def clear(self) -> None:
        """Reset all cells to empty."""
        for row in range(self.rows):
            for col in range(self.cols):
                self.cells[row][col] = GlyphCell()

    def set_cell(
        self,
        row: int,
        col: int,
        glyph: str,
        *,
        role: str = "content",
        size_class: str = "normal",
        opacity: float = 1.0,
    ) -> None:
        """Write a single glyph into the grid. Out-of-bounds writes are clipped."""
        if 0 <= row < self.rows and 0 <= col < self.cols:
            self.cells[row][col] = GlyphCell(
                glyph=glyph, role=role, size_class=size_class, opacity=opacity
            )

    def write_text(
        self,
        row: int,
        col: int,
        text: str,
        *,
        role: str = "content",
        size_class: str = "normal",
        opacity: float = 1.0,
    ) -> int:
        """Write a horizontal text run starting at (row, col).

        Returns the number of cells written.
        """
        written = 0
        for i, ch in enumerate(text):
            c = col + i
            if c >= self.cols:
                break
            if 0 <= row < self.rows:
                self.cells[row][c] = GlyphCell(
                    glyph=ch, role=role, size_class=size_class, opacity=opacity
                )
                written += 1
        return written

    def write_box(
        self,
        top: int,
        left: int,
        width: int,
        height: int,
        *,
        role: str = "box_draw",
        double: bool = False,
        opacity: float = 1.0,
    ) -> None:
        """Draw a CP437 box-draw rectangle on the grid."""
        if double:
            tl, tr, bl, br, h, v = "╔", "╗", "╚", "╝", "═", "║"
        else:
            tl, tr, bl, br, h, v = "┌", "┐", "└", "┘", "─", "│"

        bottom = top + height - 1
        right = left + width - 1
        self.set_cell(top, left, tl, role=role, opacity=opacity)
        self.set_cell(top, right, tr, role=role, opacity=opacity)
        self.set_cell(bottom, left, bl, role=role, opacity=opacity)
        self.set_cell(bottom, right, br, role=role, opacity=opacity)
        for c in range(left + 1, right):
            self.set_cell(top, c, h, role=role, opacity=opacity)
            self.set_cell(bottom, c, h, role=role, opacity=opacity)
        for r in range(top + 1, bottom):
            self.set_cell(r, left, v, role=role, opacity=opacity)
            self.set_cell(r, right, v, role=role, opacity=opacity)

    def density(self) -> float:
        """Return the fraction of non-empty cells (design spec section 5, I6)."""
        total = self.rows * self.cols
        if total == 0:
            return 0.0
        filled = sum(
            1
            for row in self.cells
            for cell in row
            if cell.glyph and cell.glyph != " "
        )
        return filled / total

    @classmethod
    def from_row_strings(
        cls,
        rows: list[str],
        *,
        emphasis_words: tuple[str, ...] = (),
        banner_word: str | None = None,
    ) -> GlyphCanvas:
        """Build a canvas from a list of row strings (design spec section 4.3).

        Each string in ``rows`` maps to one grid row. Characters beyond
        ``GRID_COLS`` are clipped; rows beyond ``GRID_ROWS`` are clipped.
        """
        canvas = cls()
        emphasis_set = {w.lower() for w in emphasis_words}
        banner_lower = banner_word.lower() if banner_word else None
        for r, row_str in enumerate(rows):
            if r >= canvas.rows:
                break
            col = 0
            for ch in row_str:
                if col >= canvas.cols:
                    break
                role = classify_glyph(ch)
                canvas.set_cell(r, col, ch, role=role)
                col += 1
            _apply_word_roles(canvas, r, row_str, emphasis_set, banner_lower)
        return canvas


def _apply_word_roles(
    canvas: GlyphCanvas,
    row: int,
    row_str: str,
    emphasis_set: set[str],
    banner_lower: str | None,
) -> None:
    """Mark emphasis/banner words in a row with their palette roles."""
    for match in re.finditer(r"[A-Za-z]+", row_str):
        word = match.group().lower()
        start_col = match.start()
        end_col = match.end()
        if word == banner_lower:
            target_role = "banner"
        elif word in emphasis_set:
            target_role = "emphasis"
        else:
            continue
        for c in range(start_col, min(end_col, canvas.cols)):
            old = canvas.cells[row][c]
            canvas.cells[row][c] = GlyphCell(
                glyph=old.glyph,
                role=target_role,
                size_class="large" if target_role == "emphasis" else "banner",
                opacity=old.opacity,
            )


# ── Composition schema (design spec section 4.3) ─────────────────────────


@dataclass(frozen=True)
class CompositionFrame:
    """One keyframe in a GemComposition."""

    glyphs: tuple[str, ...] = ()
    duration_ms: int = 1000
    transition_from_prev: Literal[
        "zero-cut", "scroll-h", "scroll-v", "overstrike"
    ] = "zero-cut"


@dataclass(frozen=True)
class GemComposition:
    """A full composition payload written by the gem publisher."""

    composition_id: str = ""
    narrative_seed_id: str | None = None
    keyframes: tuple[CompositionFrame, ...] = ()
    compose_hold_s: float = 3.0
    emphasis_words: tuple[str, ...] = ()
    banner_word: str | None = None
    anchor: Literal[
        "tl", "tc", "tr", "cl", "cc", "cr", "bl", "bc", "br"
    ] = "cc"
    created_at: float = 0.0


def read_composition(path: Path) -> GemComposition | None:
    """Parse a GemComposition from JSON. Returns None on any failure."""
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    keyframes_raw = payload.get("keyframes")
    if not isinstance(keyframes_raw, (list, tuple)) or not keyframes_raw:
        return None
    if len(keyframes_raw) > MAX_KEYFRAMES:
        log.warning(
            "gem: composition has %d keyframes (max %d) -- rejecting",
            len(keyframes_raw),
            MAX_KEYFRAMES,
        )
        return None
    frames: list[CompositionFrame] = []
    for kf in keyframes_raw:
        if not isinstance(kf, dict):
            continue
        glyphs = kf.get("glyphs")
        if not isinstance(glyphs, list):
            continue
        glyphs_tuple = tuple(str(g) for g in glyphs)
        duration = max(100, min(5000, int(kf.get("duration_ms", 1000))))
        transition = kf.get("transition_from_prev", "zero-cut")
        if transition not in ("zero-cut", "scroll-h", "scroll-v", "overstrike"):
            transition = "zero-cut"
        frames.append(
            CompositionFrame(
                glyphs=glyphs_tuple,
                duration_ms=duration,
                transition_from_prev=transition,
            )
        )
    if not frames:
        return None
    emphasis = payload.get("emphasis_words", ())
    if isinstance(emphasis, list):
        emphasis = tuple(str(w) for w in emphasis)
    else:
        emphasis = ()
    banner = payload.get("banner_word")
    if banner is not None:
        banner = str(banner)
        if len(banner) > 12:
            banner = None  # I10: banner word length <= 12
    anchor = payload.get("anchor", "cc")
    if anchor not in ("tl", "tc", "tr", "cl", "cc", "cr", "bl", "bc", "br"):
        anchor = "cc"
    return GemComposition(
        composition_id=str(payload.get("composition_id", "")),
        narrative_seed_id=payload.get("narrative_seed_id"),
        keyframes=tuple(frames),
        compose_hold_s=max(0.5, min(10.0, float(payload.get("compose_hold_s", 3.0)))),
        emphasis_words=emphasis,
        banner_word=banner,
        anchor=anchor,
        created_at=float(payload.get("created_at", 0.0)),
    )


def read_emphasis_state(path: Path = EMPHASIS_PATH) -> str:
    """Read the speaking/quiescent emphasis flag from CPAL."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return str(data.get("state", "quiescent"))
    except Exception:
        return "quiescent"


def resolve_cell_colour(
    cell: GlyphCell,
    package: Any,
    speaking: bool,
    banner_accent_counter: int = 0,
) -> tuple[float, float, float, float]:
    """Map a cell's role to an RGBA colour from the active HOMAGE package.

    Colour mapping per design spec section 4.4.
    """
    if package is None:
        return (0.95, 0.92, 0.78, 1.0)

    role_map = {
        "content": package.grammar.content_colour_role,
        "emphasis": package.grammar.identity_colour_role,
        "banner": "accent_cyan" if banner_accent_counter % 2 == 0 else "accent_magenta",
        "box_draw": package.grammar.punctuation_colour_role,
        "revision": "accent_red",
        "muted": "muted",
    }
    palette_role = role_map.get(cell.role, package.grammar.content_colour_role)
    try:
        r, g, b, a = package.resolve_colour(palette_role)
    except Exception:
        return (0.95, 0.92, 0.78, 1.0)

    if speaking and cell.role != "muted":
        r = min(1.0, r * GEM_SPEAKING_BRIGHTNESS_MULT)
        g = min(1.0, g * GEM_SPEAKING_BRIGHTNESS_MULT)
        b = min(1.0, b * GEM_SPEAKING_BRIGHTNESS_MULT)

    return (r, g, b, a)


def font_for_size_class(size_class: str, package: Any) -> str:
    """Return a Pango font description for the given size class.

    Size classes map to point sizes per design spec section 3.3:
    - compact: 8 pt
    - normal: 12 pt (default)
    - large: 24 pt
    - banner: 48 pt
    """
    size_map = {"compact": 8, "normal": 12, "large": 24, "banner": 48}
    pt = size_map.get(size_class, 12)
    family = "Px437 IBM VGA 8x16"
    if package is not None:
        try:
            family = package.typography.primary_font_family
        except Exception:
            pass
    return f"{family} {pt}"


__all__ = [
    "BLOCK_CHARS",
    "BOX_DRAW_CHARS",
    "CELL_SIZE_PX",
    "COMPOSITION_PATH",
    "CompositionFrame",
    "DECAY_DURATION_MS",
    "EMERGING_DURATION_MS",
    "EMPHASIS_PATH",
    "GEM_SPEAKING_BRIGHTNESS_MULT",
    "GEOMETRIC_CHARS",
    "GLYPH_W_PX",
    "GRID_COLS",
    "GRID_ROWS",
    "GemComposition",
    "GemSubState",
    "GlyphCanvas",
    "GlyphCell",
    "MAX_DENSITY",
    "MAX_KEYFRAMES",
    "classify_glyph",
    "font_for_size_class",
    "is_box_draw",
    "is_braille",
    "read_composition",
    "read_emphasis_state",
    "resolve_cell_colour",
]
