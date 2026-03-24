"""Tests for ConversationBuffer — VAD-gated audio accumulation.

Self-contained, unittest.mock only.
"""

from __future__ import annotations

import unittest

from agents.hapax_voice.conversation_buffer import (
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

    def test_no_accumulation_when_speaking(self):
        buf = ConversationBuffer()
        buf.activate()
        buf.set_speaking(True)
        for _ in range(10):
            buf.feed_audio(_frame())
            buf.update_vad(0.9)
        # Trigger silence
        for _ in range(SPEECH_END_DEFAULT + 1):
            buf.update_vad(0.1)
        assert buf.get_utterance() is None


class TestSpeechDetection(unittest.TestCase):
    def test_speech_start_requires_consecutive_frames(self):
        buf = ConversationBuffer()
        buf.activate()
        # Not enough consecutive speech frames
        buf.feed_audio(_frame())
        buf.update_vad(0.9)
        buf.feed_audio(_frame())
        buf.update_vad(0.1)  # breaks the streak
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
            buf.update_vad(0.1)
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
            buf.update_vad(0.1)
        assert buf.get_utterance() is not None
        assert buf.get_utterance() is None  # cleared

    def test_pre_roll_included(self):
        buf = ConversationBuffer()
        buf.activate()
        # Feed some frames before speech (pre-roll)
        for _ in range(15):
            buf.feed_audio(_frame())
            buf.update_vad(0.1)  # silence
        # Start speech
        for _ in range(SPEECH_START_CONSECUTIVE + 5):
            buf.feed_audio(_frame())
            buf.update_vad(0.9)
        # End speech
        for _ in range(SPEECH_END_DEFAULT + 1):
            buf.feed_audio(_frame())
            buf.update_vad(0.1)
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
        from agents.hapax_voice.resident_stt import ResidentSTT

        stt = ResidentSTT(model="tiny")
        assert not stt.is_loaded

    def test_transcribe_returns_empty_when_not_loaded(self):
        import asyncio

        from agents.hapax_voice.resident_stt import ResidentSTT

        stt = ResidentSTT(model="tiny")
        result = asyncio.get_event_loop().run_until_complete(stt.transcribe(b"\x00" * 1000))
        assert result == ""
