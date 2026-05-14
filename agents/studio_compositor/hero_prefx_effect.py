"""Hero pre-FX effect — applies hero camera effects on the pre_fx Cairo layer.

Replaces the GStreamer glfeedback hero-effect-slot with a software-based
approach that renders the hero effect on the same Cairo overlay as all other
wards, ensuring it goes through the GL shader chain uniformly.

The effect is applied by:
1. Reading the hero camera snapshot JPEG from /dev/shm
2. Applying a PIL/numpy-based visual effect (edge detect, scanlines, etc.)
3. Blitting the result onto the pre_fx Cairo surface at the hero tile position

This keeps the hero effect "attached" to the hero image and in the same
layer as everything else.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image, ImageFilter

if TYPE_CHECKING:
    import cairo

log = logging.getLogger(__name__)

_SNAPSHOT_DIR = Path("/dev/shm/hapax-compositor")

# How often to rotate the hero effect (seconds).
_ROTATE_INTERVAL_MIN = 45.0
_ROTATE_INTERVAL_MAX = 90.0

# Cache the decoded+effected surface for this many seconds.
_CACHE_TTL_S = 2.0


def _effect_edge_detect(img: Image.Image) -> Image.Image:
    """Sobel edge detection."""
    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return edges.convert("RGBA")


def _effect_emboss(img: Image.Image) -> Image.Image:
    """Emboss filter."""
    return img.filter(ImageFilter.EMBOSS)


def _effect_scanlines(img: Image.Image) -> Image.Image:
    """CRT scanline simulation."""
    arr = np.array(img, dtype=np.float32)
    h = arr.shape[0]
    scanline = np.ones(h, dtype=np.float32)
    for y in range(h):
        if y % 4 < 2:
            scanline[y] = 0.6
    arr[:, :, :3] *= scanline[:, np.newaxis, np.newaxis]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _effect_posterize(img: Image.Image) -> Image.Image:
    """Posterization — reduce color levels."""
    arr = np.array(img)
    levels = 6
    arr[:, :, :3] = (arr[:, :, :3] // (256 // levels)) * (256 // levels)
    return Image.fromarray(arr)


def _effect_thermal(img: Image.Image) -> Image.Image:
    """Thermal / heat-map colorization."""
    arr = np.array(img, dtype=np.float32)
    gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    norm = gray / 255.0
    r = np.clip(norm * 3.0, 0, 1) * 255
    g = np.clip((norm - 0.33) * 3.0, 0, 1) * 255
    b = np.clip(np.where(norm < 0.5, norm * 2.0, (1.0 - norm) * 2.0), 0, 1) * 255
    out = np.stack([r, g, b, arr[:, :, 3]], axis=-1)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def _effect_nightvision(img: Image.Image) -> Image.Image:
    """Night vision green-channel boost with noise."""
    arr = np.array(img, dtype=np.float32)
    gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    noise = np.random.normal(0, 8, gray.shape).astype(np.float32)
    gray = np.clip(gray + noise, 0, 255)
    out = arr.copy()
    out[:, :, 0] = gray * 0.1
    out[:, :, 1] = gray * 1.2
    out[:, :, 2] = gray * 0.1
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def _effect_kuwahara(img: Image.Image) -> Image.Image:
    """Simplified Kuwahara painterly effect."""
    smoothed = img.filter(ImageFilter.ModeFilter(size=5))
    smoothed = smoothed.filter(ImageFilter.SMOOTH_MORE)
    return smoothed


# Registry of available effects
_EFFECTS: list[tuple[str, Any]] = [
    ("edge_detect", _effect_edge_detect),
    ("emboss", _effect_emboss),
    ("scanlines", _effect_scanlines),
    ("posterize", _effect_posterize),
    ("thermal", _effect_thermal),
    ("nightvision", _effect_nightvision),
    ("kuwahara", _effect_kuwahara),
]


def _hero_prefx_enabled() -> bool:
    """Check env flag. Enabled by default when the GL hero slot is disabled."""
    raw = os.environ.get("HAPAX_HERO_PREFX_EFFECT_ENABLED", "")
    if raw.strip().lower() in ("0", "false", "no", "off", "disabled"):
        return False
    # Auto-enable when GL hero slot is disabled
    if not raw and os.environ.get("HAPAX_COMPOSITOR_DISABLE_HERO_EFFECT") == "1":
        return True
    return raw.strip().lower() in ("1", "true", "yes", "on", "enabled", "")


class HeroPreFxEffect:
    """Cairo-based hero effect applied on the pre_fx layer.

    Gets the hero tile position dynamically from the compositor's
    _tile_layout at draw time, so it adapts to layout changes.
    """

    def __init__(self) -> None:
        self._surface: cairo.ImageSurface | None = None
        self._last_load: float = 0.0
        self._last_tile: tuple[int, int, int, int] | None = None
        self._lock = threading.Lock()
        self._current_idx: int = -1
        self._next_rotate: float = 0.0
        self._hero_role: str | None = None
        log.info(
            "HeroPreFxEffect: initialized with %d effects, auto-enabled=%s",
            len(_EFFECTS), _hero_prefx_enabled(),
        )

    def _resolve_hero(self, compositor: Any) -> tuple[str, int, int, int, int] | None:
        """Dynamically resolve the hero camera tile from compositor state."""
        tile_layout = getattr(compositor, "_tile_layout", None) or {}
        cameras = getattr(getattr(compositor, "config", None), "cameras", ()) or ()
        for cam in cameras:
            role = getattr(cam, "role", "")
            if not getattr(cam, "hero", False) or not role:
                continue
            tile = tile_layout.get(role)
            if tile is None:
                continue
            w = getattr(tile, "w", 0)
            h = getattr(tile, "h", 0)
            if w <= 0 or h <= 0:
                continue
            return role, getattr(tile, "x", 0), getattr(tile, "y", 0), w, h
        return None

    def tick(self) -> None:
        """Called periodically to rotate effects."""
        now = time.monotonic()
        if now >= self._next_rotate:
            self._rotate()
            self._next_rotate = now + random.uniform(
                _ROTATE_INTERVAL_MIN, _ROTATE_INTERVAL_MAX,
            )

    def _rotate(self) -> None:
        if len(_EFFECTS) > 1:
            candidates = list(range(len(_EFFECTS)))
            if self._current_idx >= 0:
                candidates.remove(self._current_idx)
            self._current_idx = random.choice(candidates)
        else:
            self._current_idx = 0
        name, _ = _EFFECTS[self._current_idx]
        log.info("Hero pre-FX effect → %s", name)
        self._last_load = 0.0  # force reload

    def _try_load(self, role: str, tile_w: int, tile_h: int) -> None:
        now = time.monotonic()
        if now - self._last_load < _CACHE_TTL_S:
            return
        self._last_load = now

        if self._current_idx < 0:
            self._rotate()

        jpeg_path = _SNAPSHOT_DIR / f"{role}.jpg"
        if not jpeg_path.exists():
            return

        try:
            import cairo as _cairo

            img = Image.open(jpeg_path)
            img = img.convert("RGBA")
            img = img.resize((tile_w, tile_h), Image.LANCZOS)

            # Apply the current hero effect
            name, effect_fn = _EFFECTS[self._current_idx]
            img = effect_fn(img)
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            # Convert to Cairo BGRA surface
            arr = np.array(img)
            bgra = np.empty_like(arr)
            bgra[:, :, 0] = arr[:, :, 2]  # B
            bgra[:, :, 1] = arr[:, :, 1]  # G
            bgra[:, :, 2] = arr[:, :, 0]  # R
            bgra[:, :, 3] = arr[:, :, 3]  # A

            buf = bytearray(bgra.tobytes())
            surface = _cairo.ImageSurface.create_for_data(
                buf, _cairo.FORMAT_ARGB32, tile_w, tile_h,
            )
            surface._hapax_buf = buf  # type: ignore[attr-defined]
            with self._lock:
                self._surface = surface
                self._last_tile = (0, 0, tile_w, tile_h)
        except Exception:
            log.debug("HeroPreFxEffect: load/effect failed", exc_info=True)

    def draw(self, compositor: Any, cr: Any) -> None:
        """Blit the hero-effected snapshot at the hero tile position.

        Called from the pre_fx cairooverlay draw callback.
        """
        if not _hero_prefx_enabled():
            return

        target = self._resolve_hero(compositor)
        if target is None:
            return

        role, tile_x, tile_y, tile_w, tile_h = target

        self._try_load(role, tile_w, tile_h)
        self.tick()

        with self._lock:
            surface = self._surface

        if surface is None:
            return

        try:
            cr.save()
            cr.set_source_surface(surface, tile_x, tile_y)
            cr.paint_with_alpha(0.65)
            cr.restore()
        except Exception:
            log.debug("HeroPreFxEffect: draw failed", exc_info=True)

    @property
    def current_effect_name(self) -> str | None:
        if self._current_idx < 0:
            return None
        return _EFFECTS[self._current_idx][0]
