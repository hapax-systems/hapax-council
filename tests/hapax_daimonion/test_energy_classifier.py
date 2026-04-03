import struct
import time
from unittest.mock import patch

from agents.hapax_daimonion.energy_classifier import EnergyClassifier, TtsEnergyTracker


def _make_pcm(amplitude: int = 10000, n_samples: int = 480) -> bytes:
    """Generate a mono int16 PCM frame at given amplitude."""
    return struct.pack(f"<{n_samples}h", *([amplitude] * n_samples))


def _silence(n_samples: int = 480) -> bytes:
    return b"\x00\x00" * n_samples


class TestTtsEnergyTracker:
    def test_inactive_when_no_tts(self):
        t = TtsEnergyTracker()
        assert not t.is_active()

    def test_active_after_record(self):
        t = TtsEnergyTracker()
        t.record(_make_pcm())
        assert t.is_active()

    def test_inactive_after_decay(self):
        t = TtsEnergyTracker(decay_s=0.1)
        t.record(_make_pcm())
        with patch("agents.hapax_daimonion.energy_classifier.time") as mock_time:
            mock_time.monotonic.return_value = time.monotonic() + 0.2
            assert not t.is_active()

    def test_expected_energy_tracks_tts(self):
        t = TtsEnergyTracker()
        t.record(_make_pcm(amplitude=10000))
        energy = t.expected_energy()
        assert energy > 5000

    def test_expected_energy_zero_when_inactive(self):
        t = TtsEnergyTracker()
        assert t.expected_energy() == 0.0

    def test_ring_buffer_bounded(self):
        t = TtsEnergyTracker(buffer_size=5)
        for _ in range(20):
            t.record(_make_pcm())
        assert len(t._energy_ring) <= 5


class TestEnergyClassifier:
    def test_silence_when_not_speaking(self):
        tracker = TtsEnergyTracker()
        c = EnergyClassifier(tracker)
        result = c.classify(_silence(), system_speaking=False)
        assert result == "silent"

    def test_speech_when_not_speaking(self):
        tracker = TtsEnergyTracker()
        c = EnergyClassifier(tracker)
        result = c.classify(_make_pcm(amplitude=5000), system_speaking=False)
        assert result == "speech"

    def test_echo_when_mic_tracks_tts(self):
        tracker = TtsEnergyTracker()
        tracker.record(_make_pcm(amplitude=10000))
        c = EnergyClassifier(tracker)
        # Mic energy similar to TTS energy = residual echo
        result = c.classify(_make_pcm(amplitude=800), system_speaking=True)
        assert result == "echo"

    def test_speech_when_mic_exceeds_tts(self):
        tracker = TtsEnergyTracker()
        tracker.record(_make_pcm(amplitude=2000))  # quiet TTS
        c = EnergyClassifier(tracker)
        # Mic energy much higher than expected echo = real speech
        result = c.classify(_make_pcm(amplitude=10000), system_speaking=True)
        assert result == "speech"

    def test_silent_frame_during_tts(self):
        tracker = TtsEnergyTracker()
        tracker.record(_make_pcm(amplitude=10000))
        c = EnergyClassifier(tracker)
        result = c.classify(_silence(), system_speaking=True)
        assert result == "silent"

    def test_not_speaking_always_speech_or_silent(self):
        """When system is not speaking, never classify as echo."""
        tracker = TtsEnergyTracker()
        tracker.record(_make_pcm(amplitude=10000))
        c = EnergyClassifier(tracker)
        result = c.classify(_make_pcm(amplitude=8000), system_speaking=False)
        assert result in ("speech", "silent")
