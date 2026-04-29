"""Tests for the ``video_attention`` SHM publisher (GEAL Phase 0 Task 0.3).

Per spec §5.1, the Sierpinski source publishes a single f32 scalar to
``/dev/shm/hapax-compositor/video-attention.f32`` every tick. GEAL reads
this to pull back its activation budget when the YT video rects are
attention-dominant — GEAL never fills an empty rect, and never competes
with an active one.

Formula::

    video_attention = max(slot_opacity[0..N-1]) * frame_freshness
    frame_freshness = 1.0 if age < 2.0s else exponential decay (τ = 2s)

Slots with no cached frame surface contribute 0.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from agents.studio_compositor.sierpinski_renderer import (
    VIDEO_ATTENTION_PATH,
    SierpinskiCairoSource,
)

if TYPE_CHECKING:
    import cairo

NOW = 1_776_000_000.0


@pytest.fixture()
def renderer() -> SierpinskiCairoSource:
    return SierpinskiCairoSource()


@pytest.fixture()
def attention_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the publish path to a tmp file so tests don't touch /dev/shm."""
    path = tmp_path / "video-attention.f32"
    monkeypatch.setattr("agents.studio_compositor.sierpinski_renderer.VIDEO_ATTENTION_PATH", path)
    return path


def _read_f32(path: Path) -> float:
    data = path.read_bytes()
    assert len(data) == 4, f"expected 4 bytes, got {len(data)}"
    return struct.unpack("<f", data)[0]


def _cached_frame_surface() -> cairo.ImageSurface:
    """Return a cached-frame sentinel; attention logic only checks non-None."""
    return cast("cairo.ImageSurface", object())


def test_video_attention_default_is_zero(
    renderer: SierpinskiCairoSource, attention_path: Path
) -> None:
    """No frames loaded → 0.0."""
    renderer._publish_video_attention()
    assert attention_path.exists()
    assert _read_f32(attention_path) == pytest.approx(0.0)


def test_video_attention_active_slot(renderer: SierpinskiCairoSource, attention_path: Path) -> None:
    """Fresh frame loaded in active slot → equals active-slot opacity (0.9)."""
    # Simulate a cached frame surface with a fresh mtime.
    fake_surface = _cached_frame_surface()
    renderer._frame_surfaces[0] = fake_surface
    renderer._frame_mtimes[0] = NOW  # fresh
    renderer._active_slot = 0

    renderer._publish_video_attention(now=NOW)
    value = _read_f32(attention_path)
    # Active slot opacity is 0.9 (FEATURED_FALLBACK_OPACITY); freshness = 1.0.
    assert value == pytest.approx(0.9, abs=0.01)


def test_video_attention_featured_slot_maxes_out(
    renderer: SierpinskiCairoSource, attention_path: Path
) -> None:
    """Featured slot with fresh frame → ~1.0."""
    fake_surface = _cached_frame_surface()
    now = NOW
    renderer._frame_surfaces[0] = fake_surface
    renderer._frame_mtimes[0] = now
    renderer._active_slot = 0
    # Simulate a featured-slot write (Phase 2 yt-feature).
    renderer._featured_slot_id = 0
    renderer._featured_ts = now
    renderer._featured_level = 1.0

    renderer._publish_video_attention(now=now)
    value = _read_f32(attention_path)
    assert value == pytest.approx(1.0, abs=0.01)


def test_video_attention_decays_after_2s(
    renderer: SierpinskiCairoSource, attention_path: Path
) -> None:
    """Stale frame (mtime age > 2s) → freshness < 1.0 (exponential decay)."""
    fake_surface = _cached_frame_surface()
    renderer._frame_surfaces[0] = fake_surface
    renderer._frame_mtimes[0] = NOW - 4.0  # 4s old
    renderer._active_slot = 0

    renderer._publish_video_attention(now=NOW)
    value = _read_f32(attention_path)
    # age = 4s → 2s past cutoff → freshness = exp(-2/2) = 0.368
    # final = 0.9 * 0.368 ≈ 0.33
    assert 0.0 < value < 0.9
    assert value == pytest.approx(0.9 * 2.718281828**-1.0, abs=0.02)


def test_video_attention_picks_max_across_slots(
    renderer: SierpinskiCairoSource, attention_path: Path
) -> None:
    """Max across all slots, not sum — one hot slot dominates."""
    fake_surface = _cached_frame_surface()
    now = NOW
    # slot 0: stale, idle
    renderer._frame_surfaces[0] = fake_surface
    renderer._frame_mtimes[0] = now - 10.0
    # slot 1: fresh, active
    renderer._frame_surfaces[1] = fake_surface
    renderer._frame_mtimes[1] = now
    renderer._active_slot = 1

    renderer._publish_video_attention(now=now)
    value = _read_f32(attention_path)
    # Slot 1 dominates: opacity 0.9 * freshness 1.0 = 0.9
    assert value == pytest.approx(0.9, abs=0.01)


def test_video_attention_path_is_canonical() -> None:
    """Publish path is the canonical SHM location from spec §5.1."""
    assert Path("/dev/shm/hapax-compositor/video-attention.f32") == VIDEO_ATTENTION_PATH
