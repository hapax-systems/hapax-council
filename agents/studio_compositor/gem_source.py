"""GEM (Graffiti Emphasis Mural) — Hapax-authored CP437 raster expression ward.

The 15th HOMAGE ward, operator-directed 2026-04-19 (commit ``b6ec4a723``).
Replaces the captions strip in the lower-band geometry. Where captions
showed STT transcription, GEM gives Hapax a raster canvas to author
emphasized text, abstract glyph compositions, and frame-by-frame visual
sequences in BitchX CP437 grammar.

Design: ``docs/research/2026-04-19-gem-ward-design.md``.
Brainstorm (Candidate C): ``docs/research/2026-04-22-gem-rendering-redesign-brainstorm.md``.
Profile: ``config/ward_enhancement_profiles.yaml::wards.gem``.
Producer: ``agents/hapax_daimonion/gem_producer.py`` (writes
``/dev/shm/hapax-gem/gem-frames.json``; legacy compatibility reader:
``/dev/shm/hapax-compositor/gem-frames.json``).

Render contract:

* CP437 / Px437 IBM VGA only — no anti-aliased proportional fonts.
* BitchX mIRC-16 palette via the active ``HomagePackage``.
* Frame-by-frame sequences: producer writes ``frames: list[GemFrame]``
  with explicit ``hold_ms`` per frame; this class advances through them.
* AntiPattern enforcement: any frame containing ``emoji`` glyphs is
  refused at render time and a fallback frame is shown.
* HARDM gate (anti-anthropomorphization): a Pearson face-correlation
  scan over the rendered pixels that exceeds 0.6 triggers fallback.

Candidate C — Phase 1 (operator decision 2026-04-22, "C and then go,
start with 24 Hz, yes text wins"): a Gray-Scott reaction-diffusion
substrate (`gem_substrate.GemSubstrate`) is rendered as a background
layer beneath the text mural. Substrate brightness is hard-clamped via
`SUBSTRATE_BRIGHTNESS_CEILING` (0.35) so the brightest substrate cell is
always dimmer than the text layer (alpha ≥0.95). The substrate is *not*
a recruitable affordance and *not* a perception input; it is a fixed
background process owned by this renderer. Phase 2 will add nested CP437
box-draw rooms on top of the substrate; Phase 3 will add per-room
fragment punch-in. v1 single-text frames continue to work unchanged.

CP437 Glyph Canvas (design spec §3, §4, §8):

The ``GlyphCanvas`` is a raster grid of ``GlyphCell`` objects. Each cell
holds a single CP437 glyph, a palette role, and a size class. The canvas
dimensions derive from the ward geometry: at 16 px cell pitch on a
1840×240 band, the grid is 115 cols × 15 rows (1725 cells of raster
potential). The renderer walks the grid cell-by-cell, rendering each
non-empty cell via Pango at its grid position.

Content arrives via two paths:

1. **Legacy frames** — ``GemFrame`` text/layers from ``gem-frames.json``.
   Rendered as graffiti layers (the existing v1 path).
2. **Composition** — ``GemComposition`` from
   ``/dev/shm/hapax-compositor/gem-composition.json`` (design spec §4.3).
   Each composition carries ``keyframes`` whose ``glyphs`` field is a
   list of row strings that map directly onto the glyph canvas. The
   renderer parses these into ``GlyphCell`` arrays and paints them
   cell-by-cell with per-content-class palette roles.

When a ``GemComposition`` is active it takes priority over legacy frames.
When no composition is published (or all keyframes are consumed), the
renderer falls back to legacy frames, then to the governance-axiom
rotation, then to the static fallback.
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from . import metrics
from .homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo

    from .gem_substrate import NDArrayF32
else:
    NDArrayF32 = object

log = logging.getLogger(__name__)

DEFAULT_FRAMES_PATH = Path("/dev/shm/hapax-gem/gem-frames.json")
LEGACY_FRAMES_PATH = Path("/dev/shm/hapax-compositor/gem-frames.json")
COMPOSITION_PATH = Path("/dev/shm/hapax-compositor/gem-composition.json")
EMPHASIS_PATH = Path("/dev/shm/hapax-compositor/hardm-emphasis.json")
DEFAULT_FONT_DESCRIPTION = "Px437 IBM VGA 8x16 32"
FALLBACK_FRAME_TEXT = "» hapax «"
MIN_FRAME_HOLD_MS = 400
GOVERNANCE_HOLD_MS = 6000
MAX_LAYER_OFFSET_PX = 128
# The room layer remains disabled until the artifact-leak path is reworked.
ROOM_LAYER_RENDER_ENABLED = False

# ── CP437 glyph canvas constants (design spec §3) ────────────────────────

# Cell pitch in pixels. Px437 IBM VGA 8x16 at the "normal" size class
# renders an 8×16 glyph; we use 16×16 cells so the glyph sits in the
# centre of a square cell with horizontal padding. This matches HARDM's
# cell size.
CELL_SIZE_PX = 16

# Glyph widths in px for the Px437 IBM VGA font at each size class.
# These are the approximate layout widths Pango reports; actual metrics
# may vary by ±1 px depending on the font build.
_GLYPH_W_PX = 8  # 8x16 glyph width at "normal" size

# Grid dimensions derived from the ward geometry (1840×240 band).
GRID_COLS = 115  # 1840 / 16
GRID_ROWS = 15  # 240 / 16

# Maximum composition density (design spec §5, I6). A keyframe exceeding
# this fraction of filled cells is rejected by the anti-face checker.
MAX_DENSITY = 0.45

# Maximum keyframe count per composition (design spec §5, I7).
MAX_KEYFRAMES = 12

# Speaking emphasis brightness multiplier (design spec §3.5). Slightly
# above HARDM's 1.18 because GEM carries more semantic weight.
GEM_SPEAKING_BRIGHTNESS_MULT = 1.22

# Codepoint range Unicode emoji blocks fall into. Conservative — covers
# Misc Symbols & Pictographs, Emoticons, Transport, Supplemental Symbols,
# Symbols and Pictographs Extended-A, plus the variation selector U+FE0F
# that promotes a plain glyph to emoji presentation.
_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001F5FF"  # Misc Symbols & Pictographs
    r"\U0001F600-\U0001F64F"  # Emoticons
    r"\U0001F680-\U0001F6FF"  # Transport & Map
    r"\U0001F900-\U0001F9FF"  # Supplemental Symbols & Pictographs
    r"\U0001FA70-\U0001FAFF"  # Symbols and Pictographs Extended-A
    r"☀-⛿"  # Misc Symbols (☀ ☁ ★ etc.)
    r"✀-➿"  # Dingbats
    r"️]"  # Variation Selector-16 (emoji presentation)
)

# ── CP437 glyph vocabulary (design spec §4.1) ────────────────────────────

# Box-drawing characters (U+2500–U+257F).
BOX_DRAW_CHARS = frozenset("─│┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬╌╎")

# Block elements (U+2580–U+259F).
BLOCK_CHARS = frozenset("▀▁▂▃▄▅▆▇█▉▊▋▌▍▎▏▐░▒▓")

# Shaded/geometric (U+25A0–U+25FF selected).
GEOMETRIC_CHARS = frozenset("■□▣▤▥▦▧▨▩▲▼◆◇○●")

# Braille patterns (U+2800–U+28FF) — detected by range, not enumerated.
_BRAILLE_START = 0x2800
_BRAILLE_END = 0x28FF


def _is_braille(ch: str) -> bool:
    """True if ``ch`` is a single Braille pattern character."""
    return len(ch) == 1 and _BRAILLE_START <= ord(ch) <= _BRAILLE_END


def _is_box_draw(ch: str) -> bool:
    """True if ``ch`` is a CP437 box-drawing character."""
    return ch in BOX_DRAW_CHARS


def _classify_glyph(ch: str) -> str:
    """Return the palette role key for a single glyph character.

    Role mapping follows design spec §4.4:
    - Box-draw → ``punctuation_colour_role`` (accent_green)
    - Block elements / geometric → ``content_colour_role``
    - Braille density → ``muted``
    - Printable ASCII → ``content_colour_role``
    """
    if _is_box_draw(ch):
        return "box_draw"
    if ch in BLOCK_CHARS or ch in GEOMETRIC_CHARS:
        return "content"
    if _is_braille(ch):
        return "muted"
    return "content"


# ── Composition sub-state machine (design spec §6.2) ─────────────────────


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


@dataclass(frozen=True)
class GlyphCell:
    """A single cell in the CP437 raster grid.

    Each cell holds one glyph character, a palette role for colour
    resolution, and a size class for Pango font selection. Empty cells
    (``glyph == ""`` or ``glyph == " "``) are skipped during rendering.

    The ``role`` field maps to the ``HomagePackage.resolve_colour()``
    lookup. Valid roles per design spec §4.4:
    - ``"content"`` → ``content_colour_role`` (terminal_default)
    - ``"emphasis"`` → ``identity_colour_role`` (bright)
    - ``"banner"`` → ``accent_cyan`` or ``accent_magenta``
    - ``"box_draw"`` → ``punctuation_colour_role`` (accent_green)
    - ``"revision"`` → ``accent_red``
    - ``"muted"`` → ``muted``
    """

    glyph: str = ""
    role: str = "content"
    size_class: str = "normal"
    opacity: float = 1.0


@dataclass
class GlyphCanvas:
    """A 2D raster grid of CP437 glyph cells.

    The grid is addressed as ``cells[row][col]``. Empty cells are
    transparent. The canvas provides methods to write text runs, box-draw
    frames, and individual glyphs at grid coordinates.

    ``cols`` and ``rows`` default to the ward's standard geometry
    (115×15 at 16 px cell pitch on a 1840×240 band).
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

        Returns the number of cells written. Characters that would extend
        past the right edge are clipped.
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
        """Draw a CP437 box-draw rectangle on the grid.

        Uses single-line (┌─┐│└┘) or double-line (╔═╗║╚╝) glyphs.
        """
        if double:
            tl, tr, bl, br, h, v = "╔", "╗", "╚", "╝", "═", "║"
        else:
            tl, tr, bl, br, h, v = "┌", "┐", "└", "┘", "─", "│"

        bottom = top + height - 1
        right = left + width - 1
        # Corners.
        self.set_cell(top, left, tl, role=role, opacity=opacity)
        self.set_cell(top, right, tr, role=role, opacity=opacity)
        self.set_cell(bottom, left, bl, role=role, opacity=opacity)
        self.set_cell(bottom, right, br, role=role, opacity=opacity)
        # Horizontal edges.
        for c in range(left + 1, right):
            self.set_cell(top, c, h, role=role, opacity=opacity)
            self.set_cell(bottom, c, h, role=role, opacity=opacity)
        # Vertical edges.
        for r in range(top + 1, bottom):
            self.set_cell(r, left, v, role=role, opacity=opacity)
            self.set_cell(r, right, v, role=role, opacity=opacity)

    def density(self) -> float:
        """Return the fraction of non-empty cells (design spec §5, I6)."""
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
        """Build a canvas from a list of row strings (design spec §4.3).

        Each string in ``rows`` maps to one grid row. Characters beyond
        ``GRID_COLS`` are clipped; rows beyond ``GRID_ROWS`` are clipped.
        Emphasis words get the ``emphasis`` role; the banner word gets
        ``banner``. Box-draw characters auto-detect to ``box_draw`` role.
        """
        canvas = cls()
        emphasis_set = {w.lower() for w in emphasis_words}
        banner_lower = banner_word.lower() if banner_word else None
        for r, row_str in enumerate(rows):
            if r >= canvas.rows:
                break
            # Character-level role assignment based on glyph classification.
            col = 0
            for ch in row_str:
                if col >= canvas.cols:
                    break
                role = _classify_glyph(ch)
                canvas.set_cell(r, col, ch, role=role)
                col += 1
            # Re-scan for emphasis/banner words at the character level.
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
    import re as _re

    for match in _re.finditer(r"[A-Za-z]+", row_str):
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


