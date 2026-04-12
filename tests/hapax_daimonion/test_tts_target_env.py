"""HAPAX_TTS_TARGET env var routes TTS through a custom PipeWire sink.

Covers conversation_pipeline._open_audio_output — the single integration point
between the daimonion conversation loop and the voice FX filter-chain
(config/pipewire/voice-fx-chain.conf).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline


def _make_pipeline_stub() -> ConversationPipeline:
    """Return a ConversationPipeline with only the state _open_audio_output touches."""
    obj = object.__new__(ConversationPipeline)
    obj._audio_output = None  # type: ignore[attr-defined]
    return obj


class TestTtsTargetEnvVar:
    def test_default_routes_to_system_default_sink(self, monkeypatch):
        monkeypatch.delenv("HAPAX_TTS_TARGET", raising=False)
        pipeline = _make_pipeline_stub()
        mock_audio = MagicMock()
        with patch(
            "agents.hapax_daimonion.pw_audio_output.PwAudioOutput",
            return_value=mock_audio,
        ) as mock_cls:
            pipeline._open_audio_output()

        mock_cls.assert_called_once_with(sample_rate=24000, channels=1, target=None)
        assert pipeline._audio_output is mock_audio

    def test_env_var_routes_through_fx_sink(self, monkeypatch):
        monkeypatch.setenv("HAPAX_TTS_TARGET", "hapax-voice-fx-capture")
        pipeline = _make_pipeline_stub()
        with patch("agents.hapax_daimonion.pw_audio_output.PwAudioOutput") as mock_cls:
            pipeline._open_audio_output()

        mock_cls.assert_called_once_with(
            sample_rate=24000, channels=1, target="hapax-voice-fx-capture"
        )

    def test_empty_env_var_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("HAPAX_TTS_TARGET", "")
        pipeline = _make_pipeline_stub()
        with patch("agents.hapax_daimonion.pw_audio_output.PwAudioOutput") as mock_cls:
            pipeline._open_audio_output()

        mock_cls.assert_called_once_with(sample_rate=24000, channels=1, target=None)
