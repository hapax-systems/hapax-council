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
        "file": None,
        "cycle_seconds": 15,
        "x": 20,
        "y": 160,
        "max_width": 700,
        "font": "JetBrains Mono 11",
        "color": (0.92, 0.86, 0.70, 0.9),
    },
    {
        "id": "art",
        "folder": None,
        "file": str(SNAPSHOT_DIR / "overlay-art.ansi"),
        "cycle_seconds": 60,
        "x": 20,
        "y": 800,
        "max_width": 900,
        "font": "MxPlus IBM VGA 9x16 12",
        "color": (0.92, 0.86, 0.70, 0.85),
    },
]


class OverlayZone:
    def __init__(self, config: dict[str, Any]) -> None:
        self.id = config["id"]
        self.folder = config.get("folder")
        self.file = config.get("file")
        self.cycle_seconds = config.get("cycle_seconds", 45)
        self.x = config["x"]
        self.y = config["y"]
        self.max_width = config.get("max_width", 700)
        self.font_desc = config.get("font", "JetBrains Mono 11")
        self.color = config.get("color", (0.92, 0.86, 0.70, 0.9))
        self._layout: Any = None
        self._pango_markup: str = ""
        self._content_hash: int = 0
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

    def _tick_folder(self, now: float) -> None:
        folder = Path(self.folder).expanduser()
        if not folder.is_dir():
            return
        if now - self._folder_last_scan > 60.0 or not self._folder_files:
            self._folder_files = sorted(
                f for f in folder.iterdir() if f.suffix in (".md", ".ansi", ".txt") and f.is_file()
            )
            self._folder_last_scan = now
            if not self._folder_files:
                return
        if self._cycle_start == 0:
            self._cycle_start = now
        elif now - self._cycle_start >= self.cycle_seconds:
            self._folder_index = (self._folder_index + 1) % len(self._folder_files)
            self._cycle_start = now
        if self._folder_files:
            idx = self._folder_index % len(self._folder_files)
            self._read_file(self._folder_files[idx])

    def _tick_file(self) -> None:
        path = Path(self.file)
        if not path.exists():
            if self._content_hash != 0:
                self._layout = None
                self._content_hash = 0
                self._pango_markup = ""
            return
        try:
            mtime = os.path.getmtime(path)
            if mtime != self._last_mtime:
                self._read_file(path)
                self._last_mtime = mtime
        except OSError:
            pass

    def _read_file(self, path: Path) -> None:
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
        log.debug("Overlay zone '%s' updated from %s (%d chars)", self.id, path.name, len(raw))

    def render(self, cr: Any, canvas_w: int, canvas_h: int) -> None:
        if not self._pango_markup:
            return
        import gi

        gi.require_version("Pango", "1.0")
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo

        if self._layout is None:
            layout = PangoCairo.create_layout(cr)
            font = Pango.FontDescription.from_string(self.font_desc)
            layout.set_font_description(font)
            layout.set_width(int(self.max_width * Pango.SCALE))
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
            layout.set_markup(self._pango_markup, -1)
            self._layout = layout

        _w, _h = self._layout.get_pixel_size()
        pad = 6
        cr.set_source_rgba(0.0, 0.0, 0.0, 0.5)
        cr.rectangle(self.x - pad, self.y - pad, _w + pad * 2, _h + pad * 2)
        cr.fill()
        cr.move_to(self.x, self.y)
        cr.set_source_rgba(*self.color)
        PangoCairo.show_layout(cr, self._layout)


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
