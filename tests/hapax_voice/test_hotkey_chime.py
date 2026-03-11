"""Tests for chime/flash playback on hotkey-triggered sessions."""

from unittest.mock import AsyncMock, patch

from agents.hapax_voice.config import VoiceConfig


class TestHotkeyChime:
    @patch("agents.hapax_voice.__main__._screen_flash")
    @patch("agents.hapax_voice.__main__.AudioInputStream")
    @patch("agents.hapax_voice.__main__.TTSManager")
    @patch("agents.hapax_voice.__main__.WakeWordDetector")
    @patch("agents.hapax_voice.__main__.HotkeyServer")
    @patch("agents.hapax_voice.__main__.ChimePlayer")
    def test_toggle_open_plays_activation(self, MockChime, *_, **__):
        import asyncio

        from agents.hapax_voice.__main__ import VoiceDaemon

        cfg = VoiceConfig(chime_enabled=True)
        daemon = VoiceDaemon(cfg=cfg)
        mock_player = MockChime.return_value
        daemon._start_pipeline = AsyncMock()

        # Toggle when not active should open and play chime
        asyncio.get_event_loop().run_until_complete(daemon._handle_hotkey("toggle"))
        mock_player.play.assert_called_with("activation")

    @patch("agents.hapax_voice.__main__._screen_flash")
    @patch("agents.hapax_voice.__main__.AudioInputStream")
    @patch("agents.hapax_voice.__main__.TTSManager")
    @patch("agents.hapax_voice.__main__.WakeWordDetector")
    @patch("agents.hapax_voice.__main__.HotkeyServer")
    @patch("agents.hapax_voice.__main__.ChimePlayer")
    def test_open_cmd_plays_activation(self, MockChime, *_, **__):
        import asyncio

        from agents.hapax_voice.__main__ import VoiceDaemon

        cfg = VoiceConfig(chime_enabled=True)
        daemon = VoiceDaemon(cfg=cfg)
        mock_player = MockChime.return_value
        daemon._start_pipeline = AsyncMock()

        asyncio.get_event_loop().run_until_complete(daemon._handle_hotkey("open"))
        mock_player.play.assert_called_with("activation")
