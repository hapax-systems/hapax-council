"""tests/hapax_daimonion/test_audio_perception.py"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.audio_perception import AudioPerceptionBackend


class TestAudioPerceptionBackend:
    def _make_backend(self):
        stt = MagicMock()
        stt.transcribe = AsyncMock(return_value="hello hapax")
        stt.is_loaded = True
        speaker_id = MagicMock()
        speaker_id.identify.return_value = ("operator", 0.92)
        return AudioPerceptionBackend(stt=stt, speaker_id=speaker_id)

    def test_provides_audio_behaviors(self):
        backend = self._make_backend()
        assert "speech_detected" in backend.provides
        assert "audio_event" in backend.provides

    def test_name(self):
        backend = self._make_backend()
        assert backend.name == "audio"

    @pytest.mark.asyncio
    async def test_operator_speech_emits_impingement(self):
        backend = self._make_backend()
        backend.start()
        backend._emit_speech_impingement(
            transcript="hello hapax",
            speaker="operator",
            speaker_confidence=0.92,
            vad_confidence=0.95,
            duration_s=1.2,
            energy_db=-14.0,
        )
        imps = backend.drain_impingements()
        assert len(imps) == 1
        imp = imps[0]
        assert imp["source"] == "audio.operator_speech"
        assert imp["type"] == "pattern_match"
        assert imp["strength"] >= 0.85
        assert imp["content"]["transcript"] == "hello hapax"
        assert imp["content"]["speaker"] == "operator"

    @pytest.mark.asyncio
    async def test_non_operator_speech_lower_strength(self):
        backend = self._make_backend()
        backend.start()
        backend._emit_speech_impingement(
            transcript="some guest talking",
            speaker="unknown",
            speaker_confidence=0.3,
            vad_confidence=0.90,
            duration_s=2.0,
            energy_db=-18.0,
        )
        imps = backend.drain_impingements()
        assert len(imps) == 1
        assert imps[0]["source"] == "audio.scene"
        assert imps[0]["strength"] < 0.5

    @pytest.mark.asyncio
    async def test_strength_is_vad_times_speaker_posterior(self):
        backend = self._make_backend()
        backend.start()
        backend._emit_speech_impingement(
            transcript="test",
            speaker="operator",
            speaker_confidence=0.80,
            vad_confidence=0.90,
            duration_s=1.0,
            energy_db=-12.0,
        )
        imps = backend.drain_impingements()
        assert abs(imps[0]["strength"] - 0.72) < 0.01

    def test_drain_clears_queue(self):
        backend = self._make_backend()
        backend.start()
        backend._emit_speech_impingement(
            transcript="a",
            speaker="operator",
            speaker_confidence=0.9,
            vad_confidence=0.9,
            duration_s=1.0,
            energy_db=-12.0,
        )
        assert len(backend.drain_impingements()) == 1
        assert len(backend.drain_impingements()) == 0
