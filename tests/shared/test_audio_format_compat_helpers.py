"""Tests for shared.audio_format_compat_helpers (cc-task jr-tier1 Phase 0).

Pin sine generation, RMS computation, format conversion (i16↔f32), linear
resample, and the 3 assertion helpers (rms-within-attenuation,
resample-not-silenced, format-not-silenced).

All tests run on bytes-only synthetic buffers — no PipeWire daemon, no
audio hardware. Phase 1 fixture spawns real PipeWire nodes.
"""

from __future__ import annotations

import math

import pytest

from shared.audio_format_compat_helpers import (
    DEFAULT_BIT_DEPTH,
    DEFAULT_SAMPLE_RATE_HZ,
    SILENCE_FLOOR_DBFS,
    assert_format_conversion_did_not_silence,
    assert_resample_did_not_silence,
    assert_rms_within_attenuation,
    float32_to_int16,
    generate_sine_int16,
    int16_to_float32,
    linear_resample_int16,
    rms_dbfs_int16,
)


class TestPinnedConstants:
    def test_default_sample_rate(self) -> None:
        assert DEFAULT_SAMPLE_RATE_HZ == 48000

    def test_default_bit_depth(self) -> None:
        assert DEFAULT_BIT_DEPTH == 16

    def test_silence_floor_matches_health_threshold(self) -> None:
        """Pin alignment with BroadcastAudioHealthThresholds.rms_dbfs_floor."""
        from shared.broadcast_audio_health import BroadcastAudioHealthThresholds

        assert BroadcastAudioHealthThresholds().rms_dbfs_floor == SILENCE_FLOOR_DBFS


class TestGenerateSineInt16:
    def test_produces_nonempty_bytes(self) -> None:
        pcm = generate_sine_int16(440.0, 0.1)
        assert len(pcm) > 0

    def test_byte_count_matches_duration_and_rate(self) -> None:
        """100ms at 48kHz, int16 (2 bytes/sample) = 9600 bytes."""
        pcm = generate_sine_int16(440.0, 0.1)
        assert len(pcm) == int(0.1 * 48000) * 2

    def test_rms_at_amplitude_half_is_minus_9_dbfs(self) -> None:
        """Sine at amplitude=0.5 has RMS = 0.5/sqrt(2) ≈ 0.354 → -9 dBFS."""
        pcm = generate_sine_int16(440.0, 0.5, amplitude=0.5)
        rms = rms_dbfs_int16(pcm)
        assert -10.0 <= rms <= -8.0, f"expected ~-9 dBFS, got {rms}"

    def test_rms_at_full_scale_is_minus_3_dbfs(self) -> None:
        """Sine at amplitude=1.0 has RMS = 1/sqrt(2) ≈ 0.707 → -3 dBFS."""
        pcm = generate_sine_int16(440.0, 0.5, amplitude=1.0)
        rms = rms_dbfs_int16(pcm)
        assert -4.0 <= rms <= -2.0, f"expected ~-3 dBFS, got {rms}"

    def test_zero_frequency_rejected(self) -> None:
        with pytest.raises(ValueError, match="frequency_hz must be"):
            generate_sine_int16(0.0, 0.1)

    def test_negative_duration_rejected(self) -> None:
        with pytest.raises(ValueError, match="duration_s must be"):
            generate_sine_int16(440.0, -1.0)

    def test_zero_sample_rate_rejected(self) -> None:
        with pytest.raises(ValueError, match="sample_rate_hz must be"):
            generate_sine_int16(440.0, 0.1, sample_rate_hz=0)

    def test_amplitude_out_of_range_rejected(self) -> None:
        with pytest.raises(ValueError, match="amplitude must be"):
            generate_sine_int16(440.0, 0.1, amplitude=1.5)
        with pytest.raises(ValueError, match="amplitude must be"):
            generate_sine_int16(440.0, 0.1, amplitude=-0.1)


class TestRmsDbfsInt16:
    def test_empty_buffer_is_neg_inf(self) -> None:
        assert rms_dbfs_int16(b"") == float("-inf")

    def test_silence_buffer_is_neg_inf(self) -> None:
        # 1000 samples of zero → RMS = 0 → dBFS = -inf
        zeros = b"\x00\x00" * 1000
        assert rms_dbfs_int16(zeros) == float("-inf")

    def test_sine_amplitude_half_close_to_minus_9_dbfs(self) -> None:
        pcm = generate_sine_int16(440.0, 0.5, amplitude=0.5)
        rms = rms_dbfs_int16(pcm)
        assert rms == pytest.approx(-9.0, abs=1.0)


