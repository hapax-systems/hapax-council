"""Tests for ChimePlayer non-blocking WAV playback."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from agents.hapax_daimonion.chime_player import ChimePlayer


@pytest.fixture
def chime_dir(tmp_path):
    """Create a temp dir with test chime WAVs."""
    import wave

    for name in ("activation", "deactivation", "error", "completion"):
        samples = np.zeros(4800, dtype=np.int16)  # 100ms at 48kHz
        path = tmp_path / f"{name}.wav"
        with wave.open(str(path), "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(48000)
            f.writeframes(samples.tobytes())
    return tmp_path


class TestChimePlayerLoad:
    def test_loads_all_chimes(self, chime_dir):
        player = ChimePlayer(chime_dir)
        player.load()
        assert "activation" in player._buffers
        assert "deactivation" in player._buffers
        assert "error" in player._buffers
        assert "completion" in player._buffers

    def test_load_stores_bytes(self, chime_dir):
        player = ChimePlayer(chime_dir)
        player.load()
        assert isinstance(player._buffers["activation"], bytes)
        assert len(player._buffers["activation"]) > 0

    def test_load_missing_dir_logs_warning(self, tmp_path):
        player = ChimePlayer(tmp_path / "nonexistent")
        player.load()
        assert len(player._buffers) == 0

    def test_load_empty_dir_logs_warning(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        player = ChimePlayer(empty_dir)
        player.load()
        assert len(player._buffers) == 0


class TestChimePlayerPlay:
    @patch("agents.hapax_daimonion.chime_player.pyaudio")
    def test_play_known_chime(self, mock_pa, chime_dir):
        mock_stream = MagicMock()
        mock_pa.PyAudio.return_value.open.return_value = mock_stream
        mock_pa.paInt16 = 8  # PyAudio paInt16 constant

        player = ChimePlayer(chime_dir)
        player.load()
        player.play("activation")
        # play() launches a daemon thread — give it time to complete
        import time

        time.sleep(0.1)
        mock_stream.write.assert_called_once()

    @patch("agents.hapax_daimonion.chime_player.pyaudio")
    def test_play_unknown_chime_no_error(self, mock_pa, chime_dir):
        player = ChimePlayer(chime_dir)
        player.load()
        # Should log warning but not raise
        player.play("nonexistent")

    @patch("agents.hapax_daimonion.chime_player.pyaudio")
    def test_play_before_load_no_error(self, mock_pa, chime_dir):
        player = ChimePlayer(chime_dir)
        # Should handle gracefully
        player.play("activation")


class TestChimePlayerAutoGenerate:
    @patch("agents.hapax_daimonion.chime_player.pyaudio")
    def test_auto_generates_if_dir_empty(self, mock_pa, tmp_path):
        chime_dir = tmp_path / "chimes"
        chime_dir.mkdir()
        player = ChimePlayer(chime_dir, auto_generate=True)
        player.load()
        # Should have generated and loaded all 4 chimes
        assert len(player._buffers) == 4
        assert (chime_dir / "activation.wav").exists()

    @patch("agents.hapax_daimonion.chime_player.pyaudio")
    def test_auto_generates_if_dir_missing(self, mock_pa, tmp_path):
        chime_dir = tmp_path / "chimes_new"
        player = ChimePlayer(chime_dir, auto_generate=True)
        player.load()
        assert len(player._buffers) == 4


class TestChimePlayerClose:
    @patch("agents.hapax_daimonion.chime_player.pyaudio")
    def test_close_terminates_pyaudio(self, mock_pa, chime_dir):
        mock_instance = mock_pa.PyAudio.return_value
        player = ChimePlayer(chime_dir)
        player.load()
        player.close()
        mock_instance.terminate.assert_called_once()
