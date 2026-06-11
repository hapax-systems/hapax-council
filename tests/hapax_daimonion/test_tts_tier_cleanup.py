"""Tests for TTS tier map after chime cleanup.

The tier map names chatterbox since the Chatterbox-primary swap; these
asserts were stale (pre-existing failures) until the 2026-06 voice
foundation truth pass.
"""

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
        assert select_tier("conversation") == "chatterbox"

    def test_notification_tier_unchanged(self):
        assert select_tier("notification") == "chatterbox"

    def test_unknown_tier_defaults_chatterbox(self):
        assert select_tier("unknown_use_case") == "chatterbox"
