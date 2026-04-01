"""Tests for CPAL perception stream."""

import struct
from unittest.mock import MagicMock

from agents.hapax_daimonion.cpal.perception_stream import PerceptionSignals, PerceptionStream


class TestPerceptionSignals:
    def test_default_signals(self):
        s = PerceptionSignals()
        assert s.vad_confidence == 0.0
        assert s.speech_active is False
        assert s.speech_duration_s == 0.0
        assert s.is_speaking is False
        assert s.energy_rms == 0.0
        assert s.trp_probability == 0.0

    def test_signals_are_frozen(self):
        s = PerceptionSignals()
        try:
            s.vad_confidence = 0.5
            raise AssertionError("Should be frozen")
        except (AttributeError, TypeError):
            pass


class TestPerceptionStream:
    def _make_stream(self):
        buffer = MagicMock()
        buffer.speech_active = False
        buffer.speech_duration_s = 0.0
        buffer.is_speaking = False
        return PerceptionStream(buffer=buffer), buffer

    def test_initial_signals(self):
        stream, _ = self._make_stream()
        s = stream.signals
        assert s.vad_confidence == 0.0
        assert s.trp_probability == 0.0

    def test_update_reads_buffer(self):
        stream, buf = self._make_stream()
        buf.speech_active = True
        buf.speech_duration_s = 2.5
        buf.is_speaking = False
        silence_frame = b"\x00\x00" * 480
        stream.update(silence_frame, vad_prob=0.8)
        s = stream.signals
        assert s.vad_confidence == 0.8
        assert s.speech_active is True
        assert s.speech_duration_s == 2.5

    def test_energy_from_pcm(self):
        stream, buf = self._make_stream()
        samples = [1000] * 480
        frame = struct.pack(f"<{len(samples)}h", *samples)
        stream.update(frame, vad_prob=0.0)
        assert stream.signals.energy_rms > 0.0

    def test_trp_rises_on_speech_end(self):
        stream, buf = self._make_stream()
        buf.speech_active = True
        stream.update(b"\x00\x00" * 480, vad_prob=0.8)
        assert stream.signals.trp_probability == 0.0
        buf.speech_active = False
        stream.update(b"\x00\x00" * 480, vad_prob=0.05)
        assert stream.signals.trp_probability >= 0.5

    def test_trp_decays_in_silence(self):
        stream, buf = self._make_stream()
        buf.speech_active = True
        stream.update(b"\x00\x00" * 480, vad_prob=0.8)
        buf.speech_active = False
        stream.update(b"\x00\x00" * 480, vad_prob=0.05)
        trp_initial = stream.signals.trp_probability
        for _ in range(10):
            stream.update(b"\x00\x00" * 480, vad_prob=0.02)
        assert stream.signals.trp_probability < trp_initial

    def test_trp_resets_on_new_speech(self):
        stream, buf = self._make_stream()
        buf.speech_active = True
        stream.update(b"\x00\x00" * 480, vad_prob=0.8)
        buf.speech_active = False
        stream.update(b"\x00\x00" * 480, vad_prob=0.05)
        assert stream.signals.trp_probability > 0.0
        buf.speech_active = True
        stream.update(b"\x00\x00" * 480, vad_prob=0.7)
        assert stream.signals.trp_probability == 0.0

    def test_utterance_passthrough(self):
        stream, buf = self._make_stream()
        buf.get_utterance.return_value = b"\x01\x02" * 100
        assert stream.get_utterance() == b"\x01\x02" * 100

    def test_utterance_none_when_empty(self):
        stream, buf = self._make_stream()
        buf.get_utterance.return_value = None
        assert stream.get_utterance() is None
