"""Tests for CPAL production stream."""

from unittest.mock import MagicMock

from agents.hapax_daimonion.cpal.production_stream import ProductionStream
from agents.hapax_daimonion.cpal.types import CorrectionTier


class TestProductionStream:
    def _make_stream(self):
        audio_output = MagicMock()
        shm_writer = MagicMock()
        return (
            ProductionStream(audio_output=audio_output, shm_writer=shm_writer),
            audio_output,
            shm_writer,
        )

    def test_initial_state(self):
        ps, _, _ = self._make_stream()
        assert not ps.is_producing
        assert ps.current_tier is None

    def test_produce_t0_visual(self):
        ps, _, shm = self._make_stream()
        ps.produce_t0(signal_type="attentional_shift", intensity=0.7)
        shm.assert_called_once()
        assert not ps.is_producing

    def test_produce_t1_writes_audio(self):
        ps, audio, _ = self._make_stream()
        pcm = b"\x00\x01" * 500
        ps.produce_t1(pcm_data=pcm)
        audio.write.assert_called_once_with(pcm)

    def test_routed_t1_drops_if_audio_output_rejects_target(self):
        class RejectingAudioOutput:
            def __init__(self):
                self.calls = []

            def write(self, pcm_data, **kwargs):
                self.calls.append((pcm_data, kwargs))
                if kwargs:
                    raise TypeError("target kwargs unsupported")

        audio = RejectingAudioOutput()
        ps = ProductionStream(audio_output=audio, shm_writer=MagicMock())
        pcm = b"\x00\x01" * 500

        ps.produce_t1(pcm_data=pcm, destination_target="hapax-private")

        assert audio.calls == [(pcm, {"target": "hapax-private"})]

    def test_interrupt_stops_production(self):
        ps, _, _ = self._make_stream()
        ps._producing = True
        ps._current_tier = CorrectionTier.T3_FULL_FORMULATION
        ps.interrupt()
        assert not ps.is_producing
        assert ps.current_tier is None

    def test_interrupt_when_idle_is_noop(self):
        ps, _, _ = self._make_stream()
        ps.interrupt()
        assert not ps.is_producing

    def test_yield_to_operator(self):
        ps, _, _ = self._make_stream()
        ps._producing = True
        ps.yield_to_operator()
        assert not ps.is_producing
