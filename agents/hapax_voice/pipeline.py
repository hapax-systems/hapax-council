"""Pipecat pipeline construction for the Hapax Voice daemon.

Builds a local voice pipeline:
  transport.input() -> STT -> user_aggregator -> LLM -> tts -> transport.output()

Or routes to Gemini Live when config.backend == "gemini".
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agents.hapax_voice.frame_gate import FrameGate

from openai import NOT_GIVEN
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.transports.local.audio import (
    LocalAudioTransport,
    LocalAudioTransportParams,
)

from agents.hapax_voice.persona import system_prompt
from agents.hapax_voice.pipecat_tts import VoxtralTTSService
from agents.hapax_voice.tts import VOXTRAL_SAMPLE_RATE

log = logging.getLogger(__name__)

# Input sample rate for mic capture (Whisper expects 16 kHz)
INPUT_SAMPLE_RATE = 16000


def _build_transport(
    input_rate: int = INPUT_SAMPLE_RATE,
    output_rate: int = VOXTRAL_SAMPLE_RATE,
) -> LocalAudioTransport:
    """Create a LocalAudioTransport configured for voice I/O.

    Args:
        input_rate: Mic capture sample rate in Hz. Default 16000.
        output_rate: Speaker playback sample rate in Hz. Default 24000 (Voxtral).

    Returns:
        Configured LocalAudioTransport.
    """
    params = LocalAudioTransportParams(
        audio_in_enabled=True,
        audio_in_sample_rate=input_rate,
        audio_out_enabled=True,
        audio_out_sample_rate=output_rate,
        vad_enabled=True,
        vad_analyzer=SileroVADAnalyzer(sample_rate=input_rate),
    )
    return LocalAudioTransport(params)


def _build_stt(model: str) -> WhisperSTTService:
    """Create a Whisper STT service.

    Uses faster-whisper on CUDA. Falls back to CPU if CUDA is unavailable.

    Args:
        model: Whisper model name (e.g. "large-v3", "base").

    Returns:
        Configured WhisperSTTService.
    """
    # If a NeMo parakeet model is requested, fall back to whisper large-v3
    # since Pipecat's WhisperSTTService only supports faster-whisper models.
    if model.startswith("nvidia/parakeet"):
        log.info(
            "Parakeet model %s not supported in Pipecat pipeline, "
            "falling back to faster-whisper large-v3",
            model,
        )
        model = "large-v3"

    return WhisperSTTService(
        model=model,
        device="cuda",
        compute_type="float16",
        no_speech_prob=0.4,
    )


def _build_llm(model: str, prompt: str) -> OpenAILLMService:
    """Create an OpenAI-compatible LLM service routed through LiteLLM.

    Args:
        model: Model alias (e.g. "claude-sonnet") routed by LiteLLM.
        prompt: System prompt for the conversation.

    Returns:
        Configured OpenAILLMService.
    """
    from agents.hapax_voice.config import LITELLM_BASE

    base_url = LITELLM_BASE
    api_key = os.environ.get("LITELLM_API_KEY", "not-set")

    return OpenAILLMService(
        model=model,
        api_key=api_key,
        base_url=base_url,
    )


def _build_tts(voice: str) -> VoxtralTTSService:
    """Create the Voxtral TTS service for Pipecat.

    Args:
        voice: Voxtral voice ID.

    Returns:
        Configured VoxtralTTSService.
    """
    return VoxtralTTSService(voice_id=voice)


def _build_context(prompt: str) -> LLMContext:
    """Create an LLM context with the system prompt pre-loaded.

    Args:
        prompt: System prompt describing the Hapax assistant persona.

    Returns:
        LLMContext with system message.
    """
    return LLMContext(
        messages=[{"role": "system", "content": prompt}],
    )


def build_pipeline_task(
    *,
    stt_model: str = "large-v3",
    llm_model: str = "claude-sonnet",
    voxtral_voice: str = "jessica",
    guest_mode: bool = False,
    config=None,
    webcam_capturer=None,
    screen_capturer=None,
    frame_gate: FrameGate | None = None,
) -> tuple[PipelineTask, LocalAudioTransport]:
    """Build a complete Pipecat pipeline task for local voice interaction.

    Constructs: transport.input() -> STT -> user_agg -> LLM -> assistant_agg -> TTS -> transport.output()

    Args:
        stt_model: STT model name for WhisperSTTService.
        llm_model: LLM model alias for LiteLLM routing.
        voxtral_voice: Voxtral voice ID for TTS.
        guest_mode: Whether the session is in guest mode (limited access).
        config: Optional VoiceConfig for tool registration.
        webcam_capturer: Optional WebcamCapturer for analyze_scene tool.
        screen_capturer: Optional ScreenCapturer for analyze_scene tool.

    Returns:
        Tuple of (PipelineTask, LocalAudioTransport). The transport is
        returned so the caller can manage its lifecycle.
    """
    prompt = system_prompt(guest_mode=guest_mode)

    transport = _build_transport()
    stt = _build_stt(stt_model)
    llm = _build_llm(llm_model, prompt)
    tts = _build_tts(voxtral_voice)

    # Register tool handlers and get schemas for the LLM context
    from agents.hapax_voice.tools import get_tool_schemas, register_tool_handlers

    tools = get_tool_schemas(guest_mode=guest_mode)
    if config is not None:
        register_tool_handlers(llm, config, webcam_capturer, screen_capturer)

    context = LLMContext(
        messages=[{"role": "system", "content": prompt}],
        tools=tools if tools is not None else NOT_GIVEN,
    )
    context_aggregator = LLMContextAggregatorPair(context)

    # Build processor chain, optionally inserting FrameGate before STT
    processors = [transport.input()]
    if frame_gate is not None:
        processors.append(frame_gate)
    processors.extend(
        [
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    pipeline = Pipeline(processors=processors)

    task = PipelineTask(pipeline)

    return task, transport
