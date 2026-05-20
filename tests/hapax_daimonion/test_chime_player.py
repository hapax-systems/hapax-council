"""Tests for ChimePlayer non-blocking WAV playback via pw-cat."""

from unittest.mock import patch

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
            f.setframerate(44100)
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
    @patch("agents.hapax_daimonion.pw_audio_output.play_pcm")
    def test_play_known_chime(self, mock_play, chime_dir):
        player = ChimePlayer(chime_dir)
        player.load()
        player.play("activation")
        import time

        time.sleep(0.1)
        mock_play.assert_called_once()

    def test_play_unknown_chime_no_error(self, chime_dir):
        player = ChimePlayer(chime_dir)
        player.load()
        player.play("nonexistent")

    def test_play_before_load_no_error(self, chime_dir):
        player = ChimePlayer(chime_dir)
        player.play("activation")


class TestChimePlayerAutoGenerate:
    def test_auto_generates_if_dir_empty(self, tmp_path):
        chime_dir = tmp_path / "chimes"
        chime_dir.mkdir()
        player = ChimePlayer(chime_dir, auto_generate=True)
        player.load()
        assert len(player._buffers) == 4
        assert (chime_dir / "activation.wav").exists()

    def test_auto_generates_if_dir_missing(self, tmp_path):
        chime_dir = tmp_path / "chimes_new"
        player = ChimePlayer(chime_dir, auto_generate=True)
        player.load()
        assert len(player._buffers) == 4


class TestChimePlayerClose:
    def test_close_clears_buffers(self, chime_dir):
        player = ChimePlayer(chime_dir)
        player.load()
        assert len(player._buffers) > 0
        player.close()
        assert len(player._buffers) == 0
