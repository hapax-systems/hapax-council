"""Tests for CPAL runner."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.hapax_daimonion.cpal.runner import CpalRunner


class TestCpalRunnerLifecycle:
    def _make_runner(self):
        buffer = MagicMock()
        buffer.speech_active = False
        buffer.speech_duration_s = 0.0
        buffer.is_speaking = False
        buffer.get_utterance.return_value = None
        buffer.speech_frames_snapshot = []

        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="")

        router = MagicMock()
        router.route.return_value = MagicMock(tier="CAPABLE")

        return CpalRunner(
            buffer=buffer,
            stt=stt,
            salience_router=router,
        )

    def test_initial_state(self):
        runner = self._make_runner()
        assert not runner.is_running
        assert runner.tick_count == 0

    @pytest.mark.asyncio
    async def test_run_and_stop(self):
        runner = self._make_runner()

        async def stop_after_ticks():
            while runner.tick_count < 3:
                await asyncio.sleep(0.05)
            runner.stop()

        await asyncio.gather(runner.run(), stop_after_ticks())
        assert not runner.is_running
        assert runner.tick_count >= 3

    @pytest.mark.asyncio
    async def test_gain_rises_during_speech(self):
        runner = self._make_runner()
        # Simulate operator speaking
        runner._buffer.speech_active = True

        async def stop_after():
            while runner.tick_count < 5:
                await asyncio.sleep(0.05)
            runner.stop()

        await asyncio.gather(runner.run(), stop_after())
        assert runner.evaluator.gain_controller.gain > 0.0

    @pytest.mark.asyncio
    async def test_utterance_detected(self):
        runner = self._make_runner()
        runner._buffer.get_utterance.return_value = b"\x00\x01" * 500

        async def stop_after():
            while runner.tick_count < 2:
                await asyncio.sleep(0.05)
            runner.stop()

        await asyncio.gather(runner.run(), stop_after())
        # Utterance was consumed (get_utterance called)
        runner._buffer.get_utterance.assert_called()

    @pytest.mark.asyncio
    async def test_process_impingement(self):
        runner = self._make_runner()
        imp = MagicMock()
        imp.source = "stimmung"
        imp.strength = 0.9
        imp.content = {"metric": "stimmung_critical", "narrative": "System critical"}
        imp.interrupt_token = None

        await runner.process_impingement(imp)
        assert runner.evaluator.gain_controller.gain > 0.0

    def test_presynthesize_signals(self):
        runner = self._make_runner()
        tts = MagicMock()
        tts.synthesize.return_value = b"\x00\x01" * 100
        runner._tts_manager = tts
        runner.presynthesize_signals()
        assert runner.signal_cache.is_ready
