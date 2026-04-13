"""Stream status overlay — bottom-right text strip.

Compact three-line status block composited in the bottom-right corner
of the stream frame. Shows current preset (from ``fx-current.txt``),
active viewer count (from ``token-ledger.json``), and chat activity
(from ``chat-state.json``). Degrades gracefully when any of those
files are missing or unreadable.

A4 (Stream A handoff 2026-04-12). Ninth CairoSource in the unified
pipeline alongside Sierpinski, AlbumOverlay, OverlayZones, and
TokenPole. Pattern intentionally mirrors :mod:`token_pole` — a
:class:`CairoSource` subclass owning the draw logic and a facade
class owning the :class:`CairoSourceRunner`.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .cairo_source import CairoSource, CairoSourceRunner

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

SHM_DIR = Path("/dev/shm/hapax-compositor")
FX_CURRENT_FILE = SHM_DIR / "fx-current.txt"
TOKEN_LEDGER_FILE = SHM_DIR / "token-ledger.json"
CHAT_STATE_FILE = SHM_DIR / "chat-state.json"

RENDER_FPS = 2.0  # file-polling cadence, nothing animated

# Canvas geometry — right-edge anchored, vertically stacked.
MARGIN_RIGHT = 24.0
MARGIN_BOTTOM = 24.0
LINE_SPACING = 6.0  # extra px between rows

FONT_PRESET = "JetBrains Mono Bold 16"
FONT_METRICS = "JetBrains Mono Bold 14"


def _read_text(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _format_preset(raw: str) -> str:
    if not raw:
        return "FX: —"
    return f"FX: {raw[:20]}"


def _format_viewers(ledger: dict[str, Any]) -> str:
    count = ledger.get("active_viewers")
    if not isinstance(count, int) or count < 0:
        return "● — viewers"
    if count == 1:
        return "● 1 viewer"
    return f"● {count} viewers"


def _format_chat(state: dict[str, Any]) -> str:
    total = state.get("total_messages", 0)
    authors = state.get("unique_authors", 0)
    if not isinstance(total, int) or not isinstance(authors, int):
        return "░ chat idle"
    if total == 0:
        return "░ chat idle"
    if authors <= 1:
        return f"░ chat quiet ({total})"
    return f"░ {authors} talking ({total})"


class StreamOverlayCairoSource(CairoSource):
    """CairoSource implementation for the stream status strip.

    Polls the three SHM files every tick. Polling under lock is cheap
    at 2 fps and avoids caching-invalidation bugs when the operator
    rewrites preset or the token ledger updates.
    """

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        from .text_render import OUTLINE_OFFSETS_4, TextStyle, measure_text, render_text

        rows = [
            (_format_preset(_read_text(FX_CURRENT_FILE)), FONT_PRESET),
            (_format_viewers(_read_json(TOKEN_LEDGER_FILE)), FONT_METRICS),
            (_format_chat(_read_json(CHAT_STATE_FILE)), FONT_METRICS),
        ]

        # Measure pass — we need line heights and widths to right-align.
        measured: list[tuple[TextStyle, int, int]] = []
        for text, font in rows:
            style = TextStyle(
                text=text,
                font_description=font,
                color_rgba=(0.98, 0.98, 0.96, 1.0),
                outline_color_rgba=(0.0, 0.0, 0.0, 0.85),
                outline_offsets=OUTLINE_OFFSETS_4,
                markup_mode=False,
            )
            w, h = measure_text(cr, style)
            measured.append((style, w, h))

        total_h = sum(h for _, _, h in measured) + LINE_SPACING * (len(measured) - 1)
        base_y = canvas_h - MARGIN_BOTTOM - total_h

        cur_y = base_y
        for style, w, h in measured:
            x = canvas_w - MARGIN_RIGHT - w
            render_text(cr, style, x=x, y=cur_y)
            cur_y += h + LINE_SPACING


class StreamOverlay:
    """Compositor-side facade around the CairoSourceRunner.

    Matches the :class:`TokenPole` / :class:`AlbumOverlay` public API
    (``tick`` / ``draw`` / ``stop``) so ``fx_chain._pip_draw`` and the
    tick callback can treat all overlays uniformly.
    """

    def __init__(self) -> None:
        self._source = StreamOverlayCairoSource()
        self._runner = CairoSourceRunner(
            source_id="stream-overlay",
            source=self._source,
            canvas_w=1920,
            canvas_h=1080,
            target_fps=RENDER_FPS,
        )
        self._runner.start()
        log.info("StreamOverlay background thread started at %.1ffps", RENDER_FPS)

    def tick(self) -> None:
        """No-op; the runner owns the tick cadence."""

    def stop(self) -> None:
        """Stop the background render thread. Idempotent."""
        self._runner.stop()

    def draw(self, cr: cairo.Context) -> None:
        """Blit the pre-rendered output surface into the streaming thread's context."""
        surface = self._runner.get_output_surface()
        if surface is None:
            return
        cr.set_source_surface(surface, 0, 0)
        cr.paint()
