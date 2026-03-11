"""Integration test: chime synthesis -> ChimePlayer -> daemon lifecycle."""
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from agents.hapax_voice.chime_synthesis import generate_all_chimes, synthesize_chime, SAMPLE_RATE
from agents.hapax_voice.chime_player import ChimePlayer


class TestChimeIntegration:
    def test_synthesize_and_load_roundtrip(self, tmp_path):
        """Generate chimes, load into player, verify all present."""
        generate_all_chimes(tmp_path)

        player = ChimePlayer(tmp_path)
        player.load()

        assert len(player._buffers) == 4
        for name in ("activation", "deactivation", "error", "completion"):
            assert name in player._buffers
            assert len(player._buffers[name]) > 0
        player.close()

    def test_activation_frequency_content(self):
        """Verify activation chime has energy at D6 (1175 Hz)."""
        audio = synthesize_chime("activation")
        # FFT to check frequency content
        fft = np.abs(np.fft.rfft(audio.astype(np.float64)))
        freqs = np.fft.rfftfreq(len(audio), 1.0 / SAMPLE_RATE)

        # Find the bin closest to 1175 Hz (D6)
        d6_bin = np.argmin(np.abs(freqs - 1175))
        # Find the bin closest to 1568 Hz (G6)
        g6_bin = np.argmin(np.abs(freqs - 1568))

        # Both should have significant energy
        noise_floor = np.median(fft)
        assert fft[d6_bin] > noise_floor * 10, "No significant energy at D6 (1175 Hz)"
        assert fft[g6_bin] > noise_floor * 10, "No significant energy at G6 (1568 Hz)"

    def test_deactivation_is_descending(self):
        """Deactivation chime should start with G6, end with D6."""
        audio = synthesize_chime("deactivation")
        # Split into first half and second half
        mid = len(audio) // 2
        first_half = audio[:mid].astype(np.float64)
        second_half = audio[mid:].astype(np.float64)

        fft1 = np.abs(np.fft.rfft(first_half))
        fft2 = np.abs(np.fft.rfft(second_half))
        freqs1 = np.fft.rfftfreq(len(first_half), 1.0 / SAMPLE_RATE)
        freqs2 = np.fft.rfftfreq(len(second_half), 1.0 / SAMPLE_RATE)

        # First half should have more G6 energy
        g6_bin1 = np.argmin(np.abs(freqs1 - 1568))
        # Second half should have more D6 energy
        d6_bin2 = np.argmin(np.abs(freqs2 - 1175))

        assert fft1[g6_bin1] > np.median(fft1) * 5
        assert fft2[d6_bin2] > np.median(fft2) * 3

    @patch("agents.hapax_voice.chime_player.pyaudio")
    def test_auto_generate_and_play(self, mock_pa, tmp_path):
        """Auto-generate chimes, then play activation."""
        mock_stream = MagicMock()
        mock_pa.PyAudio.return_value.open.return_value = mock_stream
        mock_pa.paInt16 = 8

        chime_dir = tmp_path / "chimes"
        player = ChimePlayer(chime_dir, auto_generate=True)
        player.load()

        # Chimes should have been auto-generated
        assert (chime_dir / "activation.wav").exists()

        player.play("activation")
        # play() runs in a thread, wait briefly
        import time
        time.sleep(0.1)

        # Verify the written audio is non-empty
        mock_stream.write.assert_called_once()
        written_data = mock_stream.write.call_args[0][0]
        assert len(written_data) > 0
        player.close()
