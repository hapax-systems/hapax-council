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
    AMPLITUDE_ALPHA_FLOOR,
    DEFAULT_LINE_WIDTH,
    LINE_WIDTH_AMPLITUDE_SCALE,
    M8OscilloscopeCairoSource,
    _amplitude_normalized,
    _amplitude_scaled_alpha,
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


# ── 2b. Amplitude-driven alpha modulation ──────────────────────────────


class TestAmplitudeNormalized:
    def test_empty_returns_zero(self) -> None:
        assert _amplitude_normalized(b"") == 0.0

    def test_flat_midline_is_silence(self) -> None:
        # All samples at 128 → no deviation from centre → amplitude 0.
        assert _amplitude_normalized(bytes([128] * 32)) == 0.0

    def test_full_swing_saturates_to_one(self) -> None:
        # Mix of 0 and 255 → peak deviation 128 → amplitude 1.0.
        assert _amplitude_normalized(bytes([0, 255, 128, 64, 192])) == pytest.approx(1.0)

    def test_partial_swing_proportional(self) -> None:
        # Peak deviation of 64 from 128 → 0.5.
        assert _amplitude_normalized(bytes([128, 192, 128, 64])) == pytest.approx(0.5)


class TestAmplitudeScaledAlpha:
    def test_zero_amplitude_yields_floor(self) -> None:
        assert _amplitude_scaled_alpha(0.75, 0.0, floor=0.5) == pytest.approx(0.375)

    def test_full_amplitude_yields_base(self) -> None:
        assert _amplitude_scaled_alpha(0.75, 1.0, floor=0.5) == pytest.approx(0.75)

    def test_clamps_above_one(self) -> None:
        # Out-of-band amplitude must not push alpha above the silence-fade
        # ceiling — defends the mtime-driven cap.
        assert _amplitude_scaled_alpha(0.75, 1.5, floor=0.5) == pytest.approx(0.75)

    def test_clamps_below_zero(self) -> None:
        assert _amplitude_scaled_alpha(0.75, -0.5, floor=0.5) == pytest.approx(0.375)

    def test_zero_base_alpha_stays_zero(self) -> None:
        # When silence-fade has finished, amplitude modulation cannot
        # resurrect the ward.
        assert _amplitude_scaled_alpha(0.0, 1.0, floor=0.5) == 0.0


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

    def test_loud_waveform_paints_with_thicker_stroke_than_silent(self, tmp_path: Path) -> None:
        # Silent: midline samples → amplitude 0 → line_width = base.
        silent_path = tmp_path / "silent_lw.bin"
        _write_ring(silent_path, samples=bytes([128] * 32))
        # Loud: full ±128 swing → amplitude 1 → bounded by AMPLITUDE_BURST_CLAMP
        # so line_width = base + clamp × scale.
        loud_path = tmp_path / "loud_lw.bin"
        _write_ring(loud_path, samples=bytes([0, 255] * 16))

        def _paint_line_width_steady_state(path: Path) -> float:
            source = M8OscilloscopeCairoSource(ring_path=path, amplitude_iir_alpha=1.0)
            cr = MagicMock()
            source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
            cr.set_line_width.assert_called_once()
            return float(cr.set_line_width.call_args.args[0])

        from agents.studio_compositor.m8_oscilloscope_source import AMPLITUDE_BURST_CLAMP

        silent_lw = _paint_line_width_steady_state(silent_path)
        loud_lw = _paint_line_width_steady_state(loud_path)
        assert silent_lw == pytest.approx(DEFAULT_LINE_WIDTH)
        # Per operator tightness directive 2026-05-06, full ±128 swing
        # gets bounded by AMPLITUDE_BURST_CLAMP (replaces the prior IIR
        # transient-whip prevention with instant-response clamping).
        assert loud_lw == pytest.approx(
            DEFAULT_LINE_WIDTH + AMPLITUDE_BURST_CLAMP * LINE_WIDTH_AMPLITUDE_SCALE
        )
        assert loud_lw > silent_lw

    def test_loud_waveform_paints_with_higher_alpha_than_silent(self, tmp_path: Path) -> None:
        # Silent waveform: all samples at the midline.
        silent_path = tmp_path / "silent.bin"
        _write_ring(silent_path, samples=bytes([128] * 32))
        # Loud waveform: full ±128 swing.
        loud_path = tmp_path / "loud.bin"
        _write_ring(loud_path, samples=bytes([0, 255] * 16))

        def _paint_alpha(path: Path) -> float:
            # Disable IIR (alpha=1.0) so this test pins the alpha-floor
            # endpoint behavior without the amplitude lag interfering.
            source = M8OscilloscopeCairoSource(ring_path=path, amplitude_iir_alpha=1.0)
            cr = MagicMock()
            source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
            # set_source_rgba(r, g, b, alpha) — last positional is alpha.
            cr.set_source_rgba.assert_called_once()
            args = cr.set_source_rgba.call_args.args
            return float(args[3])

        from agents.studio_compositor.m8_oscilloscope_source import AMPLITUDE_BURST_CLAMP

        silent_alpha = _paint_alpha(silent_path)
        loud_alpha = _paint_alpha(loud_path)
        # Both render (silence-fade is mtime-driven, ring is fresh), but
        # the loud waveform must read brighter than the silent midline.
        assert loud_alpha > silent_alpha
        # The silent waveform sits at the configured floor of the active
        # alpha — never invisible while the M8 is connected and sending.
        assert silent_alpha == pytest.approx(ACTIVE_ALPHA * AMPLITUDE_ALPHA_FLOOR)
        # Loud waveform: per operator tightness directive 2026-05-06 the
        # amplitude is bounded by AMPLITUDE_BURST_CLAMP so the alpha
        # interpolates between floor and ACTIVE_ALPHA at the clamp
        # endpoint — not all the way to ACTIVE_ALPHA on raw ±128 swings.
        expected_loud_alpha = ACTIVE_ALPHA * (
            AMPLITUDE_ALPHA_FLOOR + (1.0 - AMPLITUDE_ALPHA_FLOOR) * AMPLITUDE_BURST_CLAMP
        )
        assert loud_alpha == pytest.approx(expected_loud_alpha)


