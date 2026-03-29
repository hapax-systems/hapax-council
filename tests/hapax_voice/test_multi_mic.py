"""Tests for multi-source noise averaging and PipeWire source discovery."""

from __future__ import annotations

import numpy as np

from agents.hapax_voice.multi_mic import NoiseReference, discover_pipewire_sources


def _make_pcm_frame(freq_hz: float, sample_rate: int = 16000, n_samples: int = 512) -> bytes:
    """Generate a pure tone as int16 bytes."""
    t = np.arange(n_samples) / sample_rate
    samples = (0.5 * 32767 * np.sin(2 * np.pi * freq_hz * t)).astype(np.int16)
    return samples.tobytes()


def _mag_from_pcm(pcm: bytes, n_fft: int = 512) -> np.ndarray:
    """Convert PCM bytes to magnitude spectrum."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    window = np.hanning(n_fft)
    return np.abs(np.fft.rfft(samples[:n_fft] * window))


class TestApplySubtraction:
    """Test NoiseReference._apply_subtraction() static method."""

    def test_subtraction_reduces_magnitude(self):
        mag = np.array([10.0, 20.0, 30.0])
        noise = np.array([2.0, 4.0, 6.0])
        result = NoiseReference._apply_subtraction(mag, noise, alpha=1.5, beta=0.01)
        expected = np.maximum(mag - 1.5 * noise, 0.01 * mag)
        np.testing.assert_array_almost_equal(result, expected)
        assert np.all(result < mag)

    def test_floors_at_beta_when_noise_dominates(self):
        mag = np.array([1.0, 2.0, 3.0])
        noise = np.array([100.0, 200.0, 300.0])
        result = NoiseReference._apply_subtraction(mag, noise, alpha=1.5, beta=0.01)
        expected = 0.01 * mag
        np.testing.assert_array_almost_equal(result, expected)

    def test_none_noise_is_passthrough(self):
        mag = np.array([10.0, 20.0, 30.0])
        result = NoiseReference._apply_subtraction(mag, None, alpha=1.5, beta=0.01)
        np.testing.assert_array_equal(result, mag)

    def test_mismatched_length_is_passthrough(self):
        mag = np.array([10.0, 20.0, 30.0])
        noise = np.array([1.0, 2.0])  # shorter
        result = NoiseReference._apply_subtraction(mag, noise, alpha=1.5, beta=0.01)
        np.testing.assert_array_equal(result, mag)


class TestMultiSourceAveraging:
    """Test _averaged_room_estimate() and subtract() with multiple room sources."""

    def test_averaging_two_room_estimates(self):
        ref = NoiseReference(room_sources=["mic1", "mic2"])
        est1 = np.array([10.0, 20.0, 30.0])
        est2 = np.array([20.0, 40.0, 60.0])
        ref._room_estimates["mic1"] = est1
        ref._room_estimates["mic2"] = est2

        result = ref._averaged_room_estimate()
        expected = (est1 + est2) / 2.0
        np.testing.assert_array_almost_equal(result, expected)

    def test_single_source_returns_itself(self):
        ref = NoiseReference(room_sources=["mic1"])
        est = np.array([5.0, 10.0, 15.0])
        ref._room_estimates["mic1"] = est

        result = ref._averaged_room_estimate()
        np.testing.assert_array_almost_equal(result, est)

    def test_empty_returns_none(self):
        ref = NoiseReference(room_sources=["mic1"])
        result = ref._averaged_room_estimate()
        assert result is None

    def test_subtract_uses_averaged_estimate(self):
        ref = NoiseReference(room_sources=["mic1", "mic2"])
        frame = _make_pcm_frame(440.0)
        mag = _mag_from_pcm(frame)

        # Two different noise estimates — averaged result differs from either alone
        ref._room_estimates["mic1"] = mag * 0.3
        ref._room_estimates["mic2"] = mag * 0.5

        result = ref.subtract(frame)
        # Result should differ from input (subtraction happened)
        assert result != frame

    def test_passthrough_when_no_estimates(self):
        ref = NoiseReference(room_sources=["mic1"])
        frame = _make_pcm_frame(440.0)
        result = ref.subtract(frame)
        assert result == frame


MOCK_PACTL_OUTPUT = """\
49\talsa_input.usb-046d_HD_Pro_Webcam_C920_ABC123-02.analog-stereo\tPipeWireAudioSource\ts16le\t2ch\t48000Hz\tRUNNING
50\talsa_input.usb-046d_HD_Pro_Webcam_C920_DEF456-02.analog-stereo\tPipeWireAudioSource\ts16le\t2ch\t48000Hz\tRUNNING
51\talsa_input.usb-046d_HD_Pro_Webcam_C920_GHI789-02.analog-stereo\tPipeWireAudioSource\ts16le\t2ch\t48000Hz\tRUNNING
52\talsa_input.usb-046d_BRIO_4K_Stream_Edition_JKL012-02.analog-stereo\tPipeWireAudioSource\ts16le\t2ch\t48000Hz\tIDLE
53\talsa_output.pci-0000_0c_00.4.analog-stereo\tPipeWireAudioSink\ts32le\t2ch\t48000Hz\tRUNNING
"""


class TestSourceDiscovery:
    """Test discover_pipewire_sources()."""

    def test_matches_c920_pattern(self):
        sources = discover_pipewire_sources(["C920"], _pactl_output=MOCK_PACTL_OUTPUT)
        assert len(sources) == 3
        for s in sources:
            assert "C920" in s

    def test_matches_brio_pattern(self):
        sources = discover_pipewire_sources(["BRIO"], _pactl_output=MOCK_PACTL_OUTPUT)
        assert len(sources) == 1
        assert "BRIO" in sources[0]

    def test_matches_multiple_patterns(self):
        sources = discover_pipewire_sources(["C920", "BRIO"], _pactl_output=MOCK_PACTL_OUTPUT)
        assert len(sources) == 4

    def test_no_matches_returns_empty(self):
        sources = discover_pipewire_sources(["NonexistentDevice"], _pactl_output=MOCK_PACTL_OUTPUT)
        assert sources == []
