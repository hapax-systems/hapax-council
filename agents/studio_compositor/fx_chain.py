"""Inline GPU effects chain and per-frame tick callback."""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

log = logging.getLogger(__name__)


class YouTubeOverlay:
    """Floating YouTube PiP with its own contained effects layer.

    Composited AFTER the main shader chain via a post-FX cairooverlay.
    Avoids glvideomixer deadlock by decoupling PiP frame capture from
    the main GStreamer pipeline. Frames read via ffmpeg subprocess,
    effects applied in Cairo (vignette, scanlines, tint, grain).

    Architecture:
      ffmpeg subprocess → raw BGRA frames → background thread → cairo surface
      Main pipeline → ... → shader chain → cairooverlay (paints PiP) → output
    """

    WIDTH = 640
    HEIGHT = 360
    FRAME_SIZE = 640 * 360 * 4  # BGRA
    ALPHA = 0.75
    V4L2_DEVICE = "/dev/video50"
    STATUS_URL = "http://127.0.0.1:8055/status"
    ATTRIB_FILE = "/dev/shm/hapax-compositor/yt-attribution.txt"

    def __init__(self) -> None:
        self._active = False
        self._x = 100.0
        self._y = 100.0
        self._vx = 1.2
        self._vy = 0.8
        self._last_check = 0.0
        self._ffmpeg_proc: Any = None
        self._reader_thread: Any = None
        self._surface: Any = None
        self._surface_lock = threading.Lock()
        self._fx_name = ""
        self._fx_func: Any = None
        self._attrib_text = ""
        self._attrib_mtime = 0.0
        self._attrib_layout: Any = None

    def tick(self, compositor: Any, Gst: Any) -> None:
        """Called every frame tick. Checks status, bounces position."""
        now = time.monotonic()

        if now - self._last_check > 2.0:
            self._last_check = now
            playing = self._check_playing()
            if playing and not self._active:
                self._start_capture()
            elif not playing and self._active:
                self._stop_capture()

        if self._active:
            self._x += self._vx
            self._y += self._vy
            if self._x <= 20:
                self._x = 20
                self._vx = abs(self._vx)
            elif self._x + self.WIDTH >= 1920 - 20:
                self._x = 1920 - self.WIDTH - 20
                self._vx = -abs(self._vx)
            if self._y <= 20:
                self._y = 20
                self._vy = abs(self._vy)
            elif self._y + self.HEIGHT >= 1080 - 20:
                self._y = 1080 - self.HEIGHT - 20
                self._vy = -abs(self._vy)

    def _check_playing(self) -> bool:
        try:
            import urllib.request

            r = urllib.request.urlopen(self.STATUS_URL, timeout=0.5)
            import json

            data = json.loads(r.read())
            return data.get("playing", False)
        except Exception:
            return False

    def _start_capture(self) -> None:
        """Start ffmpeg subprocess reading from v4l2loopback, piping BGRA frames."""
        import os
        import subprocess as _sp

        if not os.path.exists(self.V4L2_DEVICE):
            return

        # Pick random PiP effect
        self._fx_name, self._fx_func = random.choice(list(PIP_EFFECTS.items()))
        self._attrib_layout = None

        try:
            self._ffmpeg_proc = _sp.Popen(
                [
                    "ffmpeg",
                    "-f",
                    "v4l2",
                    "-video_size",
                    "1920x1080",
                    "-input_format",
                    "yuyv422",
                    "-i",
                    self.V4L2_DEVICE,
                    "-vf",
                    f"scale={self.WIDTH}:{self.HEIGHT}",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "bgra",
                    "-an",
                    "-v",
                    "error",
                    "pipe:1",
                ],
                stdout=_sp.PIPE,
                stderr=_sp.DEVNULL,
            )
            self._reader_thread = threading.Thread(target=self._read_frames, daemon=True)
            self._reader_thread.start()
            self._active = True
            log.info("YouTube PiP capture started (effect=%s)", self._fx_name)
        except Exception:
            log.exception("YouTube PiP capture failed to start")

    def _stop_capture(self) -> None:
        """Stop ffmpeg subprocess and clear state."""
        if self._ffmpeg_proc is not None:
            try:
                self._ffmpeg_proc.kill()
                self._ffmpeg_proc.wait(timeout=2)
            except Exception:
                pass
            self._ffmpeg_proc = None
        with self._surface_lock:
            self._surface = None
        self._active = False
        self._attrib_layout = None
        log.info("YouTube PiP capture stopped")

    def _read_frames(self) -> None:
        """Background thread: read raw BGRA frames from ffmpeg stdout."""
        import cairo

        proc = self._ffmpeg_proc
        if proc is None or proc.stdout is None:
            return
        while proc.poll() is None:
            try:
                data = proc.stdout.read(self.FRAME_SIZE)
                if len(data) != self.FRAME_SIZE:
                    break
                # Create cairo surface from raw BGRA data
                surface = cairo.ImageSurface.create_for_data(
                    bytearray(data),
                    cairo.FORMAT_ARGB32,
                    self.WIDTH,
                    self.HEIGHT,
                )
                with self._surface_lock:
                    self._surface = surface
            except Exception:
                break

    def draw(self, cr: Any) -> None:
        """Called from post-FX cairooverlay. Paints PiP + effects + attribution."""
        if not self._active:
            return

        with self._surface_lock:
            surface = self._surface
        if surface is None:
            return

        cr.save()
        x, y = int(self._x), int(self._y)
        cr.translate(x, y)

        # Paint the video frame
        cr.set_source_surface(surface, 0, 0)
        cr.paint_with_alpha(self.ALPHA)

        # Apply the randomly selected PiP effect
        if self._fx_func is not None:
            self._fx_func(cr, self.WIDTH, self.HEIGHT)

        # Attribution text
        self._draw_attribution(cr)

        cr.restore()

    def _draw_attribution(self, cr: Any) -> None:
        """Draw attribution text at bottom of PiP."""
        import os
        from pathlib import Path

        path = Path(self.ATTRIB_FILE)
        try:
            if path.exists():
                mtime = os.path.getmtime(path)
                if mtime != self._attrib_mtime:
                    self._attrib_text = path.read_text().strip()
                    self._attrib_mtime = mtime
                    self._attrib_layout = None
            elif self._attrib_text:
                self._attrib_text = ""
                self._attrib_layout = None
        except OSError:
            pass

        if not self._attrib_text:
            return

        import gi

        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo

        if self._attrib_layout is None:
            layout = PangoCairo.create_layout(cr)
            font = Pango.FontDescription.from_string("JetBrains Mono Bold 11")
            layout.set_font_description(font)
            layout.set_width(int((self.WIDTH - 20) * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            lines = self._attrib_text.split("\n")
            title = (lines[0] if lines else "").replace("&", "&amp;").replace("<", "&lt;")
            channel = (
                (lines[1] if len(lines) > 1 else "").replace("&", "&amp;").replace("<", "&lt;")
            )
            markup = f"<b>{title}</b>"
            if channel:
                markup += f"\n{channel}"
            layout.set_markup(markup, -1)
            self._attrib_layout = layout

        _w, _h = self._attrib_layout.get_pixel_size()
        tx, ty = 10, self.HEIGHT - _h - 8

        cr.set_source_rgba(0.0, 0.0, 0.0, 0.85)
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            cr.move_to(tx + dx, ty + dy)
            PangoCairo.show_layout(cr, self._attrib_layout)
        cr.set_source_rgba(1.0, 0.97, 0.90, 1.0)
        cr.move_to(tx, ty)
        PangoCairo.show_layout(cr, self._attrib_layout)


# --- PiP Cairo effects: content-preserving, randomly selected per video ---


def _pip_fx_vintage(cr: Any, w: int, h: int) -> None:
    """Warm vignette + dense scanlines + sepia wash."""
    import cairo

    cx, cy = w / 2, h / 2
    r = max(w, h) * 0.6
    pat = cairo.RadialGradient(cx, cy, r * 0.2, cx, cy, r)
    pat.add_color_stop_rgba(0, 0, 0, 0, 0)
    pat.add_color_stop_rgba(1, 0, 0, 0, 0.75)
    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Heavy warm tint
    cr.set_source_rgba(0.2, 0.1, 0.0, 0.25)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Dense scanlines
    cr.set_source_rgba(0, 0, 0, 0.18)
    for y in range(0, h, 3):
        cr.rectangle(0, y, w, 1)
    cr.fill()
    # Contrast border
    cr.set_source_rgba(0.6, 0.4, 0.1, 0.4)
    cr.set_line_width(2)
    cr.rectangle(1, 1, w - 2, h - 2)
    cr.stroke()


def _pip_fx_cold(cr: Any, w: int, h: int) -> None:
    """Cold blue tint + heavy vignette + thick horizontal lines."""
    import cairo

    cx, cy = w / 2, h / 2
    r = max(w, h) * 0.55
    pat = cairo.RadialGradient(cx, cy, r * 0.15, cx, cy, r)
    pat.add_color_stop_rgba(0, 0, 0, 0, 0)
    pat.add_color_stop_rgba(1, 0, 0, 0.05, 0.8)
    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Strong blue wash
    cr.set_source_rgba(0.0, 0.08, 0.25, 0.3)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Thick alternating lines
    cr.set_source_rgba(0, 0, 0, 0.2)
    for y in range(0, h, 4):
        cr.rectangle(0, y, w, 2)
    cr.fill()
    # Cold border
    cr.set_source_rgba(0.3, 0.5, 0.8, 0.5)
    cr.set_line_width(2)
    cr.rectangle(1, 1, w - 2, h - 2)
    cr.stroke()


def _pip_fx_neon(cr: Any, w: int, h: int) -> None:
    """Neon glow border + vignette + color wash."""
    import cairo

    cx, cy = w / 2, h / 2
    r = max(w, h) * 0.65
    pat = cairo.RadialGradient(cx, cy, r * 0.3, cx, cy, r)
    pat.add_color_stop_rgba(0, 0, 0, 0, 0)
    pat.add_color_stop_rgba(1, 0, 0, 0, 0.6)
    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Neon glow: multi-layer border
    for width, alpha in [(12, 0.08), (6, 0.15), (3, 0.35), (1.5, 0.6)]:
        cr.set_source_rgba(0.1, 0.7, 1.0, alpha)
        cr.set_line_width(width)
        cr.rectangle(2, 2, w - 4, h - 4)
        cr.stroke()
    # Subtle magenta wash
    cr.set_source_rgba(0.15, 0.0, 0.1, 0.12)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Light scanlines
    cr.set_source_rgba(0, 0, 0, 0.1)
    for y in range(0, h, 3):
        cr.rectangle(0, y, w, 1)
    cr.fill()


def _pip_fx_film(cr: Any, w: int, h: int) -> None:
    """Film print: amber wash + heavy vignette + border scratches."""
    import cairo

    cx, cy = w / 2, h / 2
    r = max(w, h) * 0.6
    pat = cairo.RadialGradient(cx, cy, r * 0.25, cx, cy, r)
    pat.add_color_stop_rgba(0, 0, 0, 0, 0)
    pat.add_color_stop_rgba(1, 0, 0, 0, 0.65)
    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Amber film tint
    cr.set_source_rgba(0.15, 0.08, 0.0, 0.2)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Desaturation overlay
    cr.set_source_rgba(0.12, 0.12, 0.12, 0.15)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Film border
    cr.set_source_rgba(0.8, 0.6, 0.2, 0.4)
    cr.set_line_width(3)
    cr.rectangle(1, 1, w - 2, h - 2)
    cr.stroke()


def _pip_fx_phosphor(cr: Any, w: int, h: int) -> None:
    """CRT phosphor: green tint + heavy scanlines + deep vignette + flicker."""
    import cairo

    cx, cy = w / 2, h / 2
    r = max(w, h) * 0.55
    pat = cairo.RadialGradient(cx, cy, r * 0.15, cx, cy, r)
    pat.add_color_stop_rgba(0, 0, 0, 0, 0)
    pat.add_color_stop_rgba(1, 0, 0, 0, 0.75)
    cr.set_source(pat)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Strong green phosphor tint
    cr.set_source_rgba(0.0, 0.18, 0.05, 0.25)
    cr.rectangle(0, 0, w, h)
    cr.fill()
    # Heavy scanlines (every 2px)
    cr.set_source_rgba(0, 0, 0, 0.22)
    for y in range(0, h, 3):
        cr.rectangle(0, y, w, 1)
    cr.fill()
    # Phosphor border glow
    cr.set_source_rgba(0.1, 0.8, 0.2, 0.35)
    cr.set_line_width(2)
    cr.rectangle(1, 1, w - 2, h - 2)
    cr.stroke()


PIP_EFFECTS = {
    "vintage": _pip_fx_vintage,
    "cold_surveillance": _pip_fx_cold,
    "neon": _pip_fx_neon,
    "film_print": _pip_fx_film,
    "phosphor": _pip_fx_phosphor,
}


class AlbumOverlay:
    """Floating album cover + splattribution text overlay.

    Reads the IR album cover image from /dev/shm/hapax-compositor/album-cover.jpg
    and the splattribution text from music-attribution.txt. Bounces independently
    from the YouTube PiP.
    """

    SIZE = 300  # display size (square, album covers are square)
    ALPHA = 0.85
    COVER_PATH = "/dev/shm/hapax-compositor/album-cover.png"
    ATTRIB_PATH = "/dev/shm/hapax-compositor/music-attribution.txt"

    def __init__(self) -> None:
        # Fixed position: lower-left quadrant (opposite token pole at upper-left)
        # Text goes above cover, cover sits near bottom
        self._x = 20.0
        self._y = 1080.0 - 300.0 - 20.0  # SIZE + margin from bottom
        self._surface: Any = None
        self._surface_mtime: float = 0
        self._attrib_text: str = ""
        self._attrib_mtime: float = 0
        self._attrib_layout: Any = None
        self._fx_func: Any = None
        self._fx_name: str = ""

    def tick(self) -> None:
        """Fixed position — no bounce."""
        pass

    def draw(self, cr: Any) -> None:
        """Paint album cover + splattribution on the cairooverlay."""
        import os

        # Reload cover image if changed
        try:
            if os.path.exists(self.COVER_PATH):
                mtime = os.path.getmtime(self.COVER_PATH)
                if mtime != self._surface_mtime:
                    self._load_cover()
                    self._surface_mtime = mtime
                    # Pick new random effect on album change
                    self._fx_name, self._fx_func = random.choice(list(PIP_EFFECTS.items()))
        except OSError:
            pass

        # Reload attribution text if changed
        try:
            if os.path.exists(self.ATTRIB_PATH):
                mtime = os.path.getmtime(self.ATTRIB_PATH)
                if mtime != self._attrib_mtime:
                    from pathlib import Path

                    self._attrib_text = Path(self.ATTRIB_PATH).read_text().strip()
                    self._attrib_mtime = mtime
                    self._attrib_layout = None
        except OSError:
            pass

        if self._surface is None:
            return

        cr.save()
        x, y = int(self._x), int(self._y)
        cr.translate(x, y)

        # Draw splattribution text ABOVE the cover
        if self._attrib_text:
            self._draw_attrib(cr)

        # Paint album cover scaled to SIZE x SIZE
        sw = self._surface.get_width()
        sh = self._surface.get_height()
        if sw > 0 and sh > 0:
            scale = self.SIZE / max(sw, sh)
            cr.save()
            cr.scale(scale, scale)
            cr.set_source_surface(self._surface, 0, 0)
            cr.paint_with_alpha(self.ALPHA)
            cr.restore()

            # Apply PiP effect on the cover area
            if self._fx_func is not None:
                self._fx_func(cr, self.SIZE, self.SIZE)

        cr.restore()

    def _load_cover(self) -> None:
        """Load album cover PNG as a cairo surface."""
        try:
            import cairo

            self._surface = cairo.ImageSurface.create_from_png(self.COVER_PATH)
            log.info(
                "Album cover loaded (%dx%d)", self._surface.get_width(), self._surface.get_height()
            )
        except Exception:
            log.warning("Album cover load failed", exc_info=True)
            self._surface = None

    def _draw_attrib(self, cr: Any) -> None:
        """Draw splattribution text below the album cover."""
        import gi

        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo

        if self._attrib_layout is None:
            layout = PangoCairo.create_layout(cr)
            font = Pango.FontDescription.from_string("JetBrains Mono Bold 10")
            layout.set_font_description(font)
            layout.set_width(int(self.SIZE * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            text = self._attrib_text.replace("&", "&amp;").replace("<", "&lt;")
            layout.set_markup(text, -1)
            self._attrib_layout = layout

        _w, _h = self._attrib_layout.get_pixel_size()
        tx, ty = 0, -_h - 5  # above the cover

        # Dark outline
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.85)
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
            cr.move_to(tx + dx, ty + dy)
            PangoCairo.show_layout(cr, self._attrib_layout)
        # Foreground
        cr.set_source_rgba(1.0, 0.97, 0.90, 1.0)
        cr.move_to(tx, ty)
        PangoCairo.show_layout(cr, self._attrib_layout)


def _pip_draw(compositor: Any, cr: Any) -> None:
    """Post-FX cairooverlay callback: draws all overlays."""
    spiro = getattr(compositor, "_spirograph_reactor", None)
    if spiro is not None:
        spiro.draw(cr)
    album = getattr(compositor, "_album_overlay", None)
    if album is not None:
        album.draw(cr)
    token_pole = getattr(compositor, "_token_pole", None)
    if token_pole is not None:
        token_pole.draw(cr)


class FlashScheduler:
    """Audio-reactive live overlay flash on the camera base.

    Kick onsets trigger a flash. Flash duration scales with bass energy.
    Random baseline schedule fills gaps when no kicks are detected.
    Alpha decays smoothly from 0.6 → 0.0 for organic feel.
    """

    FLASH_ALPHA = 0.5
    # Random baseline — more on than off (bad reception feel)
    MIN_INTERVAL = 0.1  # very short gaps between flashes
    MAX_INTERVAL = 1.0  # max 1s gap
    MIN_DURATION = 0.5  # flashes last longer
    MAX_DURATION = 3.0
    # Audio-reactive
    KICK_COOLDOWN = 0.2  # normal mode
    KICK_COOLDOWN_VINYL = 0.4  # vinyl mode: half-speed = longer between kicks

    def __init__(self) -> None:
        self._next_flash_at: float = time.monotonic() + random.uniform(1.0, 3.0)
        self._flash_end_at: float = 0.0
        self._flashing: bool = False
        self._current_alpha: float = 0.0
        self._last_kick_at: float = 0.0

    def kick(self, t: float, bass_energy: float) -> None:
        """Called when a kick onset is detected. Triggers a flash."""
        cooldown = (
            self.KICK_COOLDOWN_VINYL if getattr(self, "_vinyl_mode", False) else self.KICK_COOLDOWN
        )
        if t - self._last_kick_at < cooldown:
            return  # cooldown
        self._last_kick_at = t
        self._flashing = True
        # Duration scales with bass energy: more bass = longer flash
        duration = 0.1 + bass_energy * 0.4  # 0.1s to 0.5s — short punch
        self._flash_end_at = t + min(duration, self.MAX_DURATION)
        self._current_alpha = self.FLASH_ALPHA

    def tick(self, t: float) -> float | None:
        """Returns target alpha if changed, None if no change needed."""
        if self._flashing:
            # Smooth decay toward end of flash
            remaining = self._flash_end_at - t
            total = self._flash_end_at - self._last_kick_at if self._last_kick_at > 0 else 1.0
            if remaining <= 0:
                self._flashing = False
                self._next_flash_at = t + random.uniform(self.MIN_INTERVAL, self.MAX_INTERVAL)
                if self._current_alpha != 0.0:
                    self._current_alpha = 0.0
                    return 0.0
            else:
                # Fade out over the last 40% of the flash
                fade_point = total * 0.6
                if remaining < fade_point and fade_point > 0:
                    target = self.FLASH_ALPHA * (remaining / fade_point)
                else:
                    target = self.FLASH_ALPHA
                if abs(target - self._current_alpha) > 0.02:
                    self._current_alpha = target
                    return target
        else:
            # Random baseline flash (fills silence)
            if t >= self._next_flash_at:
                self._flashing = True
                duration = random.uniform(self.MIN_DURATION, self.MAX_DURATION)
                self._flash_end_at = t + duration
                self._last_kick_at = t
                self._current_alpha = self.FLASH_ALPHA
                return self.FLASH_ALPHA
        return None


def build_inline_fx_chain(
    compositor: Any, pipeline: Any, pre_fx_tee: Any, output_tee: Any, fps: int
) -> bool:
    """Build GPU effects chain with glvideomixer for camera+live flash overlay.

    Pipeline:
      input-selector (camera) → queue → cairooverlay → glupload → glcolorconvert ─→ glvideomixer sink_0 (base, alpha=1)
      pre_fx_tee (live flash)  → queue →                glupload → glcolorconvert ─→ glvideomixer sink_1 (flash, alpha=0↔0.6)
                                                                                            ↓
                                                                                   [24 glfeedback slots]
                                                                                            ↓
                                                                                   glcolorconvert → gldownload → output_tee

    Both sources composited on GPU via glvideomixer. FlashScheduler
    animates the flash pad's alpha property (0.0 ↔ 0.6) on a random
    schedule. Text overlay (cairooverlay) on the base path goes through
    all shader effects.
    """
    Gst = compositor._Gst

    # --- Input selector for camera source switching ---
    input_sel = Gst.ElementFactory.make("input-selector", "fx-input-selector")
    input_sel.set_property("sync-streams", False)
    pipeline.add(input_sel)

    # --- Base path: input-selector → queue → cairooverlay → glupload → glcolorconvert ---
    queue_base = Gst.ElementFactory.make("queue", "queue-fx-base")
    queue_base.set_property("leaky", 2)
    queue_base.set_property("max-size-buffers", 2)

    from .overlay import on_draw, on_overlay_caps_changed

    overlay = Gst.ElementFactory.make("cairooverlay", "overlay")
    overlay.connect("draw", lambda o, cr, ts, dur: on_draw(compositor, o, cr, ts, dur))
    overlay.connect("caps-changed", lambda o, caps: on_overlay_caps_changed(compositor, o, caps))

    convert_base = Gst.ElementFactory.make("videoconvert", "fx-convert-base")
    convert_base.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    glupload_base = Gst.ElementFactory.make("glupload", "fx-glupload-base")
    glcc_base = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-base")

    # --- Flash path: pre_fx_tee → queue → glupload → glcolorconvert ---
    queue_flash = Gst.ElementFactory.make("queue", "queue-fx-flash")
    queue_flash.set_property("leaky", 2)
    queue_flash.set_property("max-size-buffers", 2)
    convert_flash = Gst.ElementFactory.make("videoconvert", "fx-convert-flash")
    convert_flash.set_property("dither", 0)  # none — Bayer default creates sawtooth columns
    glupload_flash = Gst.ElementFactory.make("glupload", "fx-glupload-flash")
    glcc_flash = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-flash")

    # --- glvideomixer: GPU-native compositing ---
    glmixer = Gst.ElementFactory.make("glvideomixer", "fx-glmixer")
    glmixer.set_property("background", 1)  # 1=black (default is 0=checker!)

    # --- Post-mixer: shader chain → output ---
    from agents.effect_graph.pipeline import SlotPipeline

    registry = compositor._graph_runtime._registry if compositor._graph_runtime else None
    compositor._slot_pipeline = SlotPipeline(registry, num_slots=24)

    glcolorconvert_out = Gst.ElementFactory.make("glcolorconvert", "fx-glcc-out")
    gldownload = Gst.ElementFactory.make("gldownload", "fx-gldownload")
    fx_convert = Gst.ElementFactory.make("videoconvert", "fx-out-convert")
    fx_convert.set_property("dither", 0)  # none — Bayer default creates sawtooth columns

    all_elements = [
        input_sel,
        queue_base,
        overlay,
        convert_base,
        glupload_base,
        glcc_base,
        queue_flash,
        convert_flash,
        glupload_flash,
        glcc_flash,
        glmixer,
        glcolorconvert_out,
        gldownload,
        fx_convert,
    ]
    for el in all_elements:
        if el is None:
            log.error("Failed to create FX element — effects disabled")
            return False
        pipeline.add(el)

    # --- Link base path ---
    input_sel.link(queue_base)
    queue_base.link(overlay)
    overlay.link(convert_base)
    convert_base.link(glupload_base)
    glupload_base.link(glcc_base)

    # --- Link flash path ---
    tee_pad_flash = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
    tee_pad_flash.link(queue_flash.get_static_pad("sink"))
    queue_flash.link(convert_flash)
    convert_flash.link(glupload_flash)
    glupload_flash.link(glcc_flash)

    # --- glvideomixer pads ---
    base_pad = glmixer.request_pad(glmixer.get_pad_template("sink_%u"), None, None)
    base_pad.set_property("zorder", 0)
    base_pad.set_property("alpha", 1.0)
    glcc_base.link_pads("src", glmixer, base_pad.get_name())

    flash_pad = glmixer.request_pad(glmixer.get_pad_template("sink_%u"), None, None)
    flash_pad.set_property("zorder", 1)
    flash_pad.set_property("alpha", 0.0)  # hidden until flash
    glcc_flash.link_pads("src", glmixer, flash_pad.get_name())

    # --- Store glmixer ref ---
    compositor._fx_glmixer = glmixer

    # --- Shader chain after mixer ---
    compositor._slot_pipeline.build_chain(pipeline, Gst, glmixer, glcolorconvert_out)

    glcolorconvert_out.link(gldownload)
    gldownload.link(fx_convert)

    # --- Post-FX cairooverlay: composites YouTube PiP AFTER shader chain ---
    # Uses CPU compositing (640x360 PiP on 1920x1080 output = trivial).
    # Avoids glvideomixer deadlock from dynamic pad addition.
    pip_overlay = Gst.ElementFactory.make("cairooverlay", "pip-overlay")
    pip_overlay.connect("draw", lambda o, cr, ts, dur: _pip_draw(compositor, cr))
    pipeline.add(pip_overlay)
    fx_convert.link(pip_overlay)
    pip_overlay.link(output_tee)

    # --- Input-selector: default to live (tiled composite) ---
    live_pad = input_sel.request_pad(input_sel.get_pad_template("sink_%u"), None, None)
    tee_pad_live = pre_fx_tee.request_pad(pre_fx_tee.get_pad_template("src_%u"), None, None)
    tee_pad_live.link(live_pad)
    input_sel.set_property("active-pad", live_pad)

    # --- Store everything ---
    compositor._fx_input_selector = input_sel
    compositor._fx_input_pads = {"live": live_pad}
    compositor._fx_active_source = "live"
    compositor._fx_camera_branch = []  # list[Any] — camera branch elements for teardown
    compositor._fx_switching = False
    compositor._fx_flash_pad = flash_pad
    compositor._fx_flash_scheduler = FlashScheduler()
    compositor._album_overlay = AlbumOverlay()

    from .token_pole import TokenPole

    compositor._token_pole = TokenPole()

    try:
        from .spirograph_reactor import SpirographReactor

        compositor._spirograph_reactor = SpirographReactor()
        compositor._yt_overlay = None
        log.info("SpirographReactor created")
    except Exception:
        log.exception("SpirographReactor failed, falling back to YouTubeOverlay")
        compositor._spirograph_reactor = None
        compositor._yt_overlay = YouTubeOverlay()

    log.info(
        "FX chain: %d shader slots, glvideomixer (camera base + live flash 60%%)",
        compositor._slot_pipeline.num_slots,
    )
    return True


def switch_fx_source(compositor: Any, source: str) -> bool:
    """Switch FX chain input to a different camera or back to tiled composite.

    Uses IDLE pad probe to safely modify the pipeline while PLAYING.
    Creates camera branch on-demand (lazy), tears down old one.
    """
    if not hasattr(compositor, "_fx_input_selector"):
        return False
    if source == getattr(compositor, "_fx_active_source", "live"):
        return True  # already active
    if getattr(compositor, "_fx_switching", False):
        return False  # switch in progress

    Gst = compositor._Gst
    input_sel = compositor._fx_input_selector
    pipeline = compositor.pipeline

    if source == "live":
        # Switch back to tiled composite — just set active pad
        live_pad = compositor._fx_input_pads.get("live")
        if live_pad is None:
            return False
        input_sel.set_property("active-pad", live_pad)
        _teardown_camera_branch(compositor, Gst)
        compositor._fx_active_source = "live"
        log.info("FX source: switched to live (tiled composite)")
        return True

    # YouTube source: v4l2src from /dev/video50
    is_youtube = source == "youtube"

    if not is_youtube:
        # Switch to individual camera — need to create branch on-demand
        role = source.replace("-", "_")
        cam_tee = pipeline.get_by_name(f"tee_{role}")
        if cam_tee is None:
            log.warning("FX source: camera tee for %s not found", source)
            return False

    compositor._fx_switching = True

    # Use IDLE probe on input-selector src pad for safe modification
    src_pad = input_sel.get_static_pad("src")

    def _probe_callback(pad: Any, info: Any) -> Any:
        try:
            # Tear down previous camera branch if any
            _teardown_camera_branch(compositor, Gst)

            out_w = compositor.config.output_width
            out_h = compositor.config.output_height
            fps = compositor.config.framerate

            if is_youtube:
                # YouTube: v4l2src from /dev/video50
                v4l2 = Gst.ElementFactory.make("v4l2src", "fxsrc-yt")
                v4l2.set_property("device", "/dev/video50")
                v4l2.set_property("do-timestamp", True)
                q = Gst.ElementFactory.make("queue", "fxsrc-q")
                q.set_property("leaky", 2)
                q.set_property("max-size-buffers", 1)
                convert = Gst.ElementFactory.make("videoconvert", "fxsrc-convert")
                convert.set_property("dither", 0)
                scale = Gst.ElementFactory.make("videoscale", "fxsrc-scale")
                caps = Gst.ElementFactory.make("capsfilter", "fxsrc-caps")
                caps.set_property(
                    "caps",
                    Gst.Caps.from_string(f"video/x-raw,format=BGRA,width={out_w},height={out_h}"),
                )
                elements = [v4l2, q, convert, scale, caps]
                for el in elements:
                    pipeline.add(el)
                v4l2.link(q)
                q.link(convert)
                convert.link(scale)
                scale.link(caps)
                for el in elements:
                    el.sync_state_with_parent()
            else:
                # Camera: branch from camera_tee
                q = Gst.ElementFactory.make("queue", "fxsrc-q")
                q.set_property("leaky", 2)
                q.set_property("max-size-buffers", 1)
                convert = Gst.ElementFactory.make("videoconvert", "fxsrc-convert")
                convert.set_property("dither", 0)
                scale = Gst.ElementFactory.make("videoscale", "fxsrc-scale")
                caps = Gst.ElementFactory.make("capsfilter", "fxsrc-caps")
                caps.set_property(
                    "caps",
                    Gst.Caps.from_string(
                        f"video/x-raw,format=BGRA,width={out_w},height={out_h},framerate={fps}/1"
                    ),
                )

                elements = [q, convert, scale, caps]
                for el in elements:
                    pipeline.add(el)
                q.link(convert)
                convert.link(scale)
                scale.link(caps)
                for el in elements:
                    el.sync_state_with_parent()

                # Link camera tee → queue
                tee_pad = cam_tee.request_pad(cam_tee.get_pad_template("src_%u"), None, None)
                q_sink = q.get_static_pad("sink")
                tee_pad.link(q_sink)

            # Link caps → new input-selector pad
            sel_pad = input_sel.request_pad(input_sel.get_pad_template("sink_%u"), None, None)
            caps.link_pads("src", input_sel, sel_pad.get_name())

            # Switch active pad
            input_sel.set_property("active-pad", sel_pad)

            # Store for teardown
            if is_youtube:
                elements = [
                    el
                    for el in [
                        pipeline.get_by_name("fxsrc-yt"),
                        pipeline.get_by_name("fxsrc-q"),
                        pipeline.get_by_name("fxsrc-convert"),
                        pipeline.get_by_name("fxsrc-scale"),
                        pipeline.get_by_name("fxsrc-caps"),
                    ]
                    if el is not None
                ]
            compositor._fx_camera_branch = elements
            compositor._fx_camera_tee_pad = None if is_youtube else tee_pad
            compositor._fx_camera_sel_pad = sel_pad
            compositor._fx_active_source = source
            compositor._fx_switching = False

            log.info("FX source: switched to %s (lazy branch created)", source)
        except Exception:
            log.exception("FX source switch failed")
            compositor._fx_switching = False

        return Gst.PadProbeReturn.REMOVE

    src_pad.add_probe(Gst.PadProbeType.IDLE, _probe_callback)
    return True


def _teardown_camera_branch(compositor: Any, Gst: Any) -> None:
    """Remove the previous camera-specific FX source branch."""
    elements = getattr(compositor, "_fx_camera_branch", [])
    if not elements:
        return

    pipeline = compositor.pipeline

    # Unlink camera tee pad
    tee_pad = getattr(compositor, "_fx_camera_tee_pad", None)
    if tee_pad is not None:
        peer = tee_pad.get_peer()
        if peer is not None:
            tee_pad.unlink(peer)

    # Release input-selector pad
    sel_pad = getattr(compositor, "_fx_camera_sel_pad", None)
    if sel_pad is not None:
        compositor._fx_input_selector.release_request_pad(sel_pad)

    # Stop and remove elements
    for el in reversed(elements):
        el.set_state(Gst.State.NULL)
        pipeline.remove(el)

    compositor._fx_camera_branch = []
    compositor._fx_camera_tee_pad = None
    compositor._fx_camera_sel_pad = None


def fx_tick_callback(compositor: Any) -> bool:
    """GLib timeout: update graph shader uniforms at ~30fps."""
    if not compositor._running:
        return False
    if not hasattr(compositor, "_slot_pipeline") or compositor._slot_pipeline is None:
        return False

    from .fx_tick import tick_governance, tick_modulator, tick_slot_pipeline

    if not hasattr(compositor, "_fx_monotonic_start"):
        compositor._fx_monotonic_start = time.monotonic()
    t = time.monotonic() - compositor._fx_monotonic_start

    with compositor._overlay_state._lock:
        energy = compositor._overlay_state._data.audio_energy_rms
    beat = min(energy * 4.0, 1.0)
    if not hasattr(compositor, "_fx_beat_smooth"):
        compositor._fx_beat_smooth = 0.0
    compositor._fx_beat_smooth = max(beat, compositor._fx_beat_smooth * 0.85)
    b = compositor._fx_beat_smooth

    # Cache audio signals BEFORE tick_modulator (which calls get_signals and decays them)
    cached_audio: dict[str, float] = {}
    if hasattr(compositor, "_audio_capture"):
        cached_audio = compositor._audio_capture.get_signals()
    compositor._cached_audio = cached_audio

    tick_governance(compositor, t)
    tick_modulator(compositor, t, energy, b)
    tick_slot_pipeline(compositor, t)

    # Flash scheduler: animate glvideomixer flash pad alpha
    scheduler = getattr(compositor, "_fx_flash_scheduler", None)
    flash_pad = getattr(compositor, "_fx_flash_pad", None)
    if scheduler and flash_pad:
        now = time.monotonic()
        kick = cached_audio.get("onset_kick", 0.0)
        beat = cached_audio.get("beat_pulse", 0.0)
        bass = cached_audio.get("mixer_bass", 0.0)
        if kick > 0.3 or beat > 0.6:
            scheduler.kick(now, bass)
        alpha = scheduler.tick(now)
        if alpha is not None:
            flash_pad.set_property("alpha", alpha)

    # Album overlay: floating cover + splattribution
    album_overlay = getattr(compositor, "_album_overlay", None)
    if album_overlay:
        album_overlay.tick()

    # Token pole: vertical progress bar + particles
    token_pole = getattr(compositor, "_token_pole", None)
    if token_pole:
        token_pole.tick()

    # Spirograph reactor
    spiro = getattr(compositor, "_spirograph_reactor", None)
    if spiro:
        spiro.tick()

    return True
