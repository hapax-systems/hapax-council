"""Real-Cairo integration smoke for the M8 oscilloscope ward.

Sister to ``test_m8_oscilloscope_source.py`` (mock-based unit tests).
This file pins the rendering against an ACTUAL ``cairo.ImageSurface``
context — a concrete pixel buffer the source must successfully draw
into. Mocks happily accept any ``move_to`` / ``line_to`` / ``stroke``
call, but a real Cairo context will reject NaN / inf / out-of-bounds
arguments and surface them as silent draw failures or, worse, segfaults
into the GStreamer thread.

The smoke runs the source through three representative scenarios:

* Empty / missing ring — must produce a clean canvas with zero strokes.
* Active fresh ring with full ±128 swing — must produce a non-empty
  pixel buffer (at least one non-zero pixel).
* Stale ring (silence-fade complete) — must produce a clean canvas.

Pure test addition; no source code touched. Sister to the deterministic
tests (mocks) and the property tests (Hypothesis). Each layer catches
a different class of breakage:

* mocks → call-shape regressions
* Hypothesis → math-invariant violations across the parameter space
* this file → real-Cairo integration breakage that mocks miss
"""

from __future__ import annotations

import os
import struct
import time
from pathlib import Path

import cairo
import pytest

from agents.studio_compositor.m8_oscilloscope_source import (
    M8OscilloscopeCairoSource,
)


def _write_ring(
    path: Path,
    *,
    frame_id: int = 1,
    color: int = 0xFF,
    samples: bytes = b"",
) -> None:
    sample_count = len(samples)
    header = struct.pack("<QBBH", frame_id, color, 0, sample_count)
    body = samples + b"\x00" * (480 - sample_count)
    path.write_bytes(header + body)


def _surface_has_visible_pixels(surface: cairo.ImageSurface) -> bool:
    """Return True if the surface has any non-zero pixel.

    ARGB32 surfaces are RGBA in little-endian byte order; checking for
    any non-zero byte is sufficient — a fully-transparent / fully-zeroed
    canvas would have all zeros.
    """
    return any(b != 0 for b in bytes(surface.get_data()))


@pytest.fixture
def canvas() -> tuple[cairo.ImageSurface, cairo.Context]:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1280, 128)
    cr = cairo.Context(surface)
    return surface, cr


def test_missing_ring_leaves_canvas_clean(
    canvas: tuple[cairo.ImageSurface, cairo.Context], tmp_path: Path
) -> None:
    surface, cr = canvas
    source = M8OscilloscopeCairoSource(ring_path=tmp_path / "missing.bin")
    source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
    assert not _surface_has_visible_pixels(surface), (
        "missing ring file should produce no visible pixels"
    )


def test_loud_fresh_ring_paints_visible_pixels(
    canvas: tuple[cairo.ImageSurface, cairo.Context], tmp_path: Path
) -> None:
    surface, cr = canvas
    ring = tmp_path / "loud.bin"
    # Full ±128 swing across all 480 samples for an unmistakable waveform.
    _write_ring(ring, samples=bytes([0, 255] * 240))
    source = M8OscilloscopeCairoSource(ring_path=ring)
    source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
    assert _surface_has_visible_pixels(surface), (
        "fresh full-amplitude ring should paint visible pixels"
    )


def test_stale_ring_leaves_canvas_clean(
    canvas: tuple[cairo.ImageSurface, cairo.Context], tmp_path: Path
) -> None:
    surface, cr = canvas
    ring = tmp_path / "stale.bin"
    _write_ring(ring, samples=bytes([0, 255] * 240))
    # Backdate mtime past the silence-fade window so the source skips
    # rendering entirely (alpha=0).
    old_ts = time.time() - 10.0
    os.utime(ring, (old_ts, old_ts))
    source = M8OscilloscopeCairoSource(
        ring_path=ring,
        silence_fade_after_s=1.0,
        silence_fade_duration_s=0.5,
    )
    source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
    assert not _surface_has_visible_pixels(surface), (
        "stale ring (post silence-fade) should leave canvas clean"
    )


def test_default_construction_renders_without_raising(
    canvas: tuple[cairo.ImageSurface, cairo.Context],
) -> None:
    """Constructed with NO arguments + the production default ring path
    must not raise into the compositor render thread, even if the SHM
    file is absent at test time (CI machines have no real M8)."""
    surface, cr = canvas
    source = M8OscilloscopeCairoSource()
    # If the default ring exists on the runner (rare), this still must
    # not raise. If it doesn't exist (typical), the source returns early.
    source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
