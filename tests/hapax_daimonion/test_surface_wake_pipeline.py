"""Surface 1: Engagement detection → pipeline start.

Tests the critical handoff: engagement detected → session opens →
daemon audio stops → pipeline builds and starts.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.__main__ import VoiceDaemon
from agents.hapax_daimonion.session import VoiceLifecycle


def _make_daemon() -> VoiceDaemon:
    """VoiceDaemon with real SessionManager, everything else mocked."""
    with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
        daemon = VoiceDaemon()

    daemon.cfg = MagicMock()
    daemon.cfg.backend = "local"
    daemon.cfg.local_stt_model = "base"
    daemon.cfg.llm_model = "test-model"
    daemon.cfg.tts_voice = "af_heart"
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
    daemon.focus_event = MagicMock()
    daemon._engagement_signal = asyncio.Event()
    daemon.perception = MagicMock()
    daemon._cpal_runner = MagicMock()
    daemon._conversation_pipeline = None
    daemon._salience_router = None
    daemon._conversation_buffer = MagicMock()
    daemon._conversation_buffer.is_active = False
    daemon._echo_canceller = None
    daemon._resident_stt = MagicMock()
    daemon._resident_stt.is_loaded = True
    daemon._salience_concern_graph = None

    return daemon


class TestEngagementOpensSession:
    """Engagement detection opens a session and starts the pipeline.

    on_engagement_detected() is now a single async entry point that
    boosts CPAL gain, opens session, runs veto, and starts pipeline.
    """

    @pytest.mark.asyncio
    async def test_engagement_noop_if_session_active(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")

        from agents.hapax_daimonion.session_events import on_engagement_detected

        with patch.object(VoiceDaemon, "_start_pipeline", new_callable=AsyncMock):
            await on_engagement_detected(daemon)

        # Pipeline should NOT have been started — session was already active
        assert daemon.session.trigger == "test"

    @pytest.mark.asyncio
    async def test_engagement_opens_session(self):
        daemon = _make_daemon()
        daemon.governor._veto_chain = MagicMock()
        daemon.governor._veto_chain.evaluate.return_value = MagicMock(allowed=True, denied_by=())

        with patch.object(VoiceDaemon, "_start_pipeline", new_callable=AsyncMock):
            from agents.hapax_daimonion.session_events import on_engagement_detected

            await on_engagement_detected(daemon)

        assert daemon.session.is_active
        assert daemon.session.trigger == "engagement"

    @pytest.mark.asyncio
    async def test_engagement_sets_governor_and_gate(self):
        daemon = _make_daemon()
        daemon.governor.engagement_active = False
        daemon.governor._veto_chain = MagicMock()
        daemon.governor._veto_chain.evaluate.return_value = MagicMock(allowed=True, denied_by=())

        with patch.object(VoiceDaemon, "_start_pipeline", new_callable=AsyncMock):
            from agents.hapax_daimonion.session_events import on_engagement_detected

            await on_engagement_detected(daemon)

        assert daemon.governor.engagement_active is True
        daemon._frame_gate.set_directive.assert_called_once_with("process")


class TestEngagementStartsPipeline:
    """Engagement triggers pipeline build and audio handoff."""

    @pytest.mark.asyncio
    async def test_pipeline_starts_on_engagement(self):
        daemon = _make_daemon()
        daemon.governor._veto_chain = MagicMock()
        daemon.governor._veto_chain.evaluate.return_value = MagicMock(allowed=True, denied_by=())

        with patch.object(VoiceDaemon, "_start_pipeline", new_callable=AsyncMock) as mock_start:
            from agents.hapax_daimonion.session_events import on_engagement_detected

            await on_engagement_detected(daemon)

            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_start_keeps_mic_shared(self):
        """New conversation pipeline keeps mic shared (no stop/start)."""
        daemon = _make_daemon()

        with (
            patch.object(daemon, "_start_pipeline", new_callable=AsyncMock),
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
