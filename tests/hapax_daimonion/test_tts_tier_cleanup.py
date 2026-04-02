"""Tests for TTS tier map after chime cleanup — Kokoro backend."""

from agents.hapax_daimonion.tts import _TIER_MAP, select_tier


class TestTierMapCleanup:
    def test_no_chime_tier(self):
        """Chime is handled by ChimePlayer, not TTS."""
        assert "chime" not in _TIER_MAP

    def test_no_short_ack_tier(self):
        """Short acks are LLM-driven verbal, not a TTS tier."""
        assert "short_ack" not in _TIER_MAP

    def test_no_confirmation_tier(self):
        """Confirmations are LLM-driven verbal, not a TTS tier."""
        assert "confirmation" not in _TIER_MAP

    def test_conversation_tier_unchanged(self):
        assert select_tier("conversation") == "kokoro"

    def test_notification_tier_unchanged(self):
        assert select_tier("notification") == "kokoro"

    def test_unknown_tier_defaults_kokoro(self):
        assert select_tier("unknown_use_case") == "kokoro"
