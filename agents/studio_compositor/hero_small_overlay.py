"""Hero small tile overlay — projects the hero camera snapshot on cairooverlay.

Reads the hero camera's JPEG snapshot from /dev/shm and draws it at the
``_hero_small`` tile position (a virtual layout rect; underscore prefix
means no GStreamer compositor pad is created for it). Source JPEG only
changes every 5 seconds (the snapshot branch refresh rate) and we cache
the decoded surface for 500ms — re-decoding is cheap-ish but not free.

The overlay draws in the post-FX cairooverlay callback as a constant-alpha
projection. It is a bounded monitor aid, not layout success and not a
replacement for capture-side face obscuring.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agents.studio_compositor.homage import get_active_package
from shared.homage_package import HomagePackage

from .models import TileRect
from .projected_hero import (
    PROJECTED_HERO_MIN_DWELL_S,
    ProjectedHeroProfile,
    build_projected_hero_profile,
)

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

_SNAPSHOT_DIR = Path("/dev/shm/hapax-compositor")


def _fallback_package() -> HomagePackage:
    from agents.studio_compositor.homage.bitchx import BITCHX_PACKAGE

    return BITCHX_PACKAGE


_CACHE_TTL_S = PROJECTED_HERO_MIN_DWELL_S


class HeroSmallOverlay:
    """Cairo-based hero small tile blitter."""

    def __init__(self, hero_role: str, tile_x: int, tile_y: int, tile_w: int, tile_h: int) -> None:
        self._hero_role = hero_role
        self._tile_x = tile_x
        self._tile_y = tile_y
        self._tile_w = tile_w
        self._tile_h = tile_h
        self._projection: ProjectedHeroProfile = build_projected_hero_profile(
            hero_role,
            TileRect(x=tile_x, y=tile_y, w=tile_w, h=tile_h),
        )
        self._surface: cairo.ImageSurface | None = None
        self._last_load: float = 0.0
        self._lock = threading.Lock()
        log.info(
            "HeroSmallOverlay: %s at (%d,%d) %dx%d",
            hero_role,
            tile_x,
            tile_y,
            tile_w,
            tile_h,
        )

    def _try_load(self) -> None:
        """Load hero JPEG into a cairo surface, rate-limited to one read per TTL."""
        now = time.monotonic()
        if now - self._last_load < _CACHE_TTL_S:
            return
        self._last_load = now

        jpeg_path = _SNAPSHOT_DIR / f"{self._hero_role}.jpg"
        if not jpeg_path.exists():
            return

        try:
            import cairo
            import numpy as np
            from PIL import Image

            img = Image.open(jpeg_path)
            img = img.convert("RGBA")
            img = img.resize((self._tile_w, self._tile_h), Image.LANCZOS)
            arr = np.array(img)
            bgra = np.empty_like(arr)
            bgra[:, :, 0] = arr[:, :, 2]
            bgra[:, :, 1] = arr[:, :, 1]
            bgra[:, :, 2] = arr[:, :, 0]
            bgra[:, :, 3] = arr[:, :, 3]

            buf = bytearray(bgra.tobytes())
            surface = cairo.ImageSurface.create_for_data(
                buf,
                cairo.FORMAT_ARGB32,
                self._tile_w,
                self._tile_h,
            )
            surface._hapax_buf = buf
            with self._lock:
                self._surface = surface
        except Exception:
            log.debug("HeroSmallOverlay: snapshot load failed", exc_info=True)

    def draw(self, cr: Any) -> None:
        """Blit the hero snapshot at the tile position. Called from cairooverlay."""
        self._try_load()

        with self._lock:
            surface = self._surface

        if surface is None:
            return

        try:
            pkg = get_active_package() or _fallback_package()
            bg_r, bg_g, bg_b, _ = pkg.resolve_colour("background")
            br_r, br_g, br_b, _ = pkg.resolve_colour("bright")

            cr.save()
            cr.set_source_rgba(bg_r, bg_g, bg_b, self._projection.backdrop_alpha)
            cr.rectangle(self._tile_x, self._tile_y, self._tile_w, self._tile_h)
            cr.fill()
            cr.set_source_surface(surface, self._tile_x, self._tile_y)
            cr.rectangle(self._tile_x, self._tile_y, self._tile_w, self._tile_h)
            cr.paint_with_alpha(self._projection.alpha)
            cr.set_source_rgba(br_r, br_g, br_b, self._projection.border_alpha)
            cr.rectangle(self._tile_x + 0.5, self._tile_y + 0.5, self._tile_w - 1, self._tile_h - 1)
            cr.set_line_width(1.0)
            cr.stroke()
            cr.restore()
        except Exception:
            log.debug("HeroSmallOverlay: draw failed", exc_info=True)
