"""Tests for Pipecat pipeline construction."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from agents.hapax_voice.pipeline import (
    INPUT_SAMPLE_RATE,
    _build_context,
    _build_transport,
)
from agents.hapax_voice.tts import KOKORO_SAMPLE_RATE


class TestBuildTransport:
    """Tests for _build_transport helper."""

    @patch("agents.hapax_voice.pipeline.SileroVADAnalyzer")
    @patch("agents.hapax_voice.pipeline.LocalAudioTransport")
    @patch("agents.hapax_voice.pipeline.LocalAudioTransportParams")
    def test_default_sample_rates(self, mock_params_cls, mock_transport_cls, mock_vad) -> None:
        mock_params_cls.return_value = "params"
        mock_transport_cls.return_value = "transport"
        mock_vad.return_value = "vad_analyzer"

        result = _build_transport()

        mock_params_cls.assert_called_once_with(
            audio_in_enabled=True,
            audio_in_sample_rate=INPUT_SAMPLE_RATE,
            audio_out_enabled=True,
            audio_out_sample_rate=KOKORO_SAMPLE_RATE,
            vad_enabled=True,
            vad_analyzer="vad_analyzer",
        )
        mock_transport_cls.assert_called_once_with("params")
        assert result == "transport"

    @patch("agents.hapax_voice.pipeline.SileroVADAnalyzer")
    @patch("agents.hapax_voice.pipeline.LocalAudioTransport")
    @patch("agents.hapax_voice.pipeline.LocalAudioTransportParams")
    def test_custom_sample_rates(self, mock_params_cls, mock_transport_cls, mock_vad) -> None:
        mock_vad.return_value = "vad_analyzer"
        _build_transport(input_rate=8000, output_rate=22050)
        mock_params_cls.assert_called_once_with(
            audio_in_enabled=True,
            audio_in_sample_rate=8000,
            audio_out_enabled=True,
            audio_out_sample_rate=22050,
            vad_enabled=True,
            vad_analyzer="vad_analyzer",
        )


class TestBuildContext:
    """Tests for _build_context helper."""

    def test_context_has_system_message(self) -> None:
        ctx = _build_context("You are Hapax.")
        msgs = ctx.get_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"
        assert "You are Hapax." in str(msgs[0]["content"])


class TestBuildPipelineTask:
    """Tests for the full build_pipeline_task function."""

    @patch("agents.hapax_voice.pipeline._build_transport")
    @patch("agents.hapax_voice.pipeline._build_stt")
    @patch("agents.hapax_voice.pipeline._build_llm")
    @patch("agents.hapax_voice.pipeline._build_tts")
    @patch("agents.hapax_voice.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_voice.pipeline.Pipeline")
    @patch("agents.hapax_voice.pipeline.PipelineTask")
    def test_returns_task_and_transport(
        self,
        mock_pipeline_task_cls,
        mock_pipeline_cls,
        mock_agg_pair_cls,
        mock_tts,
        mock_llm,
        mock_stt,
        mock_transport,
    ) -> None:
        from agents.hapax_voice.pipeline import build_pipeline_task

        mock_transport_inst = MagicMock()
        mock_transport_inst.input.return_value = "input_proc"
        mock_transport_inst.output.return_value = "output_proc"
        mock_transport.return_value = mock_transport_inst

        mock_stt.return_value = "stt_proc"
        mock_llm.return_value = MagicMock()
        mock_tts.return_value = "tts_proc"

        mock_agg = MagicMock()
        mock_agg.user.return_value = "user_agg"
        mock_agg.assistant.return_value = "assistant_agg"
        mock_agg_pair_cls.return_value = mock_agg

        mock_pipeline_cls.return_value = "pipeline"
        mock_pipeline_task_cls.return_value = "task"

        with patch("agents.hapax_voice.pipeline.LLMContext") as mock_ctx:
            mock_ctx.return_value = MagicMock()
            task, transport = build_pipeline_task(
                stt_model="base",
                llm_model="test-model",
                kokoro_voice="af_heart",
                guest_mode=False,
            )

        assert task == "task"
        assert transport == mock_transport_inst
        mock_stt.assert_called_once_with("base")
        mock_llm.assert_called_once()
        mock_tts.assert_called_once_with("af_heart")

    @patch("agents.hapax_voice.pipeline._build_transport")
    @patch("agents.hapax_voice.pipeline._build_stt")
    @patch("agents.hapax_voice.pipeline._build_llm")
    @patch("agents.hapax_voice.pipeline._build_tts")
    @patch("agents.hapax_voice.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_voice.pipeline.Pipeline")
    @patch("agents.hapax_voice.pipeline.PipelineTask")
    def test_guest_mode_uses_guest_prompt(
        self,
        mock_pipeline_task_cls,
        mock_pipeline_cls,
        mock_agg_pair_cls,
        mock_tts,
        mock_llm,
        mock_stt,
        mock_transport,
    ) -> None:
        from agents.hapax_voice.pipeline import build_pipeline_task

        mock_transport_inst = MagicMock()
        mock_transport.return_value = mock_transport_inst
        mock_stt.return_value = "stt"
        mock_llm.return_value = MagicMock()
        mock_tts.return_value = "tts"
        mock_agg_pair_cls.return_value = MagicMock()
        mock_pipeline_cls.return_value = "pipeline"
        mock_pipeline_task_cls.return_value = "task"

        with (
            patch("agents.hapax_voice.pipeline.system_prompt") as mock_prompt,
            patch("agents.hapax_voice.pipeline.LLMContext") as mock_ctx,
        ):
            mock_prompt.return_value = "guest prompt"
            mock_ctx.return_value = MagicMock()
            build_pipeline_task(guest_mode=True)
            mock_prompt.assert_called_once_with(guest_mode=True)


class TestBuildSTT:
    """Tests for _build_stt helper."""

    @patch("agents.hapax_voice.pipeline.WhisperSTTService")
    def test_parakeet_falls_back_to_whisper(self, mock_whisper) -> None:
        from agents.hapax_voice.pipeline import _build_stt

        _build_stt("nvidia/parakeet-tdt-0.6b-v2")
        mock_whisper.assert_called_once_with(
            model="large-v3",
            device="cuda",
            compute_type="float16",
            no_speech_prob=0.4,
        )

    @patch("agents.hapax_voice.pipeline.WhisperSTTService")
    def test_whisper_model_passed_directly(self, mock_whisper) -> None:
        from agents.hapax_voice.pipeline import _build_stt

        _build_stt("base")
        mock_whisper.assert_called_once_with(
            model="base",
            device="cuda",
            compute_type="float16",
            no_speech_prob=0.4,
        )


def test_frame_gate_inserted_before_stt():
    """When a FrameGate is provided, it appears before STT in pipeline."""
    from agents.hapax_voice.frame_gate import FrameGate

    gate = FrameGate()

    with (
        patch("agents.hapax_voice.pipeline.LocalAudioTransport") as MockTransport,
        patch("agents.hapax_voice.pipeline.WhisperSTTService") as MockSTT,
        patch("agents.hapax_voice.pipeline.OpenAILLMService") as MockLLM,
        patch("agents.hapax_voice.pipeline.KokoroTTSService") as MockTTS,
        patch("agents.hapax_voice.pipeline.LLMContext") as MockContext,
        patch("agents.hapax_voice.pipeline.LLMContextAggregatorPair") as MockAggPair,
        patch("agents.hapax_voice.pipeline.Pipeline") as MockPipeline,
        patch("agents.hapax_voice.pipeline.PipelineTask") as MockTask,
        patch("agents.hapax_voice.pipeline.system_prompt", return_value="test"),
    ):
        mock_transport = MockTransport.return_value
        mock_transport.input.return_value = MagicMock()
        mock_transport.output.return_value = MagicMock()
        MockContext.return_value = MagicMock()
        MockAggPair.return_value = MagicMock()

        with (
            patch("agents.hapax_voice.tools.get_tool_schemas", return_value=None),
            patch("agents.hapax_voice.tools.register_tool_handlers"),
        ):
            from agents.hapax_voice.pipeline import build_pipeline_task
            build_pipeline_task(frame_gate=gate)

        # Check the processors list passed to Pipeline
        call_kwargs = MockPipeline.call_args
        processors = call_kwargs.kwargs["processors"]

        # Find positions
        gate_idx = processors.index(gate)
        stt_idx = next(i for i, p in enumerate(processors) if p == MockSTT.return_value)
        assert gate_idx < stt_idx, "FrameGate must be before STT"
