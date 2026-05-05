"""Tests for ``agents.studio_compositor.m8_oscilloscope_source``.

Cc-task ``m8-oscilloscope-reactive-surface`` (WSJF 3.25). Pins:

* SHM ring round-trip: a binary file shaped like the carry-fork's
  ``shm_sink_publish_oscilloscope`` output decodes back to the same
  ``(frame_id, color, samples)`` tuple — and the source falls back
  cleanly when the ring is absent / truncated / malformed.
* Silence fade: mtime-age-driven alpha curve has the right shape at
  active / fading / fully-faded ages.
* Cairo render: when given a non-empty ring + fresh mtime, the
  renderer makes the expected ``move_to`` + per-sample ``line_to``
  calls and a single ``stroke()`` (single-path performance pin from
  the task notes).
* Affordance + cairo registry registration: ``studio.m8_oscilloscope_ward``
  is in ``ALL_AFFORDANCES`` and ``M8OscilloscopeCairoSource`` is
  listed in the cairo source registry.
"""

from __future__ import annotations

import struct
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agents.studio_compositor import m8_oscilloscope_source as mod
from agents.studio_compositor.m8_oscilloscope_source import (
    ACTIVE_ALPHA,
    M8OscilloscopeCairoSource,
    _read_ring,
    _silence_alpha,
)


def _write_ring(
    path: Path,
    *,
    frame_id: int = 1,
    color: int = 0xFF,
    samples: bytes = b"",
) -> None:
    """Write a fixture ring file matching shm_sink_publish_oscilloscope."""
    sample_count = len(samples)
    header = struct.pack("<QBBH", frame_id, color, 0, sample_count)
    body = samples + b"\x00" * (480 - sample_count)
    path.write_bytes(header + body)


# ── 1. Ring file round-trip ─────────────────────────────────────────────


class TestReadRing:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert _read_ring(tmp_path / "missing.bin") is None

    def test_empty_file_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.bin"
        path.write_bytes(b"")
        assert _read_ring(path) is None

    def test_truncated_header_returns_none(self, tmp_path: Path) -> None:
        path = tmp_path / "trunc.bin"
        path.write_bytes(b"\x01\x02\x03")
        assert _read_ring(path) is None

    def test_round_trip_recovers_frame_color_samples(self, tmp_path: Path) -> None:
        path = tmp_path / "osc.bin"
        samples = bytes(range(0, 64))
        _write_ring(path, frame_id=42, color=0x80, samples=samples)
        result = _read_ring(path)
        assert result is not None
        frame_id, color, recovered, mtime = result
        assert frame_id == 42
        assert color == 0x80
        assert recovered == samples
        assert mtime > 0

    def test_sample_count_clamped_to_max(self, tmp_path: Path) -> None:
        # Spoof a sample_count larger than the buffer's actual capacity;
        # _read_ring must clamp to 480 so a malformed header cannot
        # cause an out-of-bounds slice.
        path = tmp_path / "spoofed.bin"
        header = struct.pack("<QBBH", 1, 0, 0, 9999)  # claims 9999 samples
        path.write_bytes(header + b"\xaa" * 480)
        result = _read_ring(path)
        assert result is not None
        _, _, samples, _ = result
        assert len(samples) == 480


# ── 2. Silence fade curve ───────────────────────────────────────────────


class TestSilenceAlpha:
    @pytest.mark.parametrize(
        ("age", "expected"),
        [
            (0.0, ACTIVE_ALPHA),
            (0.5, ACTIVE_ALPHA),  # under fade_after, full alpha
            (1.0, ACTIVE_ALPHA),  # at fade_after threshold, still active
            (1.25, ACTIVE_ALPHA * 0.5),  # halfway through fade
            (1.5, 0.0),  # fade complete
            (10.0, 0.0),  # long-silent, fully faded
        ],
    )
    def test_curve_shape(self, age: float, expected: float) -> None:
        now = 100.0
        mtime = now - age
        alpha = _silence_alpha(
            mtime,
            now,
            fade_after_s=1.0,
            fade_duration_s=0.5,
            active_alpha=ACTIVE_ALPHA,
        )
        assert alpha == pytest.approx(expected, abs=1e-6)


