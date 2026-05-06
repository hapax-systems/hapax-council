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

from .homage.transitional_source import HomageTransitionalSource

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

# Phase A4: Px437 IBM VGA 8x16 via Pango + fontconfig; rendered
# emissively via ``paint_emissive_glyph`` style so the strip reads as
# point-of-light text rather than flat anti-aliased labels. Sizes chosen
# so the CP437 raster cell stays legible on the 1920x1080 frame.
FONT_PRESET = "Px437 IBM VGA 8x16 16"
FONT_METRICS = "Px437 IBM VGA 8x16 16"


def _read_text(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def _read_json(path: Path) -> dict[str, Any]:
    """Return a JSON file as a dict, or {} on any failure.

    Validates the JSON root is a mapping. The ``_format_viewers`` and
    ``_format_chat`` callers downstream call ``ledger.get(...)`` /
    ``state.get(...)`` directly on the returned value; a writer
    producing valid JSON whose root is null, a list, a string, or a
    number previously raised AttributeError out of the stream-overlay
    cairooverlay callback. Same corruption-class as #2627, #2631,
    #2632, #2636 (merged) and #2640, #2642, #2644, #2646 (in flight).
    """
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _format_preset(raw: str) -> str:
    """Phase A4 — ``>>> [FX|<chain>]`` grammar."""
    value = raw[:20] if raw else "—"
    return f">>> [FX|{value}]"


def _format_viewers(ledger: dict[str, Any]) -> str:
    """Phase A4 — ``>>> [VIEWERS|<count>]`` grammar."""
    count = ledger.get("active_viewers")
    if not isinstance(count, int) or count < 0:
        return ">>> [VIEWERS|—]"
    return f">>> [VIEWERS|{count}]"


def _format_chat(state: dict[str, Any]) -> str:
    """Phase A4 — ``>>> [CHAT|<status>]`` grammar."""
    total = state.get("total_messages", 0)
    authors = state.get("unique_authors", 0)
    if not isinstance(total, int) or not isinstance(authors, int):
        return ">>> [CHAT|idle]"
    if total == 0:
        return ">>> [CHAT|idle]"
    if authors <= 1:
        return f">>> [CHAT|quiet {total}]"
    return f">>> [CHAT|{authors}t/{total}m]"


class StreamOverlayCairoSource(HomageTransitionalSource):
    """HomageTransitionalSource rendering the stream status strip.

    Polls the three SHM files every tick. Polling under lock is cheap
    at 2 fps and avoids caching-invalidation bugs when the operator
    rewrites preset or the token ledger updates.
    """

    def __init__(self) -> None:
        super().__init__(source_id="stream_overlay")

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        from .homage.emissive_base import paint_breathing_alpha
        from .homage.rendering import active_package
        from .text_render import OUTLINE_OFFSETS_4, TextStyle, measure_text, render_text

        # Phase A4: emissive Px437 grammar. Colours sourced from the
        # active HomagePackage so the strip matches the rest of the
        # HOMAGE wards under palette swaps. Outline suppressed — the
        # emissive halo already carries the legibility contrast.
        try:
            pkg = active_package()
            content_rgba = pkg.resolve_colour(pkg.grammar.content_colour_role)
            identity_rgba = pkg.resolve_colour(pkg.grammar.identity_colour_role)
        except Exception:
            content_rgba = (0.80, 0.80, 0.80, 1.0)
            identity_rgba = (0.98, 0.98, 0.96, 1.0)

        shimmer = paint_breathing_alpha(t, hz=0.4, phase=0.0)

        rows = [
            (_format_preset(_read_text(FX_CURRENT_FILE)), FONT_PRESET, identity_rgba),
            (_format_viewers(_read_json(TOKEN_LEDGER_FILE)), FONT_METRICS, content_rgba),
            (_format_chat(_read_json(CHAT_STATE_FILE)), FONT_METRICS, content_rgba),
        ]

        # Measure pass — we need line heights and widths to right-align.
        measured: list[tuple[TextStyle, int, int]] = []
        for text, font, rgba in rows:
            r, g, b, a = rgba
            style = TextStyle(
                text=text,
                font_description=font,
                color_rgba=(r, g, b, a * shimmer),
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


# The pre-Phase-9 ``StreamOverlay`` facade was removed in Phase 9
# Task 29. Rendering now flows through ``StreamOverlayCairoSource`` +
# the SourceRegistry + ``fx_chain.pip_draw_from_layout``.
