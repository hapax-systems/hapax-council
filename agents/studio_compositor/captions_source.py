"""LRR Phase 9 §3.6 — scientific-register caption overlay.

CairoSource that renders the most recent STT transcript lines onto the
compositor frame, with styling that depends on the current stream mode:

* ``public_research``: scientific register — JetBrains Mono, smaller
  type, subdued colour. Matches the research surface's visual quiet.
* ``public``: bold display — larger type, warm colour. Matches the
  ambient-stream feel.
* ``private`` / ``fortress``: renders the same way as ``public_research``
  (small monospace) since captions visible at all require explicit
  stream display — the Cairo renderer is tolerant, and downstream
  redaction gates (Phase 6 §4) decide whether to actually draw.

STT consumers are expected to write the most recent transcript line to
``/dev/shm/hapax-daimonion/stt-recent.txt``; this source reads that
path and renders it. If the file is missing or empty, render is a
no-op. Read happens at tick time and is cheap — no cache invalidation
required beyond ``_last_mtime``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .cairo_source import CairoSource

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

DEFAULT_CAPTION_PATH = Path("/dev/shm/hapax-daimonion/stt-recent.txt")
DEFAULT_STREAM_MODE = "private"


@dataclass(frozen=True)
class CaptionStyle:
    font_description: str
    color_rgba: tuple[float, float, float, float]
    font_size_px: int
    max_width_px: int
    y_offset_px: int  # from the bottom of the canvas

    # Sensible padding so the background band has breathing room.
    band_padding_px: int = 12


# LRR Phase 9 §3.6 — per-stream-mode styles. Operator can tune in place.
STYLE_PUBLIC: CaptionStyle = CaptionStyle(
    font_description="Noto Sans Display Bold 32",
    color_rgba=(1.0, 0.97, 0.88, 1.0),
    font_size_px=32,
    max_width_px=1600,
    y_offset_px=140,
)
STYLE_SCIENTIFIC: CaptionStyle = CaptionStyle(
    font_description="JetBrains Mono 18",
    color_rgba=(0.80, 0.88, 0.95, 0.95),
    font_size_px=18,
    max_width_px=1400,
    y_offset_px=80,
)


def style_for_stream_mode(mode: str | None) -> CaptionStyle:
    """Return the caption style to use for ``mode``."""
    if mode == "public":
        return STYLE_PUBLIC
    # Every other mode — public_research, private, fortress, None — takes
    # the quieter scientific register. Keeps the surface predictable.
    return STYLE_SCIENTIFIC


def _read_latest_caption(path: Path) -> str:
    """Return the trimmed last non-empty line, or '' on missing / error."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


class CaptionsCairoSource(CairoSource):
    """CairoSource rendering the latest STT line with stream-mode styling."""

    def __init__(
        self,
        *,
        caption_path: Path | None = None,
        stream_mode_reader: Any = None,
    ) -> None:
        self._path = caption_path or DEFAULT_CAPTION_PATH
        self._stream_mode_reader = stream_mode_reader
        self._current_text: str = ""
        self._current_style: CaptionStyle = STYLE_SCIENTIFIC

    # ── CairoSource protocol ───────────────────────────────────────────────

    def state(self) -> dict[str, Any]:
        """Refresh current text + style on every tick."""
        self._current_text = _read_latest_caption(self._path)
        mode = self._resolve_stream_mode()
        self._current_style = style_for_stream_mode(mode)
        return {"text": self._current_text, "mode": mode}

    def render(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        del t  # unused; caller may still pass it
        text = state.get("text") or self._current_text
        if not text:
            return
        style = self._current_style
        self._render_caption(cr, canvas_w, canvas_h, text, style)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _resolve_stream_mode(self) -> str:
        reader = self._stream_mode_reader
        if reader is None:
            # Default production reader: use the LRR Phase 6 canonical
            # stream-mode file. Fail-closed to PUBLIC if the file is
            # unreadable, matching the rest of the stream-mode consumers.
            try:
                from shared.stream_mode import get_stream_mode

                return str(get_stream_mode())
            except Exception:
                log.debug(
                    "default stream-mode reader failed — using module default",
                    exc_info=True,
                )
                return DEFAULT_STREAM_MODE
        try:
            mode = reader()
        except Exception:
            log.debug("stream-mode reader raised — falling back to default", exc_info=True)
            return DEFAULT_STREAM_MODE
        return mode if isinstance(mode, str) else DEFAULT_STREAM_MODE

    def _render_caption(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        text: str,
        style: CaptionStyle,
    ) -> None:
        """Render ``text`` using ``style``. Split out for fakes in tests."""
        try:
            from .text_render import OUTLINE_OFFSETS_8, TextStyle, render_text_to_surface
        except ImportError:  # pragma: no cover — test envs without text_render
            return

        text_style = TextStyle(
            text=text,
            font_description=style.font_description,
            color_rgba=style.color_rgba,
            outline_color_rgba=(0.0, 0.0, 0.0, 0.9),
            outline_offsets=OUTLINE_OFFSETS_8,
            max_width_px=style.max_width_px,
            wrap="word_char",
            markup_mode=False,
        )
        surface, sw, sh = render_text_to_surface(text_style, padding_px=style.band_padding_px)
        # Center horizontally, position style.y_offset_px from the bottom.
        x = max(0, (canvas_w - sw) // 2)
        y = canvas_h - sh - style.y_offset_px
        cr.set_source_surface(surface, x, y)
        cr.paint()


__all__ = [
    "CaptionStyle",
    "CaptionsCairoSource",
    "STYLE_PUBLIC",
    "STYLE_SCIENTIFIC",
    "style_for_stream_mode",
]
