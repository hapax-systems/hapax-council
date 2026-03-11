"""Surface 1: Wake word detection → pipeline start.

Tests the critical handoff: wake word fires → session opens →
daemon audio stops → Pipecat pipeline builds and starts.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_voice.__main__ import VoiceDaemon
from agents.hapax_voice.session import VoiceLifecycle


def _make_daemon() -> VoiceDaemon:
    """VoiceDaemon with real SessionManager, everything else mocked."""
    with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
        daemon = VoiceDaemon()

    daemon.cfg = MagicMock()
    daemon.cfg.backend = "local"
    daemon.cfg.local_stt_model = "base"
    daemon.cfg.llm_model = "test-model"
    daemon.cfg.kokoro_voice = "af_heart"
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

    return daemon


class TestWakeWordOpensSession:
    """Wake word detection opens a session and starts the pipeline."""

    def test_session_opens_on_wake_word(self):
        daemon = _make_daemon()
        assert not daemon.session.is_active

        daemon._on_wake_word()

        assert daemon.session.is_active
        assert daemon.session.trigger == "wake_word"
        assert daemon.session.session_id is not None

    def test_governor_wake_word_flag_set(self):
        daemon = _make_daemon()
        daemon.governor.wake_word_active = False

        daemon._on_wake_word()

        assert daemon.governor.wake_word_active is True

    def test_frame_gate_set_to_process(self):
        daemon = _make_daemon()

        daemon._on_wake_word()

        daemon._frame_gate.set_directive.assert_called_once_with("process")

    def test_event_log_records_session_open(self):
        daemon = _make_daemon()

        daemon._on_wake_word()

        daemon.event_log.emit.assert_any_call(
            "session_lifecycle", action="opened", trigger="wake_word"
        )

    def test_wake_word_noop_if_session_active(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")
        daemon.event_log.reset_mock()

        daemon._on_wake_word()

        daemon.event_log.emit.assert_not_called()


class TestWakeWordStartsPipeline:
    """Wake word triggers pipeline build and audio handoff."""

    @pytest.mark.asyncio
    async def test_pipeline_starts_on_wake_word(self):
        daemon = _make_daemon()

        with patch(
            "agents.hapax_voice.__main__.VoiceDaemon._start_pipeline",
            new_callable=AsyncMock,
        ) as mock_start:
            daemon._on_wake_word()
            # _on_wake_word creates a task — let it run
            await asyncio.sleep(0.05)

            mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_audio_input_stops_for_pipeline(self):
        daemon = _make_daemon()

        mock_task = MagicMock()
        mock_transport = MagicMock()

        with (
            patch(
                "agents.hapax_voice.pipeline.build_pipeline_task",
                return_value=(mock_task, mock_transport),
            ),
            patch("pipecat.pipeline.runner.PipelineRunner"),
        ):
            await daemon._start_local_pipeline()

        daemon._audio_input.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_audio_input_restored_on_pipeline_build_failure(self):
        daemon = _make_daemon()

        with patch(
            "agents.hapax_voice.pipeline.build_pipeline_task",
            side_effect=RuntimeError("build failed"),
        ):
            await daemon._start_local_pipeline()

        daemon._audio_input.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_stop_restores_audio(self):
        daemon = _make_daemon()
        daemon._audio_input.is_active = False

        fake_task = asyncio.create_task(asyncio.sleep(10))
        daemon._pipeline_task = fake_task
        daemon._pipecat_task = MagicMock()
        daemon._pipecat_transport = MagicMock()

        await daemon._stop_pipeline()

        daemon._audio_input.start.assert_called_once()
        assert daemon._pipeline_task is None
