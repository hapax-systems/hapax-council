"""Overlay zone manager — reads content files, cycles folders, caches Pango layouts."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from .overlay_parser import parse_overlay_content

log = logging.getLogger(__name__)

SNAPSHOT_DIR = Path("/dev/shm/hapax-compositor")

ZONES: list[dict[str, Any]] = [
    {
        "id": "main",
        "folder": "~/Documents/Personal/30-areas/stream-overlays/",
        "suffixes": (".md", ".txt", ".ansi"),
        "cycle_seconds": 15,
        "x": 40,
        "y": 200,
        "max_width": 1000,
        "font": "JetBrains Mono Bold 20",
        "color": (1.0, 0.97, 0.90, 1.0),
        "randomize_position": True,
    },
    {
        "id": "lyrics",
        "file": "/dev/shm/hapax-compositor/track-lyrics.txt",
        "x": 1350,
        "y": 0,
        "max_width": 500,
        "font": "JetBrains Mono 14",
        "color": (0.95, 0.90, 0.80, 0.9),
        "scroll": True,
        "scroll_speed": 0.5,
    },
]


class OverlayZone:
    def __init__(self, config: dict[str, Any]) -> None:
        self.id = config["id"]
        self.folder = config.get("folder")
        self.file = config.get("file")
        self.suffixes = tuple(config.get("suffixes", (".md", ".ansi", ".txt")))
        self.cycle_seconds = config.get("cycle_seconds", 45)
        self.base_x = config["x"]
        self.base_y = config["y"]
        self.x = self.base_x
        self.y = self.base_y
        self.max_width = config.get("max_width", 700)
        self.font_desc = config.get("font", "JetBrains Mono 11")
        self.color = config.get("color", (0.92, 0.86, 0.70, 0.9))
        self.randomize_position = config.get("randomize_position", False)
        self._attribution_format = config.get("attribution_format", False)
        self._scroll = config.get("scroll", False)
        self._scroll_speed = config.get("scroll_speed", 0.5)  # pixels per tick
        self._scroll_offset = 0.0
        self._is_image = False
        self._image_surface: Any = None
        self._layout: Any = None
        self._pango_markup: str = ""
        self._content_hash: int = 0
        self._cached_surface: Any = None
        self._cached_surface_size: tuple[int, int] = (0, 0)
        self._last_mtime: float = 0
        self._folder_files: list[Path] = []
        self._folder_index: int = 0
        self._folder_last_scan: float = 0
        self._cycle_start: float = 0

    def tick(self) -> None:
        now = time.monotonic()
        if self.folder:
            self._tick_folder(now)
        elif self.file:
            self._tick_file()
        # Float/bounce every tick regardless of content source
        if self.randomize_position:
            self._tick_float()
        elif self._scroll:
            self._tick_scroll()

    def _init_float(self) -> None:
        """Initialize DVD-screensaver-style floating motion."""
        import random

        self._vx = random.choice([-1, 1]) * random.uniform(0.8, 2.0)  # pixels per tick
        self._vy = random.choice([-1, 1]) * random.uniform(0.5, 1.5)
        self._float_x = float(self.base_x)
        self._float_y = float(self.base_y)

    def _tick_scroll(self, canvas_h: int = 1080) -> None:
        """Scroll text upward like credits. Resets when fully scrolled off."""
        self._scroll_offset += self._scroll_speed
        text_h = self._cached_surface_size[1] if self._cached_surface_size[1] else 200
        # When text scrolls completely off the top, reset to bottom
        if self._scroll_offset > text_h + canvas_h:
            self._scroll_offset = 0.0

    def _tick_float(self, canvas_w: int = 1920, canvas_h: int = 1080) -> None:
        """Move position and bounce off screen edges."""
        if not hasattr(self, "_vx"):
            self._init_float()

        sw, sh = self._cached_surface_size if self._cached_surface_size[0] else (400, 200)
        margin = 20

        self._float_x += self._vx
        self._float_y += self._vy

        # Bounce off edges
        if self._float_x <= margin:
            self._float_x = margin
            self._vx = abs(self._vx)
        elif self._float_x + sw >= canvas_w - margin:
            self._float_x = canvas_w - sw - margin
            self._vx = -abs(self._vx)

        if self._float_y <= margin:
            self._float_y = margin
            self._vy = abs(self._vy)
        elif self._float_y + sh >= canvas_h - margin:
            self._float_y = canvas_h - sh - margin
            self._vy = -abs(self._vy)

        self.x = int(self._float_x)
        self.y = int(self._float_y)

    def _tick_folder(self, now: float) -> None:
        folder = Path(self.folder).expanduser()
        if not folder.is_dir():
            return
        if now - self._folder_last_scan > 60.0 or not self._folder_files:
            self._folder_files = sorted(
                f for f in folder.iterdir() if f.suffix in self.suffixes and f.is_file()
            )
            self._folder_last_scan = now
            if not self._folder_files:
                return
        if self._cycle_start == 0:
            self._cycle_start = now
        elif now - self._cycle_start >= self.cycle_seconds:
            import random

            # Random file each cycle, avoid repeating the same one
            old_idx = self._folder_index
            self._folder_index = random.randrange(len(self._folder_files))
            if self._folder_index == old_idx and len(self._folder_files) > 1:
                self._folder_index = (self._folder_index + 1) % len(self._folder_files)
            self._cycle_start = now
        if self._folder_files:
            idx = self._folder_index % len(self._folder_files)
            self._load_content(self._folder_files[idx])

    def _tick_file(self) -> None:
        path = Path(self.file)
        if not path.exists():
            if self._content_hash != 0:
                self._layout = None
                self._content_hash = 0
                self._pango_markup = ""
                self._is_image = False
                self._image_surface = None
            return
        try:
            mtime = os.path.getmtime(path)
            if mtime != self._last_mtime:
                self._load_content(path)
                self._last_mtime = mtime
        except OSError:
            pass

    def _load_content(self, path: Path) -> None:
        """Load either a text file (Pango) or an image (PNG surface)."""
        if path.suffix == ".png":
            self._load_image(path)
        else:
            self._load_text(path)

    def _load_image(self, path: Path) -> None:
        """Load a PNG file as a cairo image surface."""
        import cairo

        path_str = str(path)
        content_hash = hash((path_str, os.path.getmtime(path)))
        if content_hash == self._content_hash:
            return
        try:
            surface = cairo.ImageSurface.create_from_png(path_str)
            self._image_surface = surface
            self._is_image = True
            self._content_hash = content_hash
            self._cached_surface = None
            self._pango_markup = ""
            self._layout = None
            self._cached_surface_size = (surface.get_width(), surface.get_height())
            log.debug(
                "Overlay zone '%s' loaded image %s (%dx%d)",
                self.id,
                path.name,
                surface.get_width(),
                surface.get_height(),
            )
        except Exception:
            log.warning("Overlay zone '%s' failed to load image %s", self.id, path.name)

    def _format_attribution(self, raw: str) -> str:
        """Format yt-attribution.txt (title\\nchannel\\nurl) as Pango markup."""
        lines = raw.strip().split("\n")
        title = lines[0] if lines else "Unknown"
        channel = lines[1] if len(lines) > 1 else ""
        url = lines[2] if len(lines) > 2 else ""
        # Escape for Pango
        title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        channel = channel.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        url = url.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts = [f"<b>{title}</b>"]
        if channel:
            parts.append(channel)
        if url:
            parts.append(f'<span size="small">{url}</span>')
        return "\n".join(parts)

    def _load_text(self, path: Path) -> None:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        content_hash = hash(raw)
        if content_hash == self._content_hash:
            return
        if self._attribution_format:
            self._pango_markup = self._format_attribution(raw)
        else:
            is_ansi = path.suffix == ".ansi"
            self._pango_markup = parse_overlay_content(raw, is_ansi=is_ansi)
        self._content_hash = content_hash
        self._layout = None
        self._cached_surface = None
        self._is_image = False
        self._image_surface = None
        if self._scroll:
            self._scroll_offset = 0.0  # reset scroll on new content
        log.debug("Overlay zone '%s' updated from %s (%d chars)", self.id, path.name, len(raw))

    def render(self, cr: Any, canvas_w: int, canvas_h: int) -> None:
        if self._is_image and self._image_surface is not None:
            self._render_image(cr, canvas_w, canvas_h)
            return

        if not self._pango_markup:
            return

        if self._cached_surface is None:
            self._rebuild_surface(cr)
        if self._cached_surface is None:
            return

        # Paint the pre-rendered outlined text surface — single blit per frame
        if self._scroll:
            # Scroll: text moves upward from bottom
            scroll_y = canvas_h - self._scroll_offset
            cr.set_source_surface(self._cached_surface, self.x - 2, scroll_y)
        else:
            cr.set_source_surface(self._cached_surface, self.x - 2, self.y - 2)
        cr.paint()

    def _render_image(self, cr: Any, canvas_w: int, canvas_h: int) -> None:
        """Render a PNG image overlay, scaled to fit max_width."""
        surf = self._image_surface
        iw, ih = surf.get_width(), surf.get_height()
        if iw == 0 or ih == 0:
            return
        scale = min(self.max_width / iw, 1.0)
        cr.save()
        cr.translate(self.x, self.y)
        cr.scale(scale, scale)
        cr.set_source_surface(surf, 0, 0)
        cr.paint_with_alpha(self.color[3])
        cr.restore()

    def _rebuild_surface(self, cr: Any) -> None:
        """Pre-render outlined text to a cairo image surface (cached)."""
        import cairo
        import gi

        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo

        # Create layout on the live context to get correct font metrics
        layout = PangoCairo.create_layout(cr)
        font = Pango.FontDescription.from_string(self.font_desc)
        layout.set_font_description(font)
        layout.set_width(int(self.max_width * Pango.SCALE))
        layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_markup(self._pango_markup, -1)
        self._layout = layout

        _w, _h = layout.get_pixel_size()
        pad = 4  # room for outline offsets
        sw, sh = _w + pad * 2, _h + pad * 2

        # Render outlined text to an offscreen ARGB surface
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, sw, sh)
        scr = cairo.Context(surface)

        # No background rectangle — it creates visible edge artifacts when
        # processed through shaders (thermal, halftone, mirror produce
        # vertical stripe patterns from the rectangle borders).
        # Text legibility comes from the thick 3px dark outline below.
        # Dark outline: 8 offsets at 3px for thick readable border
        scr.set_source_rgba(0.0, 0.0, 0.0, 0.9)
        for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, -2), (-2, 2), (2, 2)):
            scr.move_to(pad + dx, pad + dy)
            PangoCairo.show_layout(scr, layout)
        # Foreground
        scr.move_to(pad, pad)
        scr.set_source_rgba(*self.color)
        PangoCairo.show_layout(scr, layout)

        self._cached_surface = surface
        self._cached_surface_size = (sw, sh)


class OverlayZoneManager:
    def __init__(self, zone_configs: list[dict[str, Any]] | None = None) -> None:
        configs = zone_configs or ZONES
        self.zones = [OverlayZone(cfg) for cfg in configs]

    def tick(self) -> None:
        for zone in self.zones:
            zone.tick()

    def render(self, cr: Any, canvas_w: int, canvas_h: int) -> None:
        for zone in self.zones:
            zone.render(cr, canvas_w, canvas_h)