# ── Composition schema (design spec §4.3) ────────────────────────────────


@dataclass(frozen=True)
class CompositionFrame:
    """One keyframe in a GemComposition (design spec §4.3).

    ``glyphs`` is a list of row strings; each row is a sequence of
    characters to be placed cell-by-cell on the glyph canvas.
    """

    glyphs: tuple[str, ...] = ()
    duration_ms: int = 1000
    transition_from_prev: Literal[
        "zero-cut", "scroll-h", "scroll-v", "overstrike"
    ] = "zero-cut"


@dataclass(frozen=True)
class GemComposition:
    """A full composition payload as written by the gem publisher.

    Schema mirrors design spec §4.3. Written atomically to
    ``/dev/shm/hapax-compositor/gem-composition.json``.
    """

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


def _read_composition(path: Path) -> GemComposition | None:
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
            "gem: composition has %d keyframes (max %d) — rejecting",
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
        glyphs = tuple(str(g) for g in glyphs)
        duration = max(100, min(5000, int(kf.get("duration_ms", 1000))))
        transition = kf.get("transition_from_prev", "zero-cut")
        if transition not in ("zero-cut", "scroll-h", "scroll-v", "overstrike"):
            transition = "zero-cut"
        frames.append(
            CompositionFrame(
                glyphs=glyphs,
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
            banner = None  # I10: banner word length ≤ 12
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


def _read_emphasis_state(path: Path = EMPHASIS_PATH) -> str:
    """Read the speaking/quiescent emphasis flag from CPAL."""
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return str(data.get("state", "quiescent"))
    except Exception:
        return "quiescent"


# ── Legacy frame types (v1 compat) ───────────────────────────────────────


@dataclass(frozen=True)
class GemLayer:
    """One overlapping text layer in a GEM keyframe.

    Layers are centred together with small offsets. They are not geometry
    commands; they are bounded raster-text hints owned by the GEM renderer.
    """

    text: str
    opacity: float = 1.0
    offset_x_px: int = 0
    offset_y_px: int = 0


@dataclass(frozen=True)
class GemFrame:
    """A single keyframe in a GEM mural sequence.

    ``text`` is the frame's canonical textual fragment. ``layers`` carries
    overlapping graffiti-density render hints; if absent the renderer derives
    a bounded multi-layer stack from ``text`` so old producers stay valid.
    """

    text: str
    hold_ms: int = 1500
    layers: tuple[GemLayer, ...] = ()


def build_graffiti_layers(text: str) -> tuple[GemLayer, ...]:
    """Return a dense, non-ticker layer stack for ``text``.

    GEM is a mural band, not a chiron. The stack deliberately overlaps the
    same fragment at small offsets with varied opacity so the lower band reads
    as raster graffiti density rather than a scrolling caption strip.
    """
    safe = text.strip()
    if not safe or contains_emoji(safe):
        safe = FALLBACK_FRAME_TEXT
    return (
        GemLayer(text=f"░▒ {safe} ▒░", opacity=0.36, offset_x_px=-26, offset_y_px=-18),
        GemLayer(text=f"» {safe} «", opacity=0.94, offset_x_px=0, offset_y_px=0),
        GemLayer(text=f"╱╲ {safe} ╲╱", opacity=0.28, offset_x_px=24, offset_y_px=18),
    )


def _build_governance_frames() -> list[GemFrame]:
    """Build GEM frames from live axiom registry, sorted by weight descending.

    Each axiom becomes a frame with its ID and condensed text, formatted in
    CP437 box-draw grammar. Returns empty list if axioms cannot be loaded —
    caller falls back to the static FALLBACK_FRAME_TEXT.
    """
    try:
        from shared.axiom_registry import load_axioms
    except ImportError:
        return []
    try:
        axioms = load_axioms()
    except Exception:
        return []
    if not axioms:
        return []
    frames: list[GemFrame] = []
    for ax in sorted(axioms, key=lambda a: a.weight, reverse=True):
        text = ax.text.strip().replace("\n", " ")
        while "  " in text:
            text = text.replace("  ", " ")
        prefix = f"║ {ax.id.upper()} [{ax.weight}] ║ "
        budget = 80 - len(prefix)
        dot = text.find(". ")
        if 0 < dot <= budget:
            text = text[: dot + 1]
        elif len(text) > budget:
            text = text[: budget - 3] + "..."
        label = f"{prefix}{text}"
        frames.append(
            GemFrame(
                text=label,
                hold_ms=GOVERNANCE_HOLD_MS,
                layers=build_graffiti_layers(label),
            )
        )
    return frames


def _layer_to_payload(layer: GemLayer) -> dict[str, object]:
    return {
        "text": layer.text,
        "opacity": layer.opacity,
        "offset_x_px": layer.offset_x_px,
        "offset_y_px": layer.offset_y_px,
    }


def layer_payloads(layers: tuple[GemLayer, ...]) -> list[dict[str, object]]:
    """Serialize render-layer hints for the GEM frames JSON contract."""
    return [_layer_to_payload(layer) for layer in layers if layer.text.strip()]


def _clamp_opacity(value: object) -> float:
    try:
        return min(1.0, max(0.05, float(value)))
    except (TypeError, ValueError):
        return 1.0


def _clamp_offset(value: object) -> int:
    try:
        return min(MAX_LAYER_OFFSET_PX, max(-MAX_LAYER_OFFSET_PX, int(value)))
    except (TypeError, ValueError):
        return 0


def _parse_layers(entry: dict[str, Any], text: str) -> tuple[GemLayer, ...]:
    layers_raw = entry.get("layers")
    if not isinstance(layers_raw, list):
        return build_graffiti_layers(text)
    layers: list[GemLayer] = []
    for raw in layers_raw:
        if not isinstance(raw, dict):
            continue
        layer_text = raw.get("text")
        if not isinstance(layer_text, str):
            continue
        layer_text = layer_text.strip()
        if not layer_text or contains_emoji(layer_text):
            continue
        layers.append(
            GemLayer(
                text=layer_text,
                opacity=_clamp_opacity(raw.get("opacity", 1.0)),
                offset_x_px=_clamp_offset(raw.get("offset_x_px", 0)),
                offset_y_px=_clamp_offset(raw.get("offset_y_px", 0)),
            )
        )
    return tuple(layers) if len(layers) >= 2 else build_graffiti_layers(text)


def _read_frames(path: Path) -> list[GemFrame]:
    """Parse ``path`` into a list of GemFrames. Empty list on failure.

    Producer writes ``{"frames": [{"text": "...", "hold_ms": 1500}, ...]}``.
    Malformed input degrades gracefully — the renderer falls back to the
    static fallback frame rather than crashing.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        log.debug("gem-frames JSON malformed at %s", path)
        return []
    frames_raw = payload.get("frames") if isinstance(payload, dict) else None
    if not isinstance(frames_raw, list):
        return []
    out: list[GemFrame] = []
    for entry in frames_raw:
        if not isinstance(entry, dict):
            continue
        text = entry.get("text")
        if not isinstance(text, str):
            continue
        if not text.strip():
            continue
        if contains_emoji(text):
            continue
        hold_ms_raw = entry.get("hold_ms", 1500)
        try:
            hold_ms = max(MIN_FRAME_HOLD_MS, int(hold_ms_raw))
        except (TypeError, ValueError):
            hold_ms = 1500
        out.append(GemFrame(text=text, hold_ms=hold_ms, layers=_parse_layers(entry, text)))
    return out


def contains_emoji(text: str) -> bool:
    """Anti-pattern enforcement: True if ``text`` includes any emoji codepoint."""
    return bool(_EMOJI_RE.search(text))


class GemCairoSource(HomageTransitionalSource):
    """HOMAGE ward rendering Hapax-authored CP437 mural sequences.

    Reads keyframes from ``frames_path`` and advances through them at
    each frame's ``hold_ms`` cadence. When the producer is offline or
    every frame is rejected by the anti-pattern gate, falls back to a
    static "» hapax «" frame so the ward remains visibly active.

    Phase 1 CP437 glyph canvas: when a ``GemComposition`` is available
    from ``/dev/shm/hapax-compositor/gem-composition.json``, the renderer
    builds a ``GlyphCanvas`` from the composition's keyframe glyph rows
    and paints cell-by-cell with per-content-class palette roles. The
    composition path takes priority over legacy frames.
    """

    def __init__(
        self,
        *,
        frames_path: Path | None = None,
        composition_path: Path | None = None,
        font_description: str = DEFAULT_FONT_DESCRIPTION,
        enable_substrate: bool = True,
    ) -> None:
        super().__init__(source_id="gem")
        self._frames_path = frames_path or DEFAULT_FRAMES_PATH
        self._legacy_frames_path = None if frames_path is not None else LEGACY_FRAMES_PATH
        self._composition_path = composition_path or COMPOSITION_PATH
        self._font_description = font_description
        self._frames: list[GemFrame] = []
        self._frame_index: int = 0
        self._frame_started_ts: float = 0.0
        self._last_loaded_mtime: float = 0.0
        self._last_loaded_path: Path | None = None
        # Candidate C Phase 1 — Gray-Scott substrate ticked once per render.
        # Lazily constructed so a numpy-less environment doesn't break the
        # source at import time (the render path silently degrades to text-
        # only when the substrate cannot initialize).
        self._enable_substrate = enable_substrate
        self._substrate: object | None = None
        self._substrate_init_attempted = False
        self._governance_frames: list[GemFrame] | None = None
        self._gov_frame_index: int = 0
        self._gov_frame_started_ts: float = 0.0
        # ── Composition state (Phase 1 CP437 glyph canvas) ───────────
        self._composition: GemComposition | None = None
        self._composition_mtime: float = 0.0
        self._composition_kf_index: int = 0
        self._composition_kf_started_ts: float = 0.0
        self._sub_state: GemSubState = GemSubState.FILL
        self._sub_state_started_ts: float = 0.0
        self._canvas: GlyphCanvas = GlyphCanvas()
        # Banner accent rotation counter (design spec §4.4).
        self._banner_accent_counter: int = 0

    # ── CairoSource protocol ───────────────────────────────────────────

    def state(self) -> dict[str, Any]:
        """Refresh frame list when the producer's file changes."""
        self._maybe_reload_composition()
        self._maybe_reload_frames()
        current = self._current_frame()
        elapsed_ms = self._current_elapsed_ms()
        envelope_alpha = 1.0 if not self._frames else _crossfade_alpha(elapsed_ms, current.hold_ms)
        return {
            "text": current.text,
            "hold_ms": current.hold_ms,
            "layers": layer_payloads(current.layers or build_graffiti_layers(current.text)),
            "envelope_alpha": envelope_alpha,
            "frame_index": self._frame_index,
            "frame_count": len(self._frames),
            "sub_state": self._sub_state.value,
            "has_composition": self._composition is not None,
        }

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        # Layer 1 (Candidate C Phase 1) — substrate paints first, beneath text.
        # Step + paint happen before text so text composites on top. The
        # SUBSTRATE_BRIGHTNESS_CEILING enforces "text wins" — substrate
        # peak brightness is 0.35, text alpha is 0.95+.
        self._render_substrate(cr, canvas_w, canvas_h)

        self._render_rooms(cr, canvas_w, canvas_h, t)

        # Advance the composition sub-state machine.
        self._tick_sub_state()

        # Speaking emphasis from CPAL.
        speaking = _read_emphasis_state() == "speaking"

        # Primary render path: composition glyph canvas takes priority.
        if self._composition is not None and self._sub_state not in (
            GemSubState.FILL,
            GemSubState.DECAYING,
        ):
            self._render_composition_canvas(cr, canvas_w, canvas_h, speaking)
            return

        # Decaying: render the canvas with decay dither overlay.
        if self._sub_state == GemSubState.DECAYING:
            decay_progress = self._sub_state_progress(DECAY_DURATION_MS)
            self._render_composition_canvas(
                cr, canvas_w, canvas_h, speaking, decay_alpha=1.0 - decay_progress
            )
            return

        # Legacy path: text layers.
        text = state.get("text") or FALLBACK_FRAME_TEXT
        if not isinstance(text, str):
            text = FALLBACK_FRAME_TEXT
        if contains_emoji(text):
            log.warning("gem: refusing emoji-containing frame %r — falling back", text)
            text = FALLBACK_FRAME_TEXT
        layers = _state_layers(state, text)
        envelope_alpha = _state_envelope_alpha(state)
        self._render_graffiti_layers(cr, canvas_w, canvas_h, layers, envelope_alpha)

    # ── Composition loading (Phase 1 glyph canvas) ─────────────────────

    def _maybe_reload_composition(self) -> None:
        """Check for a new GemComposition at the SHM path."""
        try:
            mtime = self._composition_path.stat().st_mtime
        except OSError:
            return
        if mtime <= self._composition_mtime:
            return
        comp = _read_composition(self._composition_path)
        if comp is None:
            return
        self._composition = comp
        self._composition_mtime = mtime
        self._composition_kf_index = 0
        self._composition_kf_started_ts = time.monotonic()
        self._sub_state = GemSubState.EMERGING
        self._sub_state_started_ts = time.monotonic()
        self._banner_accent_counter += 1
        self._build_canvas_from_keyframe(0)
        log.debug(
            "gem: loaded composition %s (%d keyframes)",
            comp.composition_id,
            len(comp.keyframes),
        )

    def _build_canvas_from_keyframe(self, kf_index: int) -> None:
        """Build a GlyphCanvas from the composition's keyframe at kf_index."""
        if self._composition is None:
            return
        if kf_index >= len(self._composition.keyframes):
            return
        kf = self._composition.keyframes[kf_index]
        self._canvas = GlyphCanvas.from_row_strings(
            list(kf.glyphs),
            emphasis_words=self._composition.emphasis_words,
            banner_word=self._composition.banner_word,
        )

    # ── Sub-state machine (design spec §6.2) ──────────────────────────

    def _tick_sub_state(self) -> None:
        """Advance the inner sub-state machine."""
        now = time.monotonic()
        elapsed_ms = (now - self._sub_state_started_ts) * 1000.0

        if self._sub_state == GemSubState.EMERGING:
            if elapsed_ms >= EMERGING_DURATION_MS:
                self._sub_state = GemSubState.PLAYING
                self._sub_state_started_ts = now

        elif self._sub_state == GemSubState.PLAYING:
            # Advance keyframes within the composition.
            if self._composition is not None:
                kf = self._composition.keyframes[self._composition_kf_index]
                kf_elapsed = (now - self._composition_kf_started_ts) * 1000.0
                if kf_elapsed >= kf.duration_ms:
                    next_idx = self._composition_kf_index + 1
                    if next_idx < len(self._composition.keyframes):
                        self._composition_kf_index = next_idx
                        self._composition_kf_started_ts = now
                        self._build_canvas_from_keyframe(next_idx)
                    else:
                        # All keyframes consumed → resolving.
                        self._sub_state = GemSubState.RESOLVING
                        self._sub_state_started_ts = now

        elif self._sub_state == GemSubState.RESOLVING:
            hold_s = self._composition.compose_hold_s if self._composition else 3.0
            if elapsed_ms >= hold_s * 1000.0:
                self._sub_state = GemSubState.DECAYING
                self._sub_state_started_ts = now

        elif self._sub_state == GemSubState.DECAYING:
            if elapsed_ms >= DECAY_DURATION_MS:
                self._sub_state = GemSubState.FILL
                self._sub_state_started_ts = now
                self._composition = None

    def _sub_state_progress(self, duration_ms: float) -> float:
        """Return progress through the current sub-state in [0.0, 1.0]."""
        elapsed = (time.monotonic() - self._sub_state_started_ts) * 1000.0
        if duration_ms <= 0:
            return 1.0
        return max(0.0, min(1.0, elapsed / duration_ms))

    # ── Glyph canvas rendering ────────────────────────────────────────

    def _render_composition_canvas(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        speaking: bool,
        *,
        decay_alpha: float = 1.0,
    ) -> None:
        """Render the GlyphCanvas cell-by-cell via Pango.

        Each non-empty cell is rendered as a single CP437 glyph at its
        grid position. Colour is resolved from the cell's palette role
        via the active HomagePackage. Speaking emphasis applies a
        brightness multiplier per design spec §3.5.
        """
        try:
            from .homage.rendering import active_package
            from .text_render import TextStyle, render_text
        except ImportError:
            return

        try:
            package = active_package()
        except Exception:
            package = None

        for row_idx in range(self._canvas.rows):
            for col_idx in range(self._canvas.cols):
                cell = self._canvas.cells[row_idx][col_idx]
                if not cell.glyph or cell.glyph == " ":
                    continue

                # Resolve colour from the palette role.
                r, g, b, a = self._resolve_cell_colour(
                    cell, package, speaking
                )
                a = a * cell.opacity * decay_alpha
                if a <= 0.0:
                    continue

                # Cell position on the canvas.
                x = col_idx * CELL_SIZE_PX + (CELL_SIZE_PX - _GLYPH_W_PX) / 2.0
                y = row_idx * CELL_SIZE_PX

                # Font description from size class.
                font_desc = self._font_for_size_class(cell.size_class, package)

                style = TextStyle(
                    text=cell.glyph,
                    font_description=font_desc,
                    color_rgba=(r, g, b, a),
                    outline_offsets=(),
                )
                render_text(cr, style, x=x, y=y)

    def _resolve_cell_colour(
        self,
        cell: GlyphCell,
        package: Any,
        speaking: bool,
    ) -> tuple[float, float, float, float]:
        """Map a cell's role to an RGBA colour from the active package.

        Colour mapping per design spec §4.4:
        - content → content_colour_role
        - emphasis → identity_colour_role (bright)
        - banner → accent_cyan / accent_magenta (alternates per composition)
        - box_draw → punctuation_colour_role (accent_green)
        - revision → accent_red
        - muted → muted
        """
        if package is None:
            return (0.95, 0.92, 0.78, 1.0)

        role_map = {
            "content": package.grammar.content_colour_role,
            "emphasis": package.grammar.identity_colour_role,
            "banner": "accent_cyan" if self._banner_accent_counter % 2 == 0 else "accent_magenta",
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

    def _font_for_size_class(
        self, size_class: str, package: Any
    ) -> str:
        """Return a Pango font description for the given size class.

        Size classes map to point sizes per design spec §3.3:
        - compact: 8 pt
        - normal: 12 pt (default)
        - large: 24 pt
        - banner: 48 pt
        """
        size_map = {
            "compact": 8,
            "normal": 12,
            "large": 24,
            "banner": 48,
        }
        pt = size_map.get(size_class, 12)
        family = "Px437 IBM VGA 8x16"
        if package is not None:
            try:
                family = package.typography.primary_font_family
            except Exception:
                pass
        return f"{family} {pt}"

    # ── Legacy frame advancement ─────────────────────────────────────────

    def _maybe_reload_frames(self) -> None:
        """Reload frames if the producer file has been rewritten."""
        candidate = self._find_current_frames_file()
        if candidate is None:
            return
        path, mtime = candidate
        if path == self._last_loaded_path and mtime <= self._last_loaded_mtime:
            return
        new_frames = _read_frames(path)
        if not new_frames:
            return
        self._frames = new_frames
        self._frame_index = 0
        self._frame_started_ts = time.monotonic()
        self._last_loaded_mtime = mtime
        self._last_loaded_path = path

    def _find_current_frames_file(self) -> tuple[Path, float] | None:
        """Return a readable frames source, preferring canonical GEM SHM."""
        for path in (self._frames_path, self._legacy_frames_path):
            if path is None:
                continue
            try:
                return (path, path.stat().st_mtime)
            except OSError:
                continue
        # File missing — keep existing frames if any; they may still be
        # useful (paint-and-hold behaviour).
        return None

    def _ensure_governance_frames(self) -> list[GemFrame]:
        if self._governance_frames is None:
            self._governance_frames = _build_governance_frames()
        return self._governance_frames

    def _current_governance_frame(self) -> GemFrame:
        """Rotate through governance axiom frames when producer is offline."""
        gov = self._ensure_governance_frames()
        if not gov:
            return GemFrame(
                text=FALLBACK_FRAME_TEXT,
                hold_ms=1500,
                layers=build_graffiti_layers(FALLBACK_FRAME_TEXT),
            )
        now = time.monotonic()
        if self._gov_frame_started_ts == 0.0:
            self._gov_frame_started_ts = now
        current = gov[self._gov_frame_index % len(gov)]
        elapsed_ms = (now - self._gov_frame_started_ts) * 1000.0
        if elapsed_ms >= current.hold_ms:
            self._gov_frame_index = (self._gov_frame_index + 1) % len(gov)
            self._gov_frame_started_ts = now
            current = gov[self._gov_frame_index % len(gov)]
        return current

    def _current_frame(self) -> GemFrame:
        """Return the frame to draw now, advancing the index if hold elapsed."""
        if not self._frames:
            return self._current_governance_frame()
        now = time.monotonic()
        if self._frame_started_ts == 0.0:
            self._frame_started_ts = now
        current = self._frames[self._frame_index]
        elapsed_ms = (now - self._frame_started_ts) * 1000.0
        if elapsed_ms >= current.hold_ms:
            self._frame_index = (self._frame_index + 1) % len(self._frames)
            self._frame_started_ts = now
            current = self._frames[self._frame_index]
        return current

    def _current_elapsed_ms(self) -> float:
        if self._frame_started_ts == 0.0:
            return 0.0
        return max(0.0, (time.monotonic() - self._frame_started_ts) * 1000.0)

    # ── Render ────────────────────────────────────────────────────────

    def _ensure_substrate(self) -> object | None:
        """Lazily construct the Gray-Scott substrate.

        Failure to construct (e.g. numpy missing in a stripped venv) is
        swallowed and recorded so we never retry — the source then renders
        text-only, which preserves the v1 behavior.
        """
        if self._substrate is not None or self._substrate_init_attempted:
            return self._substrate
        self._substrate_init_attempted = True
        if not self._enable_substrate:
            metrics.set_gem_substrate_active(False)
            return None
        try:
            from .gem_substrate import GemSubstrate

            self._substrate = GemSubstrate()
            metrics.set_gem_substrate_active(True)
        except Exception:
            log.warning("gem: substrate init failed — rendering text-only", exc_info=True)
            self._substrate = None
            metrics.set_gem_substrate_active(False)
        return self._substrate

    def _ensure_room_tree(self, canvas_w: int, canvas_h: int):
        if hasattr(self, "_room_tree") and self._room_tree is not None:
            if (
                getattr(self, "_room_tree_w", 0) == canvas_w
                and getattr(self, "_room_tree_h", 0) == canvas_h
            ):
                return self._room_tree
        try:
            from .gem_rooms import compute_room_tree

            self._room_tree = compute_room_tree(canvas_w, canvas_h)
            self._room_tree_w = canvas_w
            self._room_tree_h = canvas_h
            return self._room_tree
        except Exception:
            return None

    def _render_rooms(self, cr, canvas_w: int, canvas_h: int, t: float) -> None:
        if not ROOM_LAYER_RENDER_ENABLED:
            return
        return

    def _render_substrate(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
    ) -> None:
        """Step the Gray-Scott field once and blit it as a dim background."""
        substrate = self._ensure_substrate()
        if substrate is None:
            return
        try:
            substrate.step()
            bright = substrate.brightness_array()
            grid_h, grid_w = bright.shape
        except Exception:
            log.debug("gem: substrate step failed — skipping background", exc_info=True)
            metrics.record_gem_substrate_step_error()
            return

        # Build a Cairo ImageSurface from the brightness grid. Each cell
        # becomes one pixel on the small surface; Cairo upscales to the
        # canvas via a translation+scale paint. We use a content_colour
        # tinted by the brightness so the substrate matches the active
        # HOMAGE palette rather than appearing as a neutral grey.
        try:
            tint = self._substrate_tint_rgba()
            self._paint_substrate_grid(cr, bright, grid_w, grid_h, canvas_w, canvas_h, tint)
            max_brightness = float(bright.max()) if hasattr(bright, "max") else None
            metrics.record_gem_substrate_paint(max_brightness=max_brightness)
        except Exception:
            log.debug("gem: substrate paint failed — skipping", exc_info=True)
            metrics.record_gem_substrate_step_error()

    def _substrate_tint_rgba(self) -> tuple[float, float, float]:
        """Resolve the substrate base RGB from the active HOMAGE palette."""
        try:
            from .homage.rendering import active_package

            package = active_package()
            r, g, b, _ = package.resolve_colour(package.grammar.content_colour_role)
            return (r, g, b)
        except Exception:
            # Gruvbox-dark warm-yellow fallback — same as the text default.
            return (0.95, 0.92, 0.78)

    def _paint_substrate_grid(
        self,
        cr: cairo.Context,
        bright: NDArrayF32,  # np.ndarray[grid_h, grid_w] of float32 in [0, ceiling]
        grid_w: int,
        grid_h: int,
        canvas_w: int,
        canvas_h: int,
        tint_rgb: tuple[float, float, float],
    ) -> None:
        """Upscale the substrate brightness grid into the canvas.

        Builds a transient cairo.ImageSurface at grid resolution, then
        Cairo paints it with a translation+scale matrix. The default
        Cairo filter (BILINEAR for upscaled patterns) gives a soft
        organic look that matches the Gray-Scott aesthetic.
        """
        import struct

        try:
            import cairo as _cairo  # type: ignore[import-not-found]
        except ImportError:
            return

        # Pack float32 brightness × tint RGB into BGRA32 bytes that Cairo
        # ARGB32 surface expects (little-endian: B, G, R, A in memory).
        # Alpha is the brightness value itself so the substrate composites
        # additively-feeling against whatever is beneath.
        tr, tg, tb = tint_rgb
        # Vectorise the per-cell pack via numpy when available; fall back
        # to a Python loop for environments without numpy (tests).
        try:
            import numpy as np

            b_chan = np.clip(bright * tb * 255.0, 0, 255).astype(np.uint8)
            g_chan = np.clip(bright * tg * 255.0, 0, 255).astype(np.uint8)
            r_chan = np.clip(bright * tr * 255.0, 0, 255).astype(np.uint8)
            a_chan = np.clip(bright * 255.0, 0, 255).astype(np.uint8)
            stacked = np.stack([b_chan, g_chan, r_chan, a_chan], axis=-1)
            buf = stacked.tobytes()
        except ImportError:
            buf_parts: list[bytes] = []
            for row in range(grid_h):
                for col in range(grid_w):
                    v = float(bright[row][col])
                    buf_parts.append(
                        struct.pack(
                            "BBBB",
                            int(min(255, max(0, v * tb * 255))),
                            int(min(255, max(0, v * tg * 255))),
                            int(min(255, max(0, v * tr * 255))),
                            int(min(255, max(0, v * 255))),
                        )
                    )
            buf = b"".join(buf_parts)

        stride = grid_w * 4
        surface = _cairo.ImageSurface.create_for_data(
            bytearray(buf), _cairo.FORMAT_ARGB32, grid_w, grid_h, stride
        )
        cr.save()
        try:
            cr.scale(canvas_w / grid_w, canvas_h / grid_h)
            cr.set_source_surface(surface, 0, 0)
            cr.get_source().set_filter(_cairo.FILTER_BILINEAR)
            cr.paint()
        finally:
            cr.restore()

    def _render_graffiti_layers(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        layers: tuple[GemLayer, ...],
        envelope_alpha: float,
    ) -> None:
        for layer in layers:
            alpha = min(1.0, max(0.0, layer.opacity * envelope_alpha))
            if alpha <= 0.0:
                continue
            self._render_text_centered(
                cr,
                canvas_w,
                canvas_h,
                layer.text,
                opacity=alpha,
                offset_x_px=layer.offset_x_px,
                offset_y_px=layer.offset_y_px,
            )

    def _render_text_centered(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        text: str,
        *,
        opacity: float = 1.0,
        offset_x_px: int = 0,
        offset_y_px: int = 0,
    ) -> None:
        """Centre ``text`` in the canvas using Px437 raster + active palette."""
        try:
            from .homage.rendering import active_package
            from .text_render import OUTLINE_OFFSETS_8, TextStyle, render_text_to_surface
        except ImportError:
            return

        try:
            package = active_package()
            r, g, b, a = package.resolve_colour(package.grammar.content_colour_role)
            colour = (r, g, b, a * opacity)
        except Exception:
            colour = (0.95, 0.92, 0.78, opacity)

        style = TextStyle(
            text=text,
            font_description=self._font_description,
            color_rgba=colour,
            outline_color_rgba=(0.0, 0.0, 0.0, 0.85),
            outline_offsets=OUTLINE_OFFSETS_8,
            max_width_px=max(canvas_w - 40, 100),
            wrap="word_char",
            markup_mode=False,
        )
        try:
            surface, sw, sh = render_text_to_surface(style, padding_px=12)
        except Exception:
            log.debug("gem: text-surface render failed for %r", text, exc_info=True)
            return
        x = max(0, (canvas_w - sw) // 2 + offset_x_px)
        y = max(0, (canvas_h - sh) // 2 + offset_y_px)
        cr.set_source_surface(surface, x, y)
        cr.paint()


def _crossfade_alpha(elapsed_ms: float, hold_ms: int) -> float:
    """Envelope each keyframe to avoid blink/strobe transitions."""
    fade_ms = min(600.0, max(200.0, hold_ms / 2.0))
    fade_ms = min(fade_ms, max(1.0, hold_ms / 2.0))
    if elapsed_ms < fade_ms:
        return max(0.0, min(1.0, elapsed_ms / fade_ms))
    remaining_ms = hold_ms - elapsed_ms
    if remaining_ms < fade_ms:
        return max(0.0, min(1.0, remaining_ms / fade_ms))
    return 1.0


def _state_envelope_alpha(state: dict[str, Any]) -> float:
    raw = state.get("envelope_alpha", 1.0)
    try:
        return min(1.0, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return 1.0


def _state_layers(state: dict[str, Any], fallback_text: str) -> tuple[GemLayer, ...]:
    raw_layers = state.get("layers")
    if not isinstance(raw_layers, list):
        return build_graffiti_layers(fallback_text)
    parsed = _parse_layers({"layers": raw_layers}, fallback_text)
    return parsed or build_graffiti_layers(fallback_text)


__all__ = [
    "BLOCK_CHARS",
    "BOX_DRAW_CHARS",
    "CELL_SIZE_PX",
    "COMPOSITION_PATH",
    "CompositionFrame",
    "DEFAULT_FRAMES_PATH",
    "FALLBACK_FRAME_TEXT",
    "GEM_SPEAKING_BRIGHTNESS_MULT",
    "GEOMETRIC_CHARS",
    "GOVERNANCE_HOLD_MS",
    "GRID_COLS",
    "GRID_ROWS",
    "GemCairoSource",
    "GemComposition",
    "GemFrame",
    "GemLayer",
    "GemSubState",
    "GlyphCanvas",
    "GlyphCell",
    "LEGACY_FRAMES_PATH",
    "MAX_DENSITY",
    "MAX_KEYFRAMES",
    "MIN_FRAME_HOLD_MS",
    "build_graffiti_layers",
    "contains_emoji",
    "layer_payloads",
]
