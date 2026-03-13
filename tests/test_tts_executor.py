"""Tests for TTSExecutor — mocked PyAudio, pre-synthesized PCM playback."""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from agents.hapax_voice.commands import Command, Schedule
from agents.hapax_voice.executor import Executor, ScheduleQueue
from agents.hapax_voice.tts_executor import TTSExecutor


class TestTTSExecutor(unittest.TestCase):
    def _make_executor(self):
        mock_pa = MagicMock()
        mock_stream = MagicMock()
        mock_pa.open.return_value = mock_stream
        return TTSExecutor(pa=mock_pa), mock_pa, mock_stream

    def test_satisfies_executor_protocol(self):
        ex, _, _ = self._make_executor()
        self.assertIsInstance(ex, Executor)

    def test_handles(self):
        ex, _, _ = self._make_executor()
        self.assertEqual(ex.handles, frozenset({"tts_announce"}))

    def test_play_pcm_from_params(self):
        ex, mock_pa, mock_stream = self._make_executor()
        pcm = b"\x00\x01" * 100
        ex._play_pcm(pcm, 24000, 1)
        mock_pa.open.assert_called_once()
        mock_stream.write.assert_called_once_with(pcm)
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()

    @patch("agents.hapax_voice.tts_executor.threading.Thread")
    def test_execute_spawns_daemon_thread(self, mock_thread_cls):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread
        ex, _, _ = self._make_executor()

        pcm = b"\x00\x01" * 100
        cmd = Command(action="tts_announce", params={"pcm_data": pcm, "sample_rate": 24000})
        ex.execute(cmd)

        mock_thread_cls.assert_called_once()
        _, kwargs = mock_thread_cls.call_args
        self.assertTrue(kwargs["daemon"])
        mock_thread.start.assert_called_once()

    def test_missing_pcm_data_handled(self):
        ex, _, _ = self._make_executor()
        cmd = Command(action="tts_announce", params={})
        # Should not raise
        ex.execute(cmd)

    def test_non_bytes_pcm_handled(self):
        ex, _, _ = self._make_executor()
        cmd = Command(action="tts_announce", params={"pcm_data": "not bytes"})
        ex.execute(cmd)  # should not raise

    def test_available_with_pa(self):
        ex, _, _ = self._make_executor()
        self.assertTrue(ex.available())

    def test_unavailable_without_pa(self):
        ex = TTSExecutor(pa=None)
        self.assertFalse(ex.available())

    def test_integration_synthesize_enqueue_drain_play(self):
        """Simulates: synthesize → Command.params → ScheduleQueue → drain → TTSExecutor."""
        ex, mock_pa, mock_stream = self._make_executor()

        # Step 1: "synthesize" (in reality Kokoro produces PCM)
        pcm = b"\x00\x01" * 500

        # Step 2: Pack into Command
        cmd = Command(
            action="tts_announce",
            params={"pcm_data": pcm, "sample_rate": 24000},
            trigger_source="tts_governance",
        )

        # Step 3: Create Schedule targeting bar boundary
        now = time.monotonic()
        schedule = Schedule(
            command=cmd,
            domain="beat",
            target_time=4.0,  # bar boundary
            wall_time=now + 0.001,  # just ahead of now
            tolerance_ms=100.0,
        )

        # Step 4: Enqueue and drain
        queue = ScheduleQueue()
        queue.enqueue(schedule)

        ready = queue.drain(now + 0.002)
        self.assertEqual(len(ready), 1)

        # Step 5: Play
        ex._play_pcm(ready[0].command.params["pcm_data"], 24000, 1)
        mock_stream.write.assert_called_once_with(pcm)


if __name__ == "__main__":
    unittest.main()
