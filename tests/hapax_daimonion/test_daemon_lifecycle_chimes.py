"""Tests for session lifecycle acknowledgment events (chime or screen flash)."""

from unittest.mock import AsyncMock, patch

from agents.hapax_daimonion.config import DaimonionConfig


class TestDeactivationChime:
    @patch("agents.hapax_daimonion.session_events.screen_flash")
    @patch("agents.hapax_daimonion.daemon.AudioInputStream")
    @patch("agents.hapax_daimonion.daemon.TTSManager")
    @patch("agents.hapax_daimonion.daemon.WakeWordDetector")
    @patch("agents.hapax_daimonion.daemon.HotkeyServer")
    @patch("agents.hapax_daimonion.daemon.ChimePlayer")
    def test_close_session_plays_deactivation_chime(self, MockChime, *_, **__):
        from agents.hapax_daimonion.__main__ import VoiceDaemon

        cfg = DaimonionConfig(chime_enabled=True)
        daemon = VoiceDaemon(cfg=cfg)
        mock_player = MockChime.return_value
        daemon._stop_pipeline = AsyncMock()

        daemon.session.open(trigger="test")

        import asyncio

        asyncio.get_event_loop().run_until_complete(daemon._close_session(reason="test"))
        mock_player.play.assert_called_with("deactivation")

    @patch("agents.hapax_daimonion.session_events.screen_flash")
    @patch("agents.hapax_daimonion.daemon.AudioInputStream")
    @patch("agents.hapax_daimonion.daemon.TTSManager")
    @patch("agents.hapax_daimonion.daemon.WakeWordDetector")
    @patch("agents.hapax_daimonion.daemon.HotkeyServer")
    @patch("agents.hapax_daimonion.daemon.ChimePlayer")
    def test_chime_disabled_uses_screen_flash(
        self, MockChime, _hotkey, _ww, _tts, _audio, mock_flash
    ):
        from agents.hapax_daimonion.__main__ import VoiceDaemon

        cfg = DaimonionConfig(chime_enabled=False)
        daemon = VoiceDaemon(cfg=cfg)
        mock_player = MockChime.return_value
        daemon._stop_pipeline = AsyncMock()

        daemon.session.open(trigger="test")

        import asyncio

        asyncio.get_event_loop().run_until_complete(daemon._close_session(reason="test"))
        mock_player.play.assert_not_called()
        mock_flash.assert_called_with("deactivation")
