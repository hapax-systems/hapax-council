"""Image file loader — single source of truth for PNG/JPEG → Cairo surface.

Phase 3d of the compositor unification epic. Replaces the duplicate
``cairo.ImageSurface.create_from_png`` + manual PIL decode paths in
:mod:`fx_chain`, :mod:`overlay_zones`, and :mod:`token_pole`. Cached
by (absolute path, mtime) so repeated loads of the same image cost
nothing.

The cache is process-wide via :func:`get_image_loader`. The dataclass
that backs each entry is private; callers receive only the
:class:`cairo.ImageSurface` they asked for.

Format support:

* **PNG** — native ``cairo.ImageSurface.create_from_png``
* **JPEG** — PIL → RGBA → premultiplied BGRA → cairo.ImageSurface.
  The premultiply pass is necessary because Cairo's ``FORMAT_ARGB32``
  expects premultiplied alpha. Without it, the cover image renders
  with black halos at translucent edges.

Other formats fall through to a warning log and a None return —
callers can fall back to per-class decode paths if needed.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import cairo

log = logging.getLogger(__name__)

_PNG_SUFFIXES = frozenset({".png"})
_JPEG_SUFFIXES = frozenset({".jpg", ".jpeg"})


@dataclass
class _CacheEntry:
    surface: cairo.ImageSurface
    mtime: float


class ImageLoader:
    """Process-wide image cache. Thread-safe; one decode per (path, mtime).

    The cache key is the resolved absolute path. mtime invalidation is
    automatic on every ``load`` call — pass the same path after touching
    the file and the next load decodes again. Failed decodes are not
    cached: a transient OSError doesn't poison the entry.
    """

    def __init__(self) -> None:
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.Lock()

    def load(self, path: str | Path) -> cairo.ImageSurface | None:
        """Return the cached or freshly-decoded surface for ``path``.

        Returns ``None`` if the file doesn't exist, the format is
        unsupported, or decode raises. The decode itself runs outside
        the lock so concurrent loads of *different* paths don't
        serialize. Concurrent loads of the *same* path may briefly
        race the lock-free decode but the cache write is atomic.
        """
        try:
            resolved = Path(path).expanduser().resolve()
        except (OSError, ValueError):
            return None
        if not resolved.is_file():
            return None
        try:
            mtime = resolved.stat().st_mtime
        except OSError:
            return None

        key = str(resolved)
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and entry.mtime == mtime:
                return entry.surface

        surface = self._decode(resolved)
        if surface is None:
            return None

        with self._lock:
            self._cache[key] = _CacheEntry(surface=surface, mtime=mtime)
        return surface

    def invalidate(self, path: str | Path) -> None:
        """Drop the cached surface for ``path`` if any.

        Useful when the caller knows the file changed but the mtime
        hasn't advanced (rare; e.g. atomic-rename of a same-second
        rewrite). Lookups for unrelated paths are unaffected.
        """
        try:
            key = str(Path(path).expanduser().resolve())
        except (OSError, ValueError):
            return
        with self._lock:
            self._cache.pop(key, None)

    def cache_size(self) -> int:
        """Return the number of cached entries (for tests/observability)."""
        with self._lock:
            return len(self._cache)

    def _decode(self, path: Path) -> cairo.ImageSurface | None:
        suffix = path.suffix.lower()
        try:
            if suffix in _PNG_SUFFIXES:
                return cairo.ImageSurface.create_from_png(str(path))
            if suffix in _JPEG_SUFFIXES:
                return self._decode_jpeg(path)
            log.warning("ImageLoader: unsupported format %s", path)
            return None
        except Exception:
            log.exception("ImageLoader: failed to decode %s", path)
            return None

    @staticmethod
    def _decode_jpeg(path: Path) -> cairo.ImageSurface | None:
        """Decode JPEG via PIL into a Cairo ARGB32 surface.

        PIL returns RGBA in non-premultiplied form. Cairo's ARGB32
        format expects premultiplied BGRA, so we swap channels and
        multiply RGB by alpha/255 in one numpy pass before constructing
        the surface via ``create_for_data``. The numpy buffer is kept
        alive by the closure on the returned surface (Cairo holds a
        reference to the underlying memoryview).
        """
        from PIL import Image

        img = Image.open(path).convert("RGBA")
        w, h = img.size
        import numpy as np

        rgba = np.asarray(img, dtype=np.uint8)
        # Swap RGB→BGR and copy so we own the buffer.
        bgra = rgba[..., [2, 1, 0, 3]].copy()
        # Premultiply RGB by alpha.
        alpha = bgra[..., 3:4].astype(np.float32) * (1.0 / 255.0)
        bgra[..., :3] = (bgra[..., :3].astype(np.float32) * alpha).astype(np.uint8)
        # create_for_data needs a writable bytes-like buffer; the numpy
        # array satisfies that and Cairo holds a reference to the memory
        # via the surface's lifetime.
        return cairo.ImageSurface.create_for_data(
            memoryview(bgra),  # type: ignore[arg-type]
            cairo.FORMAT_ARGB32,
            w,
            h,
            w * 4,
        )


# ---------------------------------------------------------------------------
# Process-wide singleton
# ---------------------------------------------------------------------------


_LOADER: ImageLoader | None = None
_LOADER_LOCK = threading.Lock()


def get_image_loader() -> ImageLoader:
    """Return the process-wide :class:`ImageLoader` singleton.

    Lazy initialization under a lock so the first call from multiple
    threads doesn't race two distinct loaders into existence.
    """
    global _LOADER
    if _LOADER is None:
        with _LOADER_LOCK:
            if _LOADER is None:
                _LOADER = ImageLoader()
    return _LOADER


def reset_image_loader_for_tests() -> None:
    """Drop the singleton so a test can start with an empty cache.

    Tests must call this in setup if they care about decode counts.
    """
    global _LOADER
    with _LOADER_LOCK:
        _LOADER = None
