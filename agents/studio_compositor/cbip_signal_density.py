"""CBIP signal-density what's-playing ward (Phase 1 scaffold).

Phase 5 of the content-source-registry plan
(``docs/superpowers/plans/2026-04-23-content-source-registry-plan.md``):
a multi-layer "what's playing" ward driven by metadata, waveform,
stem activity, BPM-locked motion, and attribution — replacing the
retired SHM cover-art chain that ``album_overlay.py`` consumes.

This Phase 1 slice lands the **layered renderer scaffold** plus two
of the five layers per the plan §5:

* **Layer 1 — platter/media texture base.** Palette-quantized tile
  background of the current platter media image. Reads from the same
  ``/dev/shm/hapax-compositor/album-cover.png`` chain
  ``album_overlay.py`` reads today (the chain is retired in a
  follow-up — see :ref:`out-of-scope` below). Quantization to the
  active HOMAGE package's 16 palette roles via PIL ordered-dither,
  same approach as ``album_overlay._build_mirc16_palette_image``.
* **Layer 5 — tag/mood text overlay.** Px437 BitchX-grammar
  ``[CBIP] artist — title`` line read from
  ``/dev/shm/hapax-compositor/album-state.json``. Text-only;
  honors the post-#1236 no-flashing contract by holding alpha
  constant.

Layers 2-4 (waveform, stem-activity, BPM-locked motion) are stubbed
as ``_paint_*_layer`` methods that no-op when the upstream data is
unavailable. Each carries a TODO documenting the producer it needs.

.. _out-of-scope:

Out of scope for this slice
---------------------------

- Waveform producer (Layer 2 source) — not currently wired; the layer
  no-ops until a producer ships. The plan §5 calls for "render
  locally-computed waveform data" — an analysis pass against the
  active track's audio buffer that no producer currently writes.
- Stem-activity mixer level meter (Layer 3 source) — same shape:
  needs a per-stem-channel meter publishing to ``/dev/shm/hapax-mixer/``.
- BPM source for Layer 4 — needs either a metadata-side BPM field
  (some local-music-repo entries carry it; many do not) or a runtime
  estimate. The layer renders an idle grid pattern when BPM is
  absent.
- Crossfade between tracks (plan §5, "smooth crossfade between tracks
  200-600 ms") — held until the layers themselves are stable.
- Retiring the SHM ``album-cover.png`` producer chain — operator-
  visible side effects (some consumers still poll the file) so the
  retirement lands as a separate cc-task once every consumer is
  migrated to the metadata-driven path.

Co-existence with ``album_overlay.py``
--------------------------------------

This module ships ALONGSIDE ``album_overlay.py`` rather than replacing
it in-place. Layout JSONs choose one or the other via
``cairo_sources`` registration. The retirement of the legacy ward is a
separate slice once the new ward's audio-reactive layers are wired
and the operator confirms the visual contract.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Final

import cairo

from .homage.rendering import active_package
from .homage.transitional_source import HomageTransitionalSource

log = logging.getLogger(__name__)

#: Same SHM media-image path the legacy ward reads. Retirement of this
#: producer chain is deferred (separate slice).
PLATTER_IMAGE_PATH: Final[Path] = Path("/dev/shm/hapax-compositor/album-cover.png")
COVER_PATH: Final[Path] = PLATTER_IMAGE_PATH

#: Metadata sidecar for the current platter/media image.
PLATTER_STATE_PATH: Final[Path] = Path("/dev/shm/hapax-compositor/album-state.json")
ALBUM_STATE_PATH: Final[Path] = PLATTER_STATE_PATH

#: Texture-base layer alpha — kept low so the texture reads as
#: ambient background rather than ward chrome.
COVER_BASE_ALPHA: Final[float] = 0.35

#: Tag/mood overlay font size in pixels (Pango units handled inside
#: ``text_render``). Px437 8x16 is the operator's pixel font of choice
#: per the spec; 14 px renders crisply at 1280×720.
TAG_TEXT_SIZE_PX: Final[int] = 14

#: Bottom margin for the tag/mood line so it doesn't touch the bottom
#: edge of the ward canvas.
TAG_BOTTOM_MARGIN: Final[int] = 8


class CBIPSignalDensityCairoSource(HomageTransitionalSource):
    """Multi-layer "what's playing" ward — Phase 1 scaffold.

    Composition order (per plan §5):

    1. Cover-art texture base (palette-quantized, low-opacity tile)
    2. Waveform layer (stub — no producer yet)
    3. Stem-activity layer (stub — no mixer meter yet)
    4. BPM-locked motion grid (stub — needs BPM source)
    5. Tag/mood text overlay (Px437)

    Each ``_paint_*_layer`` method is independent so future slices can
    fill in 2-4 without touching the others. Phase 1 implements 1 and
    5 only.

    Construct once per compositor process; the ``CairoSourceRunner``
    handles cadence, output-surface caching, and visibility gates.
    """

    def __init__(self) -> None:
        super().__init__(source_id="cbip_signal_density")
        self._cached_cover: cairo.ImageSurface | None = None
        self._cached_cover_mtime: float = 0.0
        self._cached_state: dict[str, Any] = {}
        self._cached_state_mtime: float = 0.0

    # ── Layer 1: cover-art texture base ───────────────────────────

    def _refresh_cover(self) -> cairo.ImageSurface | None:
        """Reload + palette-quantize the cover surface on mtime change.

        Phase 2 of cc-task ``content-source-cbip-signal-density``
        wires :func:`agents.studio_compositor.palette_quantize.quantize_cairo_to_package_palette`
        into the cache so the layer paints the palette-quantized
        cover, not the raw decode. Quantization is mtime-cached so
        the per-tick render path stays cheap (the inner Pillow
        round-trip is only paid when the cover file changes).

        Falls back to the raw decode if quantization fails (PIL
        missing, palette resolution failed, etc.) so a transient
        error doesn't take the whole layer offline.
        """
        try:
            mtime = COVER_PATH.stat().st_mtime
        except OSError:
            self._cached_cover = None
            self._cached_cover_mtime = 0.0
            return None
        if self._cached_cover is not None and mtime == self._cached_cover_mtime:
            return self._cached_cover
        try:
            raw_surface = cairo.ImageSurface.create_from_png(str(COVER_PATH))
        except Exception:
            log.debug("cbip cover-art decode failed", exc_info=True)
            self._cached_cover = None
            self._cached_cover_mtime = 0.0
            return None

        # Phase 2: quantize to the active HOMAGE package's mIRC palette
        # so the cover-art base layer reads in the same colour family as
        # the rest of the ward chrome. Falls back to the raw decode if
        # quantization fails (PIL missing, package unavailable, etc.).
        from agents.studio_compositor.palette_quantize import (
            quantize_cairo_to_package_palette,
        )

        quantized: cairo.ImageSurface | None = None
        try:
            pkg = active_package()
        except Exception:
            log.debug("cbip active_package read failed; using raw cover", exc_info=True)
            pkg = None
        if pkg is not None:
            quantized = quantize_cairo_to_package_palette(raw_surface, pkg)

        self._cached_cover = quantized if quantized is not None else raw_surface
        self._cached_cover_mtime = mtime
        return self._cached_cover

    def _paint_cover_art_base(self, cr: cairo.Context, canvas_w: int, canvas_h: int) -> bool:
        """Paint the palette-quantized cover as a low-opacity texture base.

        Returns True if anything was drawn, False when the cover-art
        file is missing or undecodable. Quantization happens inside
        :meth:`_refresh_cover` (mtime-cached) so this method just
        scales-to-fit the cached surface and paints at
        :data:`COVER_BASE_ALPHA`.
        """
        surface = self._refresh_cover()
        if surface is None:
            return False
        sw = surface.get_width()
        sh = surface.get_height()
        if sw <= 0 or sh <= 0:
            return False

        scale_x = canvas_w / sw
        scale_y = canvas_h / sh
        scale = max(scale_x, scale_y)
        offset_x = (canvas_w - sw * scale) / 2
        offset_y = (canvas_h - sh * scale) / 2

        cr.save()
        cr.translate(offset_x, offset_y)
        cr.scale(scale, scale)
        cr.set_source_surface(surface, 0, 0)
        cr.paint_with_alpha(COVER_BASE_ALPHA)
        cr.restore()
        return True

    # ── Layer 2: waveform (stub) ──────────────────────────────────

    def _paint_waveform_layer(self, cr: cairo.Context, canvas_w: int, canvas_h: int) -> bool:
        """No-op until a waveform producer ships. Plan §5: "render
        locally-computed waveform data; live position marker"."""
        del cr, canvas_w, canvas_h
        # TODO: wire `/dev/shm/hapax-mixer/waveform.f32` once a
        # producer exists. Returns False so callers know the layer
        # didn't draw.
        return False

    # ── Layer 3: stem activity (stub) ─────────────────────────────

    def _paint_stem_activity_layer(self, cr: cairo.Context, canvas_w: int, canvas_h: int) -> bool:
        """No-op until a per-stem mixer meter ships. Plan §5: "four
        lanes (drums/bass/melody/instruments), each pulsing at the
        stem's amplitude envelope". Pulse must be amplitude-driven —
        no alpha-beat modulation per #1236."""
        del cr, canvas_w, canvas_h
        # TODO: wire `/dev/shm/hapax-mixer/stem-levels.json` once a
        # producer exists.
        return False

    # ── Layer 4: BPM-locked motion grid (stub) ────────────────────

    def _paint_bpm_motion_grid(
        self, cr: cairo.Context, canvas_w: int, canvas_h: int, t: float
    ) -> bool:
        """No-op until a BPM source ships. Plan §5: "particles or grid
        lines pulse at the track's BPM, locked to the mixer transport".
        Motion is positional only — no alpha-beat modulation."""
        del cr, canvas_w, canvas_h, t
        # TODO: read BPM from album-state.json metadata when the
        # local-music-repo entry carries it; otherwise stay idle.
        return False

    # ── Layer 5: tag/mood text overlay ────────────────────────────

    def _refresh_state(self) -> dict[str, Any]:
        """Reload album-state.json on mtime change."""
        try:
            mtime = ALBUM_STATE_PATH.stat().st_mtime
        except OSError:
            self._cached_state = {}
            self._cached_state_mtime = 0.0
            return self._cached_state
        if self._cached_state and mtime == self._cached_state_mtime:
            return self._cached_state
        try:
            data = json.loads(ALBUM_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            log.debug("cbip album-state decode failed", exc_info=True)
            data = {}
        if isinstance(data, dict):
            self._cached_state = data
            self._cached_state_mtime = mtime
        else:
            self._cached_state = {}
        return self._cached_state

    def _format_tag_line(self, state: dict[str, Any]) -> str:
        """Build the BitchX-grammar tag line from album-state.json.

        Format: ``[CBIP] {artist} — {title}`` when both are present;
        ``[CBIP] (no track)`` when state is empty so the ward has a
        baseline visual contract instead of going invisible.
        """
        artist = str(state.get("artist") or "").strip()
        title = str(state.get("title") or "").strip()
        if artist and title:
            return f"[CBIP] {artist} — {title}"
        if title:
            return f"[CBIP] {title}"
        if artist:
            return f"[CBIP] {artist}"
        return "[CBIP] (no track)"

    def _paint_tag_mood_overlay(self, cr: cairo.Context, canvas_w: int, canvas_h: int) -> bool:
        """Render the tag line in Px437 at the canvas's bottom edge.

        Constant alpha (no flashing) per the post-#1236 contract.
        Returns True if the layer drew, False if rendering failed.
        """
        state = self._refresh_state()
        text = self._format_tag_line(state)

        try:
            from agents.studio_compositor.homage.fonts import (
                select_bitchx_font_pango,
            )
            from agents.studio_compositor.text_render import (
                TextStyle,
                render_text,
            )
        except Exception:
            log.debug("cbip text-render imports failed", exc_info=True)
            return False

        try:
            pkg = active_package()
        except Exception:
            log.debug("cbip active_package read failed", exc_info=True)
            return False

        try:
            colour = pkg.resolve_colour(pkg.grammar.identity_colour_role)
        except Exception:
            colour = (0.9, 0.9, 0.9, 1.0)

        try:
            font = select_bitchx_font_pango(pkg, size_px=TAG_TEXT_SIZE_PX)
        except Exception:
            log.debug("cbip Px437 font selection failed", exc_info=True)
            return False

        style = TextStyle(text=text, font=font, colour_rgba=colour)

        try:
            render_text(
                cr,
                style,
                x=8.0,
                y=float(canvas_h - TAG_BOTTOM_MARGIN - TAG_TEXT_SIZE_PX),
            )
        except Exception:
            log.debug("cbip tag/mood render failed", exc_info=True)
            return False
        return True

    # ── Composition entrypoint ────────────────────────────────────

    def render_content(
        self,
        cr: cairo.Context,
        canvas_w: int,
        canvas_h: int,
        t: float,
        state: dict[str, Any],
    ) -> None:
        """Draw all five layers in order.

        Layers 2-4 are stubbed and return False — they don't draw and
        don't error. The composition order is fixed: cover-art → waves
        → stems → grid → tags so the audio-reactive layers (when they
        ship) sit above the texture base and below the tag line.
        """
        del state  # Phase 1 doesn't consume the runner state dict.
        self._paint_cover_art_base(cr, canvas_w, canvas_h)
        self._paint_waveform_layer(cr, canvas_w, canvas_h)
        self._paint_stem_activity_layer(cr, canvas_w, canvas_h)
        self._paint_bpm_motion_grid(cr, canvas_w, canvas_h, t)
        self._paint_tag_mood_overlay(cr, canvas_w, canvas_h)
