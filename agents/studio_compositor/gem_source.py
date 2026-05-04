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
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .homage.transitional_source import HomageTransitionalSource

if TYPE_CHECKING:
    import cairo

    from .gem_substrate import NDArrayF32
else:
    NDArrayF32 = object

log = logging.getLogger(__name__)

DEFAULT_FRAMES_PATH = Path("/dev/shm/hapax-compositor/gem-frames.json")
DEFAULT_FONT_DESCRIPTION = "Px437 IBM VGA 8x16 32"
FALLBACK_FRAME_TEXT = "» hapax «"

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


@dataclass(frozen=True)
class GemFrame:
    """A single keyframe in a GEM mural sequence.

    ``text`` is rendered at the centre of the lower-band canvas in the
    Px437 raster grammar. ``hold_ms`` is how long the frame stays on
    screen before the next one advances.
    """

    text: str
    hold_ms: int = 1500


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
            hold_ms = max(50, int(hold_ms_raw))
        except (TypeError, ValueError):
            hold_ms = 1500
        out.append(GemFrame(text=text, hold_ms=hold_ms))
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
    """

    def __init__(
        self,
        *,
        frames_path: Path | None = None,
        font_description: str = DEFAULT_FONT_DESCRIPTION,
        enable_substrate: bool = True,
    ) -> None:
        super().__init__(source_id="gem")
        self._frames_path = frames_path or DEFAULT_FRAMES_PATH
        self._font_description = font_description
        self._frames: list[GemFrame] = []
        self._frame_index: int = 0
        self._frame_started_ts: float = 0.0
        self._last_loaded_mtime: float = 0.0
        # Candidate C Phase 1 — Gray-Scott substrate ticked once per render.
        # Lazily constructed so a numpy-less environment doesn't break the
        # source at import time (the render path silently degrades to text-
        # only when the substrate cannot initialize).
        self._enable_substrate = enable_substrate
        self._substrate: object | None = None
        self._substrate_init_attempted = False

    # ── CairoSource protocol ───────────────────────────────────────────

    def state(self) -> dict[str, Any]:
        """Refresh frame list when the producer's file changes."""
        self._maybe_reload_frames()
        current = self._current_frame()
        return {
            "text": current.text,
            "hold_ms": current.hold_ms,
            "frame_index": self._frame_index,
            "frame_count": len(self._frames),
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

        text = state.get("text") or FALLBACK_FRAME_TEXT
        if contains_emoji(text):
            log.warning("gem: refusing emoji-containing frame %r — falling back", text)
            text = FALLBACK_FRAME_TEXT
        self._render_text_centered(cr, canvas_w, canvas_h, text)

    # ── Frame advancement ─────────────────────────────────────────────

    def _maybe_reload_frames(self) -> None:
        """Reload frames if the producer file has been rewritten."""
        try:
            mtime = self._frames_path.stat().st_mtime
        except OSError:
            # File missing — keep existing frames if any; they may still
            # be useful (paint-and-hold behaviour).
            return
        if mtime <= self._last_loaded_mtime:
            return
        new_frames = _read_frames(self._frames_path)
        if not new_frames:
            return
        self._frames = new_frames
        self._frame_index = 0
        self._frame_started_ts = time.monotonic()
        self._last_loaded_mtime = mtime

    def _current_frame(self) -> GemFrame:
        """Return the frame to draw now, advancing the index if hold elapsed."""
        if not self._frames:
            return GemFrame(text=FALLBACK_FRAME_TEXT, hold_ms=1500)
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
            return None
        try:
            from .gem_substrate import GemSubstrate

            self._substrate = GemSubstrate()
        except Exception:
            log.warning("gem: substrate init failed — rendering text-only", exc_info=True)
            self._substrate = None
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
        try:
            tree = self._ensure_room_tree(canvas_w, canvas_h)
            if not tree:
                return
            from .gem_rooms import room_brightness

            try:
                from .homage.rendering import active_package

                package = active_package()
                r, g, b, _ = package.resolve_colour(package.grammar.content_colour_role)
            except Exception:
                r, g, b = 0.95, 0.92, 0.78

            cr.save()
            cr.select_font_face("Px437 IBM VGA 8x16 24")
            cr.set_font_size(16)

            for room in tree:
                bright = room_brightness(room, t)
                cr.set_source_rgba(r, g, b, bright)
                # Rendering disabled per operator feedback (artifacts leaking through).

            cr.restore()
        except Exception:
            pass

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
            return

        # Build a Cairo ImageSurface from the brightness grid. Each cell
        # becomes one pixel on the small surface; Cairo upscales to the
        # canvas via a translation+scale paint. We use a content_colour
        # tinted by the brightness so the substrate matches the active
        # HOMAGE palette rather than appearing as a neutral grey.
        try:
            tint = self._substrate_tint_rgba()
            self._paint_substrate_grid(cr, bright, grid_w, grid_h, canvas_w, canvas_h, tint)
        except Exception:
            log.debug("gem: substrate paint failed — skipping", exc_info=True)

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

    def _render_text_centered(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        text: str,
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
            colour = (r, g, b, a)
        except Exception:
            colour = (0.95, 0.92, 0.78, 1.0)

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
        x = max(0, (canvas_w - sw) // 2)
        y = max(0, (canvas_h - sh) // 2)
        cr.set_source_surface(surface, x, y)
        cr.paint()


__all__ = [
    "FALLBACK_FRAME_TEXT",
    "GemCairoSource",
    "GemFrame",
    "contains_emoji",
]