# ── 3. Cairo render path ────────────────────────────────────────────────


class TestRenderContent:
    def test_no_ring_file_emits_no_drawing(self, tmp_path: Path) -> None:
        source = M8OscilloscopeCairoSource(ring_path=tmp_path / "missing.bin")
        cr = MagicMock()
        source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
        # No ring → silent skip, no Cairo calls beyond defensive helpers.
        cr.move_to.assert_not_called()
        cr.line_to.assert_not_called()
        cr.stroke.assert_not_called()

    def test_silent_ring_emits_no_drawing(self, tmp_path: Path) -> None:
        path = tmp_path / "stale.bin"
        _write_ring(path, samples=bytes(range(16)))
        # Backdate mtime so silence_alpha returns 0.
        import os

        old_ts = time.time() - 10.0
        os.utime(path, (old_ts, old_ts))
        source = M8OscilloscopeCairoSource(
            ring_path=path,
            silence_fade_after_s=1.0,
            silence_fade_duration_s=0.5,
        )
        cr = MagicMock()
        source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
        cr.stroke.assert_not_called()

    def test_active_ring_strokes_single_path(self, tmp_path: Path) -> None:
        path = tmp_path / "active.bin"
        samples = bytes([64, 96, 128, 160, 192])  # 5 samples
        _write_ring(path, samples=samples)
        source = M8OscilloscopeCairoSource(ring_path=path)
        cr = MagicMock()
        source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
        # First sample uses move_to; remaining four use line_to.
        assert cr.move_to.call_count == 1
        assert cr.line_to.call_count == 4
        # Single stroke at the end — no per-pixel stroke calls.
        assert cr.stroke.call_count == 1

    def test_render_does_not_raise_on_malformed_ring(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.bin"
        path.write_bytes(b"\x01\x02")  # too short for header
        source = M8OscilloscopeCairoSource(ring_path=path)
        cr = MagicMock()
        # Must not raise into the compositor's render thread.
        source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})


# ── 4. Affordance + cairo registry registration ─────────────────────────


class TestRegistration:
    def test_affordance_registered(self) -> None:
        from shared.affordance_registry import ALL_AFFORDANCES

        names = {cap.name for cap in ALL_AFFORDANCES}
        assert "studio.m8_oscilloscope_ward" in names

    def test_affordance_consent_not_required(self) -> None:
        # Waveform samples carry only post-mix audio amplitude — no
        # PII — so the affordance must not require an active consent
        # contract per the task spec.
        from shared.affordance_registry import ALL_AFFORDANCES

        cap = next(c for c in ALL_AFFORDANCES if c.name == "studio.m8_oscilloscope_ward")
        assert cap.operational.consent_required is False
        assert cap.operational.medium == "visual"

    def test_cairo_source_registered(self) -> None:
        from agents.studio_compositor.cairo_sources import _CAIRO_SOURCE_CLASSES

        assert "M8OscilloscopeCairoSource" in _CAIRO_SOURCE_CLASSES
        assert _CAIRO_SOURCE_CLASSES["M8OscilloscopeCairoSource"] is M8OscilloscopeCairoSource


# ── 5. Module constants pinned (carry-fork wire format) ──────────────────


class TestWireFormat:
    """Pin the binary wire-format constants so a future refactor cannot
    silently break the carry-fork ↔ Cairo source contract."""

    def test_header_size_matches_carry_fork(self) -> None:
        assert mod._HEADER_SIZE == 12

    def test_max_samples_matches_carry_fork(self) -> None:
        assert mod._MAX_SAMPLES == 480

    def test_total_file_size(self) -> None:
        assert mod._FILE_SIZE == 12 + 480
