"""Surface 1: Wake word detection → pipeline start.

Tests the critical handoff: wake word fires → session opens →
daemon audio stops → Pipecat pipeline builds and starts.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.__main__ import VoiceDaemon
from agents.hapax_daimonion.primitives import Event
from agents.hapax_daimonion.session import VoiceLifecycle


def _make_daemon() -> VoiceDaemon:
    """VoiceDaemon with real SessionManager, everything else mocked."""
    with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
        daemon = VoiceDaemon()

    daemon.cfg = MagicMock()
    daemon.cfg.backend = "local"
    daemon.cfg.local_stt_model = "base"
    daemon.cfg.llm_model = "test-model"
    daemon.cfg.voxtral_voice_id = "jessica"
    daemon.cfg.chime_enabled = False

    daemon.session = VoiceLifecycle(silence_timeout_s=30)
    daemon.event_log = MagicMock()
    daemon.chime_player = MagicMock()
    daemon._audio_input = MagicMock()
    daemon._audio_input.is_active = True
    daemon._pipeline_task = None
    daemon._pipecat_task = None
    daemon._pipecat_transport = None
    daemon._gemini_session = None
    daemon._frame_gate = MagicMock()
    daemon.governor = MagicMock()
    daemon.workspace_monitor = MagicMock()
    daemon.workspace_monitor.webcam_capturer = None
    daemon.workspace_monitor.screen_capturer = None
    daemon.wake_word_event = Event()
    daemon.focus_event = Event()
    daemon._wake_word_signal = asyncio.Event()
    daemon.perception = MagicMock()
    daemon._cognitive_loop = None
    daemon._conversation_pipeline = None
    daemon._salience_router = None
    daemon._conversation_buffer = MagicMock()
    daemon._conversation_buffer.is_active = False
    daemon._echo_canceller = None
    daemon._resident_stt = MagicMock()
    daemon._resident_stt.is_loaded = True
    daemon._salience_concern_graph = None

    return daemon


class TestWakeWordOpensSession:
    """Wake word detection opens a session and starts the pipeline.

    After the async refactor, _on_wake_word() sets a signal and
    _wake_word_processor() handles session setup atomically.
    """

    def test_wake_word_sets_signal(self):
        daemon = _make_daemon()
        assert not daemon._wake_word_signal.is_set()

        daemon._on_wake_word()

        assert daemon._wake_word_signal.is_set()

    def test_wake_word_noop_if_session_active(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")

        daemon._on_wake_word()

        assert not daemon._wake_word_signal.is_set()

    @pytest.mark.asyncio
    async def test_processor_opens_session(self):
        daemon = _make_daemon()
        daemon._running = True
        daemon._wake_word_signal.set()

        with patch.object(VoiceDaemon, "_start_pipeline", new_callable=AsyncMock):
            task = asyncio.create_task(daemon._wake_word_processor())
            await asyncio.sleep(0.05)
            daemon._running = False
            daemon._wake_word_signal.set()  # unblock to exit
            await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert daemon.session.is_active
        assert daemon.session.trigger == "wake_word"

    @pytest.mark.asyncio
    async def test_processor_sets_governor_and_gate(self):
        daemon = _make_daemon()
        daemon.governor.wake_word_active = False
        daemon._running = True
        daemon._wake_word_signal.set()

        with patch.object(VoiceDaemon, "_start_pipeline", new_callable=AsyncMock):
            task = asyncio.create_task(daemon._wake_word_processor())
            await asyncio.sleep(0.05)
            daemon._running = False
            daemon._wake_word_signal.set()
            await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert daemon.governor.wake_word_active is True
        daemon._frame_gate.set_directive.assert_called_once_with("process")


class TestWakeWordStartsPipeline:
    """Wake word triggers pipeline build and audio handoff."""

    @pytest.mark.asyncio
    async def test_pipeline_starts_on_wake_word(self):
        daemon = _make_daemon()
        daemon._running = True
        daemon._wake_word_signal.set()

        with patch.object(VoiceDaemon, "_start_pipeline", new_callable=AsyncMock) as mock_start:
            task = asyncio.create_task(daemon._wake_word_processor())
            await asyncio.sleep(0.05)
            daemon._running = False
            daemon._wake_word_signal.set()
            await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_start_keeps_mic_shared(self):
        """New conversation pipeline keeps mic shared (no stop/start)."""
        daemon = _make_daemon()

        with (
            patch.object(daemon, "_start_conversation_pipeline", new_callable=AsyncMock),
        ):
            await daemon._start_pipeline()

        # Mic should NOT be stopped — conversation buffer shares audio
        daemon._audio_input.stop.assert_not_called()

    @pytest.mark.asyncio
    async def test_pipeline_stop_clears_task(self):
        daemon = _make_daemon()

        fake_task = asyncio.create_task(asyncio.sleep(10))
        daemon._pipeline_task = fake_task
        daemon._salience_concern_graph = None

        await daemon._stop_pipeline()

        assert daemon._pipeline_task is None

    @pytest.mark.asyncio
    async def test_pipeline_stop_clears_cognitive_loop(self):
        daemon = _make_daemon()
        daemon._salience_concern_graph = None

        mock_loop = MagicMock()
        daemon._cognitive_loop = mock_loop

        await daemon._stop_pipeline()

        mock_loop.stop_loop.assert_called_once()
        assert daemon._cognitive_loop is None
