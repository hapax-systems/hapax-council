"""Tests for the shared ImageLoader.

Phase 3d of the compositor unification epic — the single source of
truth for PNG/JPEG → Cairo surface decode.

PNG decode uses cairo.ImageSurface.create_from_png which has no GTK
dependency, so these tests run in CI containers without the gi
typelibs. JPEG tests are skipped if PIL or numpy are unavailable.
"""

from __future__ import annotations

import threading
from pathlib import Path

import cairo
import pytest

from agents.studio_compositor.image_loader import (
    ImageLoader,
    get_image_loader,
    reset_image_loader_for_tests,
)


def _make_png(path: Path, width: int = 8, height: int = 8) -> None:
    """Write a tiny ARGB PNG to ``path`` for use in tests.

    Cairo's create_from_png is the test target so we round-trip
    through cairo's own PNG writer to avoid pulling in PIL just for
    fixture generation.
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(surface)
    # Solid red so we can sanity-check pixels in test_load_returns_pixels.
    cr.set_source_rgba(1.0, 0.0, 0.0, 1.0)
    cr.rectangle(0, 0, width, height)
    cr.fill()
    surface.write_to_png(str(path))


def _has_pil() -> bool:
    try:
        import numpy  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# PNG decode (no GTK dependency)
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_none(tmp_path: Path):
    loader = ImageLoader()
    assert loader.load(tmp_path / "does-not-exist.png") is None


def test_load_unsupported_format_returns_none(tmp_path: Path):
    loader = ImageLoader()
    target = tmp_path / "fake.bmp"
    target.write_bytes(b"BMP")
    assert loader.load(target) is None


def test_load_png_returns_image_surface(tmp_path: Path):
    png_path = tmp_path / "tiny.png"
    _make_png(png_path, width=12, height=8)
    loader = ImageLoader()
    surface = loader.load(png_path)
    assert isinstance(surface, cairo.ImageSurface)
    assert surface.get_width() == 12
    assert surface.get_height() == 8


def test_load_png_pixels_match_input(tmp_path: Path):
    png_path = tmp_path / "red.png"
    _make_png(png_path)
    loader = ImageLoader()
    surface = loader.load(png_path)
    assert surface is not None
    surface.flush()
    data = bytes(surface.get_data())
    # ARGB32 in little-endian byte order is BGRA. Our solid-red fill
    # gives B=0, G=0, R=255, A=255 → check the first pixel.
    assert data[0] == 0
    assert data[1] == 0
    assert data[2] == 255
    assert data[3] == 255


def test_load_caches_subsequent_calls(tmp_path: Path):
    """Loading the same path twice should not decode twice."""
    png_path = tmp_path / "cached.png"
    _make_png(png_path)
    loader = ImageLoader()
    s1 = loader.load(png_path)
    s2 = loader.load(png_path)
    assert s1 is not None
    # Cached entry returns the *same* surface object on the second call.
    assert s1 is s2
    assert loader.cache_size() == 1


def test_load_invalidates_on_mtime_change(tmp_path: Path):
    """Touching the file should invalidate the cache and re-decode."""
    png_path = tmp_path / "mtime.png"
    _make_png(png_path)
    loader = ImageLoader()
    s1 = loader.load(png_path)
    assert s1 is not None
    # Bump mtime by a known amount; loader compares stat().st_mtime
    # which is float seconds.
    new_mtime = png_path.stat().st_mtime + 5.0
    import os

    os.utime(png_path, (new_mtime, new_mtime))
    s2 = loader.load(png_path)
    assert s2 is not None
    assert s2 is not s1  # different surface object → re-decoded


def test_load_distinct_paths_distinct_entries(tmp_path: Path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    _make_png(a)
    _make_png(b)
    loader = ImageLoader()
    sa = loader.load(a)
    sb = loader.load(b)
    assert sa is not None
    assert sb is not None
    assert sa is not sb
    assert loader.cache_size() == 2


def test_invalidate_drops_entry(tmp_path: Path):
    png_path = tmp_path / "drop.png"
    _make_png(png_path)
    loader = ImageLoader()
    loader.load(png_path)
    assert loader.cache_size() == 1
    loader.invalidate(png_path)
    assert loader.cache_size() == 0


def test_invalidate_unknown_path_is_noop(tmp_path: Path):
    loader = ImageLoader()
    # Should not raise.
    loader.invalidate(tmp_path / "never-loaded.png")
    assert loader.cache_size() == 0


# ---------------------------------------------------------------------------
# Singleton behaviour
# ---------------------------------------------------------------------------


def test_get_image_loader_returns_singleton():
    reset_image_loader_for_tests()
    a = get_image_loader()
    b = get_image_loader()
    assert a is b


def test_reset_image_loader_returns_fresh_instance():
    a = get_image_loader()
    reset_image_loader_for_tests()
    b = get_image_loader()
    assert a is not b


# ---------------------------------------------------------------------------
# Thread safety smoke
# ---------------------------------------------------------------------------


def test_concurrent_load_is_safe(tmp_path: Path):
    png_path = tmp_path / "concurrent.png"
    _make_png(png_path)
    loader = ImageLoader()
    results: list[cairo.ImageSurface | None] = []
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            results.append(loader.load(png_path))
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)
    assert not errors
    # All workers got a non-None surface.
    assert all(r is not None for r in results)
    # The cache holds exactly one entry regardless of how many
    # threads called load().
    assert loader.cache_size() == 1


# ---------------------------------------------------------------------------
# JPEG decode (skipped if PIL/numpy missing)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _has_pil(), reason="PIL/numpy not installed")
def test_load_jpeg_via_pil(tmp_path: Path):
    """JPEG decode goes through the PIL → premultiplied BGRA path.

    We generate the JPEG via PIL itself rather than cairo (which
    doesn't write JPEG) so the test is self-contained.
    """
    from PIL import Image

    jpeg_path = tmp_path / "color.jpg"
    img = Image.new("RGB", (16, 16), color=(128, 64, 200))
    img.save(jpeg_path, format="JPEG", quality=95)

    loader = ImageLoader()
    surface = loader.load(jpeg_path)
    assert isinstance(surface, cairo.ImageSurface)
    assert surface.get_width() == 16
    assert surface.get_height() == 16
    surface.flush()
    data = bytes(surface.get_data())
    # JPEG is lossy so we can't check exact pixel values; just verify
    # the surface holds non-zero data and the right number of bytes.
    assert len(data) == 16 * 16 * 4
    assert any(b != 0 for b in data)
