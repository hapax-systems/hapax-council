"""Tests for AudioExecutor — mocked PyAudio, daemon thread, Executor protocol."""

from __future__ import annotations

import struct
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from agents.hapax_voice.audio_executor import AudioExecutor
from agents.hapax_voice.commands import Command
from agents.hapax_voice.executor import Executor
from agents.hapax_voice.sample_bank import SampleBank


def _write_wav(path: Path, rate: int = 44100, channels: int = 1, n_frames: int = 100) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(struct.pack(f"<{n_frames}h", *([1000] * n_frames)))


class TestAudioExecutor(unittest.TestCase):
    def _make_executor(self, tmpdir: str):
        base = Path(tmpdir)
        _write_wav(base / "vocal_throw" / "high_001.wav")
        _write_wav(base / "ad_lib" / "medium_001.wav")

        bank = SampleBank(base)
        bank.load()

        mock_pa = MagicMock()
        mock_stream = MagicMock()
        mock_pa.open.return_value = mock_stream

        executor = AudioExecutor(pa=mock_pa, sample_bank=bank)
        return executor, mock_pa, mock_stream

    def test_satisfies_executor_protocol(self):
        with TemporaryDirectory() as tmpdir:
            executor, _, _ = self._make_executor(tmpdir)
            self.assertIsInstance(executor, Executor)

    @patch("agents.hapax_voice.audio_executor.threading.Thread")
    def test_execute_spawns_daemon_thread(self, mock_thread_cls):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        with TemporaryDirectory() as tmpdir:
            executor, _, _ = self._make_executor(tmpdir)
            cmd = Command(action="vocal_throw", params={"energy_rms": 0.8})
            executor.execute(cmd)

            mock_thread_cls.assert_called_once()
            _, kwargs = mock_thread_cls.call_args
            self.assertTrue(kwargs["daemon"])
            mock_thread.start.assert_called_once()

    def test_play_pcm_calls_stream_write(self):
        with TemporaryDirectory() as tmpdir:
            executor, mock_pa, mock_stream = self._make_executor(tmpdir)
            executor._play_pcm(b"\x00\x00", 44100, 1, "test")
            mock_pa.open.assert_called_once()
            mock_stream.write.assert_called_once_with(b"\x00\x00")
            mock_stream.stop_stream.assert_called_once()
            mock_stream.close.assert_called_once()

    def test_available_with_samples(self):
        with TemporaryDirectory() as tmpdir:
            executor, _, _ = self._make_executor(tmpdir)
            self.assertTrue(executor.available())

    def test_unavailable_without_pa(self):
        bank = SampleBank(Path("/nonexistent"))
        executor = AudioExecutor(pa=None, sample_bank=bank)
        self.assertFalse(executor.available())

    def test_handles(self):
        with TemporaryDirectory() as tmpdir:
            executor, _, _ = self._make_executor(tmpdir)
            self.assertEqual(executor.handles, frozenset({"vocal_throw", "ad_lib"}))

    def test_execute_no_matching_sample(self):
        """execute with unknown action does not spawn thread."""
        with TemporaryDirectory() as tmpdir:
            executor, _, _ = self._make_executor(tmpdir)
            with patch("agents.hapax_voice.audio_executor.threading.Thread") as mock_thread_cls:
                executor.execute(Command(action="nonexistent"))
                mock_thread_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
