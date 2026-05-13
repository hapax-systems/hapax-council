"""Conversation TTS output refuses legacy default/broadcast sink routing.

Covers conversation_pipeline._open_audio_output — the single integration point
between the daimonion conversation loop and the voice FX filter-chain
(config/pipewire/hapax-voice-fx-chain.conf).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.hapax_daimonion.conversation_pipeline import ConversationPipeline
from agents.hapax_daimonion.cpal.destination_channel import DestinationChannel
from agents.hapax_daimonion.pw_audio_output import PlaybackResult


def _make_pipeline_stub() -> ConversationPipeline:
    """Return a ConversationPipeline with only the state _open_audio_output touches."""
    obj = object.__new__(ConversationPipeline)
    obj._audio_output = None  # type: ignore[attr-defined]
    return obj


class TestTtsTargetEnvVar:
    def test_audio_output_opens_without_constructor_target(self, monkeypatch):
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

    def test_env_var_broadcast_target_is_ignored(self, monkeypatch):
        monkeypatch.setenv("HAPAX_TTS_TARGET", "hapax-voice-fx-capture")
        pipeline = _make_pipeline_stub()
        with patch("agents.hapax_daimonion.pw_audio_output.PwAudioOutput") as mock_cls:
            pipeline._open_audio_output()

        mock_cls.assert_called_once_with(sample_rate=24000, channels=1, target=None)

    def test_empty_env_var_is_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("HAPAX_TTS_TARGET", "")
        pipeline = _make_pipeline_stub()
        with patch("agents.hapax_daimonion.pw_audio_output.PwAudioOutput") as mock_cls:
            pipeline._open_audio_output()

        mock_cls.assert_called_once_with(sample_rate=24000, channels=1, target=None)


class TestConversationPipelineRoutedAudio:
    def test_unrouted_write_drops_without_default_sink(self):
        audio_output = MagicMock()
        pcm = b"\x00\x01" * 500

        ConversationPipeline._write_audio(audio_output, None, pcm)

        audio_output.write.assert_not_called()

    def test_routed_write_drops_if_audio_output_rejects_route_kwargs(self):
        class RejectingAudioOutput:
            def __init__(self):
                self.calls = []

            def write(self, pcm, **kwargs):
                self.calls.append((pcm, kwargs))
                if kwargs:
                    raise TypeError("route kwargs unsupported")

        audio_output = RejectingAudioOutput()
        pcm = b"\x00\x01" * 500

        ConversationPipeline._write_audio(
            audio_output,
            None,
            pcm,
            destination_target="hapax-private",
            destination_role="Assistant",
        )

        assert audio_output.calls == [(pcm, {"target": "hapax-private", "media_role": "Assistant"})]

    @pytest.mark.asyncio
    async def test_bridge_phrase_drops_when_default_route_is_blocked(self):
        pipeline = object.__new__(ConversationPipeline)
        pipeline._turn_model_tier = "STRONG"  # type: ignore[attr-defined]
        pipeline._last_assistant_end = 0.0  # type: ignore[attr-defined]
        pipeline._bridge_engine = MagicMock()  # type: ignore[attr-defined]
        pipeline._bridge_engine.select.return_value = ("one moment", b"\x00\x01")  # type: ignore[attr-defined]
        pipeline._salience_router = None  # type: ignore[attr-defined]
        pipeline.turn_count = 1  # type: ignore[attr-defined]
        pipeline._activity_mode = "listening"  # type: ignore[attr-defined]
        pipeline._consent_phase = "none"  # type: ignore[attr-defined]
        pipeline._session_id = "test-session"  # type: ignore[attr-defined]
        pipeline._audio_output = MagicMock()  # type: ignore[attr-defined]
        pipeline._echo_canceller = None  # type: ignore[attr-defined]
        pipeline._recent_tts_texts = []  # type: ignore[attr-defined]
        blocked_decision = SimpleNamespace(
            allowed=False,
            destination=DestinationChannel.PRIVATE,
            reason_code="private_monitor_status_missing",
            safety_gate={"context_default": "private_or_drop"},
            target=None,
            media_role=None,
        )

        with (
            patch(
                "agents.hapax_daimonion.cpal.destination_channel.resolve_playback_decision",
                return_value=blocked_decision,
            ),
            patch(
                "agents.hapax_daimonion.voice_output_witness.record_destination_decision"
            ) as record_decision,
            patch("agents.hapax_daimonion.voice_output_witness.record_drop") as record_drop,
        ):
            await pipeline._speak_bridge()

        pipeline._audio_output.write.assert_not_called()  # type: ignore[attr-defined]
        record_decision.assert_called_once()
        record_drop.assert_called_once()
        assert record_drop.call_args.kwargs["reason"] == "private_monitor_status_missing"

    @pytest.mark.asyncio
    async def test_canned_response_pcm_drops_when_default_route_is_blocked(self):
        pipeline = object.__new__(ConversationPipeline)
        pipeline._audio_output = MagicMock()  # type: ignore[attr-defined]
        pipeline._echo_canceller = None  # type: ignore[attr-defined]
        blocked_decision = SimpleNamespace(
            allowed=False,
            destination=DestinationChannel.PRIVATE,
            reason_code="private_monitor_status_missing",
            safety_gate={"context_default": "private_or_drop"},
            target=None,
            media_role=None,
        )

        with (
            patch(
                "agents.hapax_daimonion.cpal.destination_channel.resolve_playback_decision",
                return_value=blocked_decision,
            ),
            patch("agents.hapax_daimonion.voice_output_witness.record_destination_decision"),
            patch("agents.hapax_daimonion.voice_output_witness.record_drop") as record_drop,
        ):
            played = await pipeline._play_guarded_pcm(
                pcm=b"\x00\x01",
                text="canned",
                source="conversation_canned_response",
            )

        assert played is False
        pipeline._audio_output.write.assert_not_called()  # type: ignore[attr-defined]
        assert record_drop.call_args.kwargs["source"] == "conversation_canned_response"

    @pytest.mark.asyncio
    async def test_tool_bridge_phrase_drops_when_default_route_is_blocked(self):
        pipeline = object.__new__(ConversationPipeline)
        pipeline._bridge_engine = MagicMock()  # type: ignore[attr-defined]
        pipeline._bridge_engine.select.return_value = ("checking", b"\x00\x01")  # type: ignore[attr-defined]
        pipeline._audio_output = MagicMock()  # type: ignore[attr-defined]
        pipeline._echo_canceller = None  # type: ignore[attr-defined]
        pipeline.turn_count = 2  # type: ignore[attr-defined]
        pipeline._session_id = "test-session"  # type: ignore[attr-defined]
        pipeline.messages = []  # type: ignore[attr-defined]
        pipeline.tool_handlers = {}  # type: ignore[attr-defined]
        pipeline._consent_reader = None  # type: ignore[attr-defined]
        pipeline._tool_recruitment_gate = None  # type: ignore[attr-defined]
        pipeline._generate_and_speak = AsyncMock()  # type: ignore[method-assign]
        blocked_decision = SimpleNamespace(
            allowed=False,
            destination=DestinationChannel.PRIVATE,
            reason_code="private_monitor_status_missing",
            safety_gate={"context_default": "private_or_drop"},
            target=None,
            media_role=None,
        )

        with (
            patch(
                "agents.hapax_daimonion.cpal.destination_channel.resolve_playback_decision",
                return_value=blocked_decision,
            ),
            patch("agents.hapax_daimonion.voice_output_witness.record_destination_decision"),
            patch("agents.hapax_daimonion.voice_output_witness.record_drop") as record_drop,
        ):
            await pipeline._handle_tool_calls([], "")

        pipeline._audio_output.write.assert_not_called()  # type: ignore[attr-defined]
        assert record_drop.call_args.kwargs["source"] == "conversation_tool_bridge"

    @pytest.mark.asyncio
    async def test_routed_spontaneous_sentence_records_tts_and_playback_witness(self):
        pipeline = object.__new__(ConversationPipeline)
        pipeline._running = True  # type: ignore[attr-defined]
        pipeline._current_envelope = None  # type: ignore[attr-defined]
        pipeline._recent_tts_texts = []  # type: ignore[attr-defined]
        pipeline._max_tts_history = 5  # type: ignore[attr-defined]
        pipeline.tts = SimpleNamespace(synthesize=MagicMock(return_value=b"\x00\x01" * 120))  # type: ignore[attr-defined]
        pipeline._echo_canceller = None  # type: ignore[attr-defined]
        pipeline._audio_output = MagicMock()  # type: ignore[attr-defined]
        pipeline._audio_output.write.return_value = PlaybackResult(  # type: ignore[attr-defined]
            status="completed",
            returncode=0,
            duration_s=0.005,
            timeout_s=0.005,
            target="hapax-private",
            media_role="Assistant",
        )

        with (
            patch("agents.hapax_daimonion.voice_output_witness.record_tts_synthesis") as record_tts,
            patch(
                "agents.hapax_daimonion.voice_output_witness.record_playback_result"
            ) as record_playback,
        ):
            spoken = await pipeline._speak_sentence(
                "Private routed sentence.",
                destination_target="hapax-private",
                destination_role="Assistant",
                destination="private",
            )
            for _ in range(20):
                if record_playback.called:
                    break
                await asyncio.sleep(0.01)

        assert spoken == "Private routed sentence."
        record_tts.assert_called_once()
        assert record_tts.call_args.kwargs["status"] == "completed"
        record_playback.assert_called_once()
        assert record_playback.call_args.kwargs["destination"] == "private"
        assert record_playback.call_args.kwargs["target"] == "hapax-private"
        assert record_playback.call_args.kwargs["media_role"] == "Assistant"
