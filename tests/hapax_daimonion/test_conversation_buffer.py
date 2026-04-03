"""Tests for ConversationBuffer — continuous audio accumulation.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import unittest

from agents.hapax_daimonion.conversation_buffer import (
    SPEECH_END_DEFAULT,
    SPEECH_START_CONSECUTIVE,
    ConversationBuffer,
)


def _frame(n: int = 480) -> bytes:
    """Generate a dummy 30ms frame (480 samples × 2 bytes)."""
    return b"\x00" * (n * 2)


class TestConversationBufferBasic(unittest.TestCase):
    def test_inactive_by_default(self):
        buf = ConversationBuffer()
        assert not buf.is_active

    def test_activate_deactivate(self):
        buf = ConversationBuffer()
        buf.activate()
        assert buf.is_active
        buf.deactivate()
        assert not buf.is_active

    def test_no_accumulation_when_inactive(self):
        buf = ConversationBuffer()
        buf.feed_audio(_frame())
        buf.update_vad(0.9)
        assert buf.get_utterance() is None

    def test_low_vad_during_speaking_does_not_trigger_speech(self):
        """During system speech, probability 0.9 is below the 0.8 adaptive threshold
        when fewer than 7 consecutive frames are seen — but actually 0.9 >= 0.8 so
        speech CAN be detected. This test verifies the higher threshold (0.5) blocks."""
        buf = ConversationBuffer()
        buf.activate()
        buf.set_speaking(True)
        for _ in range(10):
            buf.feed_audio(_frame())
            buf.update_vad(0.5)  # below adaptive 0.8 threshold during speech
        # Trigger silence
        for _ in range(SPEECH_END_DEFAULT + 1):
            buf.update_vad(0.05)
        assert buf.get_utterance() is None


class TestSpeechDetection(unittest.TestCase):
    def test_speech_start_requires_consecutive_frames(self):
        buf = ConversationBuffer()
        buf.activate()
        # Not enough consecutive speech frames
        buf.feed_audio(_frame())
        buf.update_vad(0.9)
        buf.feed_audio(_frame())
        buf.update_vad(0.05)  # breaks the streak
        buf.feed_audio(_frame())
        buf.update_vad(0.9)
        # No utterance should be pending
        assert buf.get_utterance() is None

    def test_speech_detected_after_consecutive(self):
        buf = ConversationBuffer()
        buf.activate()
        # Trigger speech start
        for _ in range(SPEECH_START_CONSECUTIVE + 5):
            buf.feed_audio(_frame())
            buf.update_vad(0.9)
        # Trigger speech end
        for _ in range(SPEECH_END_DEFAULT + 1):
            buf.feed_audio(_frame())
            buf.update_vad(0.05)
        utterance = buf.get_utterance()
        assert utterance is not None
        assert len(utterance) > 0

    def test_utterance_cleared_after_get(self):
        buf = ConversationBuffer()
        buf.activate()
        for _ in range(SPEECH_START_CONSECUTIVE + 5):
            buf.feed_audio(_frame())
            buf.update_vad(0.9)
        for _ in range(SPEECH_END_DEFAULT + 1):
            buf.feed_audio(_frame())
            buf.update_vad(0.05)
        assert buf.get_utterance() is not None
        assert buf.get_utterance() is None  # cleared

    def test_pre_roll_included(self):
        buf = ConversationBuffer()
        buf.activate()
        # Feed some frames before speech (pre-roll)
        for _ in range(15):
            buf.feed_audio(_frame())
            buf.update_vad(0.05)  # silence
        # Start speech
        for _ in range(SPEECH_START_CONSECUTIVE + 5):
            buf.feed_audio(_frame())
            buf.update_vad(0.9)
        # End speech
        for _ in range(SPEECH_END_DEFAULT + 1):
            buf.feed_audio(_frame())
            buf.update_vad(0.05)
        utterance = buf.get_utterance()
        assert utterance is not None
        # Should be longer than just the speech frames due to pre-roll
        speech_only = (SPEECH_START_CONSECUTIVE + 5) * 480 * 2
        assert len(utterance) > speech_only

    def test_max_duration_caps(self):
        buf = ConversationBuffer(max_duration_s=0.5)  # ~16 frames
        buf.activate()
        for _ in range(SPEECH_START_CONSECUTIVE):
            buf.feed_audio(_frame())
            buf.update_vad(0.9)
        # Keep speaking beyond max
        for _ in range(100):
            buf.feed_audio(_frame())
            buf.update_vad(0.9)
        # Should have auto-emitted
        assert buf.get_utterance() is not None

    def test_reset_on_deactivate(self):
        buf = ConversationBuffer()
        buf.activate()
        for _ in range(SPEECH_START_CONSECUTIVE + 5):
            buf.feed_audio(_frame())
            buf.update_vad(0.9)
        buf.deactivate()
        assert buf.get_utterance() is None


class TestResidentSTTInterface(unittest.TestCase):
    """Verify ResidentSTT interface (mock model)."""

    def test_not_loaded_by_default(self):
        from agents.hapax_daimonion.resident_stt import ResidentSTT

        stt = ResidentSTT(model="tiny")
        assert not stt.is_loaded

    def test_transcribe_returns_empty_when_not_loaded(self):
        import asyncio

        from agents.hapax_daimonion.resident_stt import ResidentSTT

        stt = ResidentSTT(model="tiny")
        result = asyncio.get_event_loop().run_until_complete(stt.transcribe(b"\x00" * 1000))
        assert result == ""


class TestAdaptiveVad:
    """Tests for continuous perception — no _speaking gate."""

    def test_vad_updates_during_speaking(self):
        """VAD must process during system speech (was gated before)."""
        buf = ConversationBuffer()
        buf.activate()
        buf.set_speaking(True)
        for _ in range(10):
            buf.update_vad(0.9)
        assert buf.speech_active

    def test_vad_requires_higher_threshold_during_speaking(self):
        """During system speech, VAD threshold rises to 0.8."""
        buf = ConversationBuffer()
        buf.activate()
        buf.set_speaking(True)
        for _ in range(10):
            buf.update_vad(0.5)
        assert not buf.speech_active

    def test_frames_accumulated_during_speaking(self):
        """Audio frames must accumulate during system speech."""
        buf = ConversationBuffer()
        buf.activate()
        buf.set_speaking(True)
        for _ in range(10):
            buf.update_vad(0.9)
        for _ in range(5):
            buf.feed_audio(b"\x01\x00" * 480)
        assert len(buf._speech_frames) >= 5

    def test_no_cooldown_property(self):
        """Cooldown mechanism must be removed entirely."""
        buf = ConversationBuffer()
        assert not hasattr(buf, "_dynamic_cooldown_s")