class TestInt16Float32RoundTrip:
    def test_round_trip_preserves_signal_within_quantisation(self) -> None:
        original = generate_sine_int16(440.0, 0.1, amplitude=0.5)
        as_float = int16_to_float32(original)
        back_to_int = float32_to_int16(as_float)
        # Quantisation noise is ≤ 1 bit; RMS should match within 0.1 dB.
        rms_original = rms_dbfs_int16(original)
        rms_round_trip = rms_dbfs_int16(back_to_int)
        assert abs(rms_original - rms_round_trip) < 0.1

    def test_int16_to_float32_byte_count_doubles(self) -> None:
        """f32 is 4 bytes/sample vs i16 2 bytes/sample."""
        i16 = generate_sine_int16(440.0, 0.1)
        f32 = int16_to_float32(i16)
        assert len(f32) == len(i16) * 2

    def test_float32_clamps_out_of_range_to_unity(self) -> None:
        """f32 sample > 1.0 should clamp; not produce overflow int16."""
        import array

        floats = array.array("f", [2.0, -2.0])
        out = float32_to_int16(floats.tobytes())
        samples = array.array("h")
        samples.frombytes(out)
        assert samples[0] == 32767  # +1.0 → max int16
        assert samples[1] == -32767  # -1.0 → min int16 (symmetric)


class TestLinearResampleInt16:
    def test_no_op_when_rates_equal(self) -> None:
        original = generate_sine_int16(440.0, 0.1, sample_rate_hz=48000)
        resampled = linear_resample_int16(original, 48000, 48000)
        assert resampled == original

    def test_44k_to_48k_increases_sample_count(self) -> None:
        original = generate_sine_int16(440.0, 0.1, sample_rate_hz=44100)
        resampled = linear_resample_int16(original, 44100, 48000)
        # Output should be ≈ 48000/44100 × input length.
        ratio = len(resampled) / len(original)
        assert ratio == pytest.approx(48000 / 44100, abs=0.01)

    def test_48k_to_24k_halves_sample_count(self) -> None:
        original = generate_sine_int16(440.0, 0.1, sample_rate_hz=48000)
        resampled = linear_resample_int16(original, 48000, 24000)
        ratio = len(resampled) / len(original)
        assert ratio == pytest.approx(0.5, abs=0.01)

    def test_resample_preserves_signal_above_silence(self) -> None:
        """The whole point of the assertion: rate mismatch → resample, not silence."""
        original = generate_sine_int16(440.0, 0.5, sample_rate_hz=44100, amplitude=0.5)
        resampled = linear_resample_int16(original, 44100, 48000)
        rms_orig = rms_dbfs_int16(original)
        rms_resampled = rms_dbfs_int16(resampled)
        # Linear interpolation may attenuate slightly but stays well above silence.
        assert rms_resampled > SILENCE_FLOOR_DBFS
        assert abs(rms_orig - rms_resampled) < 3.0  # within 3 dB

    def test_zero_rate_rejected(self) -> None:
        with pytest.raises(ValueError, match="sample rates"):
            linear_resample_int16(b"\x00\x01", 0, 48000)

    def test_empty_buffer_returns_empty(self) -> None:
        assert linear_resample_int16(b"", 44100, 48000) == b""


