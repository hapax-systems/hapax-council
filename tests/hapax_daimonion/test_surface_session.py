"""Surface 3: Session lifecycle — open, close, timeout, pause, resume.

Tests the session state machine wired into the daemon, verifying
that state transitions trigger the correct pipeline and event actions.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.__main__ import VoiceDaemon
from agents.hapax_daimonion.session import VoiceLifecycle


def _make_daemon(silence_timeout_s: int = 30) -> VoiceDaemon:
    with patch.object(VoiceDaemon, "__init__", lambda self, **kw: None):
        daemon = VoiceDaemon()

    daemon.cfg = MagicMock()
    daemon.cfg.backend = "local"
    daemon.cfg.chime_enabled = False
    daemon.cfg.local_stt_model = "base"
    daemon.cfg.llm_model = "test-model"
    daemon.cfg.voxtral_voice_id = "jessica"

    daemon.session = VoiceLifecycle(silence_timeout_s=silence_timeout_s)
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
    daemon.perception = MagicMock()
    daemon._cognitive_loop = None
    daemon._conversation_pipeline = None
    daemon._salience_router = None
    daemon._conversation_buffer = MagicMock()
    daemon._conversation_buffer.is_active = False
    daemon._echo_canceller = None
    daemon._resident_stt = MagicMock()
    daemon._resident_stt.is_loaded = True

    return daemon


class TestSessionOpenClose:
    """Session opens and closes with correct state transitions."""

    @pytest.mark.asyncio
    async def test_hotkey_open_starts_session(self):
        daemon = _make_daemon()

        with (
            patch.object(daemon, "_start_pipeline", new_callable=AsyncMock),
            patch("agents.hapax_daimonion.session_events.screen_flash"),
        ):
            await daemon._handle_hotkey("open")

        assert daemon.session.is_active
        assert daemon.session.trigger == "hotkey"

    @pytest.mark.asyncio
    async def test_hotkey_close_ends_session(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")

        with (
            patch.object(daemon, "_stop_pipeline", new_callable=AsyncMock),
            patch("agents.hapax_daimonion.session_events.screen_flash"),
        ):
            await daemon._handle_hotkey("close")

        assert not daemon.session.is_active
        assert daemon.session.session_id is None

    @pytest.mark.asyncio
    async def test_toggle_opens_when_idle(self):
        daemon = _make_daemon()

        with (
            patch.object(daemon, "_start_pipeline", new_callable=AsyncMock),
            patch("agents.hapax_daimonion.session_events.screen_flash"),
        ):
            await daemon._handle_hotkey("toggle")

        assert daemon.session.is_active

    @pytest.mark.asyncio
    async def test_toggle_closes_when_active(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")

        with (
            patch.object(daemon, "_stop_pipeline", new_callable=AsyncMock),
            patch("agents.hapax_daimonion.session_events.screen_flash"),
        ):
            await daemon._handle_hotkey("toggle")

        assert not daemon.session.is_active

    @pytest.mark.asyncio
    async def test_close_stops_pipeline(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")

        with (
            patch.object(daemon, "_stop_pipeline", new_callable=AsyncMock) as mock_stop,
            patch("agents.hapax_daimonion.session_events.screen_flash"),
        ):
            await daemon._close_session(reason="test")

        mock_stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_emits_event_with_duration(self):
        daemon = _make_daemon()
        daemon.session.open(trigger="test")

        with (
            patch.object(daemon, "_stop_pipeline", new_callable=AsyncMock),
            patch("agents.hapax_daimonion.session_events.screen_flash"),
        ):
            await daemon._close_session(reason="timeout")

        daemon.event_log.emit.assert_any_call(
            "session_lifecycle",
            action="closed",
            reason="timeout",
            duration_s=pytest.approx(0.0, abs=1.0),
        )


class TestSessionTimeout:
    """Session timeout detection works correctly."""

    def test_session_not_timed_out_when_fresh(self):
        session = VoiceLifecycle(silence_timeout_s=1)
        session.open(trigger="test")
        assert not session.is_timed_out

    def test_session_timed_out_after_silence(self):
        session = VoiceLifecycle(silence_timeout_s=0)
        session.open(trigger="test")
        session._last_activity = time.monotonic() - 1.0
        assert session.is_timed_out

    def test_mark_activity_resets_timeout(self):
        session = VoiceLifecycle(silence_timeout_s=5)
        session.open(trigger="test")
        session._last_activity = time.monotonic() - 10.0
        assert session.is_timed_out
        session.mark_activity()
        assert not session.is_timed_out

    def test_paused_session_does_not_timeout(self):
        session = VoiceLifecycle(silence_timeout_s=0)
        session.open(trigger="test")
        session._last_activity = time.monotonic() - 1.0
        session.pause(reason="governor")
        assert not session.is_timed_out


class TestSessionPauseResume:
    """Pause and resume interact correctly with timeout."""

    def test_pause_sets_paused_flag(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        session.pause(reason="conversation")
        assert session.is_paused

    def test_resume_clears_paused_flag(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        session.pause(reason="test")
        session.resume()
        assert not session.is_paused

    def test_resume_resets_activity_timer(self):
        session = VoiceLifecycle(silence_timeout_s=10)
        session.open(trigger="test")
        session._last_activity = time.monotonic() - 5.0
        session.pause(reason="test")
        session.resume()
        assert not session.is_timed_out

    def test_close_clears_paused(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        session.pause(reason="test")
        session.close(reason="done")
        assert not session.is_paused

    def test_pause_noop_when_idle(self):
        session = VoiceLifecycle()
        session.pause(reason="test")
        assert not session.is_paused


class TestGuestMode:
    """Guest mode detection based on speaker identity."""

    def test_not_guest_when_no_speaker(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        assert not session.is_guest_mode

    def test_not_guest_when_operator(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        session.set_speaker("operator", 0.9)
        assert not session.is_guest_mode

    def test_guest_when_non_operator(self):
        session = VoiceLifecycle()
        session.open(trigger="test")
        session.set_speaker("child", 0.8)
        assert session.is_guest_mode