# ── 3b. Amplitude IIR smoothing ────────────────────────────────────────


class TestAmplitudeBoundedClamp:
    """The modulation amplitude is bounded by AMPLITUDE_BURST_CLAMP.

    Per operator directive 2026-05-06 (audio reactivity must be TIGHT),
    the prior one-pole IIR (#2651 α=0.3, ~3-5 frame lag on alpha + line-
    width modulations) was replaced with instant-response clamping. The
    waveform DRAW still reads raw samples (that surface IS the audio).
    Cross-ward consistency: same approach used in sierpinski_renderer.
    """

    def test_default_iir_alpha_is_one_for_tightness(self) -> None:
        from agents.studio_compositor.m8_oscilloscope_source import (
            AMPLITUDE_BURST_CLAMP,
            AMPLITUDE_IIR_ALPHA,
        )

        assert AMPLITUDE_IIR_ALPHA == 1.0
        assert 0.0 < AMPLITUDE_BURST_CLAMP <= 1.0

    def test_amplitude_responds_instantly_under_burst_clamp(self, tmp_path: Path) -> None:
        # Two ring fixtures: full-amplitude impulse and silent midline.
        from agents.studio_compositor.m8_oscilloscope_source import AMPLITUDE_BURST_CLAMP

        loud_path = tmp_path / "loud.bin"
        _write_ring(loud_path, samples=bytes([0, 255] * 16))
        silent_path = tmp_path / "silent.bin"
        _write_ring(silent_path, samples=bytes([128] * 32))

        source = M8OscilloscopeCairoSource(amplitude_iir_alpha=1.0)
        cr = MagicMock()

        # Frame 1 — loud impulse from rest. With α=1.0 the smoothed
        # envelope tracks the per-frame amplitude exactly, but the
        # amplitude is clamped at AMPLITUDE_BURST_CLAMP first so a raw
        # 1.0 (full ±128 swing) lands at clamp on frame 1.
        source._ring_path = loud_path
        source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
        assert source._amplitude_smoothed == pytest.approx(AMPLITUDE_BURST_CLAMP)

        # Frame 2 — loud sustained. Same instant-response endpoint.
        source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.033, state={})
        assert source._amplitude_smoothed == pytest.approx(AMPLITUDE_BURST_CLAMP)

        # Frame 3 — silence. Instant drop to 0 (no decay tail).
        source._ring_path = silent_path
        source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.066, state={})
        assert source._amplitude_smoothed == pytest.approx(0.0)

    def test_iir_alpha_one_with_burst_clamp(self, tmp_path: Path) -> None:
        # ``amplitude_iir_alpha=1.0`` is the instant-response default.
        # A raw 1.0 amplitude (full ±128 swing) is clamped to
        # AMPLITUDE_BURST_CLAMP before reaching _amplitude_smoothed.
        from agents.studio_compositor.m8_oscilloscope_source import AMPLITUDE_BURST_CLAMP

        loud_path = tmp_path / "loud_alpha1.bin"
        _write_ring(loud_path, samples=bytes([0, 255] * 16))
        source = M8OscilloscopeCairoSource(ring_path=loud_path, amplitude_iir_alpha=1.0)
        cr = MagicMock()
        source.render_content(cr, canvas_w=1280, canvas_h=128, t=0.0, state={})
        assert source._amplitude_smoothed == pytest.approx(AMPLITUDE_BURST_CLAMP)


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
