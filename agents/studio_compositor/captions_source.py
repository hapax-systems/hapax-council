"""LRR Phase 9 §3.6 — scientific-register caption overlay (DEPRECATED).

DEPRECATION NOTICE (2026-04-21):
This source is being retired in favor of the GEM ward (15th HOMAGE
ward, operator-ratified 2026-04-21). Both occupy the lower-band
geometry ``(40, 820, 1840, 240)``; GEM authors mural keyframes
through Hapax instead of passively rendering STT.

See ``docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md``
§5 (captions retirement). Importers continue to function — the
class still constructs and renders — but operator-facing surfaces
should migrate to GEM. A warning fires once per process at import
time so downstream consumers notice the deprecation.

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
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

# Module-level deprecation marker: GEM ward (15th HOMAGE) is the
# successor to captions in the same lower-band geometry. Fire ONCE per
# process so downstream consumers (compositor.py, tests, scripts)
# notice without flooding the log on repeated imports.
warnings.warn(
    "captions_source is deprecated; the GEM ward "
    "(agents/studio_compositor/gem_source.py) is the successor in the "
    "same lower-band geometry. See "
    "docs/superpowers/plans/2026-04-21-gem-ward-activation-plan.md §5.",
    DeprecationWarning,
    stacklevel=2,
)

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
#
# Phase A4 (homage-completion-plan §2): typography swapped to Px437 IBM
# VGA 8x16 so captions render in the BitchX CP437 raster grammar via
# Pango + fontconfig. Sizes bumped (public 32 → 36, scientific 18 → 22)
# to compensate for the bitmap-esque raster cell vs. the previous
# anti-aliased proportional display face.
STYLE_PUBLIC: CaptionStyle = CaptionStyle(
    font_description="Px437 IBM VGA 8x16 36",
    color_rgba=(1.0, 0.97, 0.88, 1.0),
    font_size_px=36,
    max_width_px=1600,
    y_offset_px=140,
)
STYLE_SCIENTIFIC: CaptionStyle = CaptionStyle(
    font_description="Px437 IBM VGA 8x16 22",
    color_rgba=(0.80, 0.88, 0.95, 0.95),
    font_size_px=22,
    max_width_px=1400,
    y_offset_px=80,
)


# Phase A4 (homage-completion-plan §2): loud WARN at module import time
# if Px437 doesn't resolve via Pango — operator learns at boot rather
# than noticing a wrong-looking livestream.
def _check_px437_availability() -> None:
    try:
        from .text_render import has_font

        if not has_font("Px437 IBM VGA 8x16"):
            log.warning(
                "captions-font-probe: 'Px437 IBM VGA 8x16' NOT FOUND via Pango/"
                "fontconfig — captions will fall back to DejaVu Sans Mono. "
                "Install the TTF (e.g. /usr/share/fonts/TTF/Px437_IBM_VGA_8x16.ttf) "
                "and restart the compositor."
            )
    except Exception:
        log.debug("captions Px437 probe skipped (text_render import failed)", exc_info=True)


_check_px437_availability()


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


class CaptionsCairoSource(HomageTransitionalSource):
    """HomageTransitionalSource rendering the latest STT line with stream-mode styling."""

    def __init__(
        self,
        *,
        caption_path: Path | None = None,
        stream_mode_reader: Any = None,
    ) -> None:
        super().__init__(source_id="captions")
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

    def render_content(
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
