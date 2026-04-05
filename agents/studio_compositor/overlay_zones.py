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
        "x": 20,
        "y": 160,
        "max_width": 700,
        "font": "JetBrains Mono 11",
        "color": (0.92, 0.86, 0.70, 0.9),
        "randomize_position": True,
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

    def _randomize_xy(self, canvas_w: int = 1920, canvas_h: int = 1080) -> None:
        """Randomize position within safe margins on each cycle."""
        import random

        margin_x, margin_y = 40, 120
        sw, sh = self._cached_surface_size if self._cached_surface_size[0] else (400, 200)
        max_x = max(margin_x, canvas_w - sw - margin_x)
        max_y = max(margin_y, canvas_h - sh - margin_y)
        self.x = random.randint(margin_x, max_x)
        self.y = random.randint(margin_y, max_y)

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
            self._folder_index = (self._folder_index + 1) % len(self._folder_files)
            self._cycle_start = now
            # Randomize position on each cycle
            if self.randomize_position:
                self._randomize_xy()
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

    def _load_text(self, path: Path) -> None:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        content_hash = hash(raw)
        if content_hash == self._content_hash:
            return
        is_ansi = path.suffix == ".ansi"
        self._pango_markup = parse_overlay_content(raw, is_ansi=is_ansi)
        self._content_hash = content_hash
        self._layout = None
        self._cached_surface = None
        self._is_image = False
        self._image_surface = None
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

        # Semi-transparent background (60% opacity)
        scr.set_source_rgba(0.0, 0.0, 0.0, 0.6)
        scr.rectangle(0, 0, sw, sh)
        scr.fill()
        # Dark outline: 4 offsets
        scr.set_source_rgba(0.0, 0.0, 0.0, 0.8)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
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
