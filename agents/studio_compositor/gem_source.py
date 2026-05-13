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
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
DEFAULT_FONT_DESCRIPTION = "Px437 IBM VGA 8x16 32"
FALLBACK_FRAME_TEXT = "» hapax «"
MIN_FRAME_HOLD_MS = 400
GOVERNANCE_HOLD_MS = 6000
MAX_LAYER_OFFSET_PX = 128
# The room layer remains disabled until the artifact-leak path is reworked.
ROOM_LAYER_RENDER_ENABLED = False

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
        self._legacy_frames_path = None if frames_path is not None else LEGACY_FRAMES_PATH
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

    # ── CairoSource protocol ───────────────────────────────────────────

    def state(self) -> dict[str, Any]:
        """Refresh frame list when the producer's file changes."""
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
        if not isinstance(text, str):
            text = FALLBACK_FRAME_TEXT
        if contains_emoji(text):
            log.warning("gem: refusing emoji-containing frame %r — falling back", text)
            text = FALLBACK_FRAME_TEXT
        layers = _state_layers(state, text)
        envelope_alpha = _state_envelope_alpha(state)
        self._render_graffiti_layers(cr, canvas_w, canvas_h, layers, envelope_alpha)

    # ── Frame advancement ─────────────────────────────────────────────

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
    "FALLBACK_FRAME_TEXT",
    "DEFAULT_FRAMES_PATH",
    "GOVERNANCE_HOLD_MS",
    "GemCairoSource",
    "GemFrame",
    "GemLayer",
    "LEGACY_FRAMES_PATH",
    "MIN_FRAME_HOLD_MS",
    "build_graffiti_layers",
    "contains_emoji",
    "layer_payloads",
]