class TestAssertRmsWithinAttenuation:
    def test_no_attenuation_within_tolerance(self) -> None:
        pcm = generate_sine_int16(440.0, 0.5, amplitude=0.5)
        assert_rms_within_attenuation(
            input_pcm=pcm,
            output_pcm=pcm,  # passthrough; same RMS
            declared_attenuation_db=0.0,
        )

    def test_zero_attenuation_with_quiet_output_fails(self) -> None:
        loud = generate_sine_int16(440.0, 0.5, amplitude=0.5)
        quiet = generate_sine_int16(440.0, 0.5, amplitude=0.05)
        with pytest.raises(AssertionError, match="not within"):
            assert_rms_within_attenuation(
                input_pcm=loud,
                output_pcm=quiet,
                declared_attenuation_db=0.0,
            )

    def test_declared_6db_attenuation_passes(self) -> None:
        """Input at amplitude 0.5; output at amplitude 0.25 = -6 dB."""
        loud = generate_sine_int16(440.0, 0.5, amplitude=0.5)
        attenuated = generate_sine_int16(440.0, 0.5, amplitude=0.25)
        assert_rms_within_attenuation(
            input_pcm=loud,
            output_pcm=attenuated,
            declared_attenuation_db=6.0,
        )

    def test_silent_input_fails(self) -> None:
        zeros = b"\x00\x00" * 1000
        with pytest.raises(AssertionError, match="silent"):
            assert_rms_within_attenuation(
                input_pcm=zeros,
                output_pcm=zeros,
                declared_attenuation_db=0.0,
            )

    def test_custom_tolerance_band(self) -> None:
        pcm = generate_sine_int16(440.0, 0.5, amplitude=0.5)
        # 3 dB out of declared with ±5 dB tolerance — passes.
        attenuated = generate_sine_int16(440.0, 0.5, amplitude=0.5 / math.sqrt(2))
        assert_rms_within_attenuation(
            input_pcm=pcm,
            output_pcm=attenuated,
            declared_attenuation_db=0.0,
            tolerance_db=5.0,
        )


class TestAssertResampleDidNotSilence:
    """The audit #2228 regression pin."""

    def test_real_resample_passes(self) -> None:
        original = generate_sine_int16(440.0, 0.5, sample_rate_hz=44100, amplitude=0.5)
        resampled = linear_resample_int16(original, 44100, 48000)
        assert_resample_did_not_silence(input_pcm=original, output_pcm=resampled)

    def test_silenced_output_fails_with_audit_2228_message(self) -> None:
        """Simulate the audit #2228 regression: input audible, output silent."""
        original = generate_sine_int16(440.0, 0.5, amplitude=0.5)
        silenced = b"\x00\x00" * (len(original) // 2)
        with pytest.raises(AssertionError, match="audit #2228"):
            assert_resample_did_not_silence(input_pcm=original, output_pcm=silenced)

    def test_silent_input_fails_with_setup_message(self) -> None:
        """Test setup error: silent input means we can't assert resample worked."""
        zeros = b"\x00\x00" * 1000
        with pytest.raises(AssertionError, match="silent"):
            assert_resample_did_not_silence(input_pcm=zeros, output_pcm=zeros)


class TestAssertFormatConversionDidNotSilence:
    def test_real_conversion_passes(self) -> None:
        original = generate_sine_int16(440.0, 0.1, amplitude=0.5)
        as_float = int16_to_float32(original)
        back_to_int = float32_to_int16(as_float)
        assert_format_conversion_did_not_silence(input_pcm=original, output_pcm=back_to_int)

    def test_silenced_output_fails_with_audit_2228_message(self) -> None:
        original = generate_sine_int16(440.0, 0.5, amplitude=0.5)
        silenced = b"\x00\x00" * (len(original) // 2)
        with pytest.raises(AssertionError, match="audit #2228"):
            assert_format_conversion_did_not_silence(input_pcm=original, output_pcm=silenced)


class TestAudit2228RegressionExemplar:
    """End-to-end integration test of the synthetic chain:
    sine → resample → format-convert → format-convert-back → assert."""

    def test_44k_int16_to_48k_float32_round_trip_preserves_signal(self) -> None:
        # Source: 44.1k int16 sine (typical YouTube / streaming source).
        source = generate_sine_int16(440.0, 0.5, sample_rate_hz=44100, amplitude=0.5)
        # Resample to 48k (chain expects 48k).
        resampled = linear_resample_int16(source, 44100, 48000)
        # Convert int16 → float32 (chain LADSPA stages run on float32).
        as_float = int16_to_float32(resampled)
        # Convert back to int16 for output (broadcast egress is int16).
        output = float32_to_int16(as_float)
        # All 3 audit assertions must pass on this synthetic chain.
        assert_resample_did_not_silence(input_pcm=source, output_pcm=resampled)
        assert_format_conversion_did_not_silence(input_pcm=resampled, output_pcm=output)
        assert_rms_within_attenuation(
            input_pcm=source,
            output_pcm=output,
            declared_attenuation_db=0.0,  # no chain attenuation in this synthetic
            tolerance_db=2.0,  # account for resample + quantisation noise
        )
