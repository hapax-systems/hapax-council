"""Surface 2: STT → LLM → TTS voice round-trip.

Tests that pipeline construction wires processors in the correct order
and that each component receives the right configuration. Full audio
round-trip requires live hardware — see smoke_test_voice.sh.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agents.hapax_daimonion.pipeline import build_pipeline_task


class TestPipelineWiring:
    """Pipeline processors are wired in the correct order."""

    @patch("agents.hapax_daimonion.pipeline.LocalAudioTransport")
    @patch("agents.hapax_daimonion.pipeline.WhisperSTTService")
    @patch("agents.hapax_daimonion.pipeline.OpenAILLMService")
    @patch("agents.hapax_daimonion.pipeline.VoxtralTTSService")
    @patch("agents.hapax_daimonion.pipeline.LLMContext")
    @patch("agents.hapax_daimonion.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_daimonion.pipeline.Pipeline")
    @patch("agents.hapax_daimonion.pipeline.PipelineTask")
    def test_processor_order(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair_cls,
        mock_ctx_cls,
        mock_tts_cls,
        mock_llm_cls,
        mock_stt_cls,
        mock_transport_cls,
    ):
        """Processors must be: input → STT → user_agg → LLM → TTS → output → assistant_agg."""
        mock_transport = MagicMock()
        mock_transport_cls.return_value = mock_transport
        mock_agg = MagicMock()
        mock_agg_pair_cls.return_value = mock_agg

        build_pipeline_task(
            stt_model="base",
            llm_model="test",
            voxtral_voice="jessica",
        )

        call_kwargs = mock_pipeline_cls.call_args.kwargs
        processors = call_kwargs["processors"]

        assert processors[0] == mock_transport.input()  # transport input
        assert processors[1] == mock_stt_cls()  # STT
        assert processors[2] == mock_agg.user()  # user aggregator
        assert processors[3] == mock_llm_cls()  # LLM
        assert processors[4] == mock_tts_cls()  # TTS
        assert processors[5] == mock_transport.output()  # transport output
        assert processors[6] == mock_agg.assistant()  # assistant aggregator

    @patch("agents.hapax_daimonion.pipeline.LocalAudioTransport")
    @patch("agents.hapax_daimonion.pipeline.WhisperSTTService")
    @patch("agents.hapax_daimonion.pipeline.OpenAILLMService")
    @patch("agents.hapax_daimonion.pipeline.VoxtralTTSService")
    @patch("agents.hapax_daimonion.pipeline.LLMContext")
    @patch("agents.hapax_daimonion.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_daimonion.pipeline.Pipeline")
    @patch("agents.hapax_daimonion.pipeline.PipelineTask")
    def test_frame_gate_inserted_when_provided(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair_cls,
        mock_ctx_cls,
        mock_tts_cls,
        mock_llm_cls,
        mock_stt_cls,
        mock_transport_cls,
    ):
        """When frame_gate is provided, it is inserted between input and STT."""
        mock_transport = MagicMock()
        mock_transport_cls.return_value = mock_transport
        mock_agg = MagicMock()
        mock_agg_pair_cls.return_value = mock_agg

        mock_gate = MagicMock()
        build_pipeline_task(
            stt_model="base",
            llm_model="test",
            frame_gate=mock_gate,
        )

        call_kwargs = mock_pipeline_cls.call_args.kwargs
        processors = call_kwargs["processors"]

        assert processors[0] == mock_transport.input()  # transport input
        assert processors[1] == mock_gate  # frame gate
        assert processors[2] == mock_stt_cls()  # STT
        assert len(processors) == 8

    @patch("agents.hapax_daimonion.pipeline.LocalAudioTransport")
    @patch("agents.hapax_daimonion.pipeline.WhisperSTTService")
    @patch("agents.hapax_daimonion.pipeline.OpenAILLMService")
    @patch("agents.hapax_daimonion.pipeline.VoxtralTTSService")
    @patch("agents.hapax_daimonion.pipeline.LLMContext")
    @patch("agents.hapax_daimonion.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_daimonion.pipeline.Pipeline")
    @patch("agents.hapax_daimonion.pipeline.PipelineTask")
    def test_stt_model_forwarded(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair_cls,
        mock_ctx_cls,
        mock_tts_cls,
        mock_llm_cls,
        mock_stt_cls,
        mock_transport_cls,
    ):
        """STT model name is passed through to WhisperSTTService."""
        mock_transport_cls.return_value = MagicMock()
        mock_agg_pair_cls.return_value = MagicMock()

        build_pipeline_task(stt_model="large-v3")

        mock_stt_cls.assert_called_once_with(
            model="large-v3",
            device="cuda",
            compute_type="float16",
            no_speech_prob=0.4,
        )

    @patch("agents.hapax_daimonion.pipeline.LocalAudioTransport")
    @patch("agents.hapax_daimonion.pipeline.WhisperSTTService")
    @patch("agents.hapax_daimonion.pipeline.OpenAILLMService")
    @patch("agents.hapax_daimonion.pipeline.VoxtralTTSService")
    @patch("agents.hapax_daimonion.pipeline.LLMContext")
    @patch("agents.hapax_daimonion.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_daimonion.pipeline.Pipeline")
    @patch("agents.hapax_daimonion.pipeline.PipelineTask")
    def test_llm_uses_litellm_config(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair_cls,
        mock_ctx_cls,
        mock_tts_cls,
        mock_llm_cls,
        mock_stt_cls,
        mock_transport_cls,
    ):
        """LLM service is configured with LiteLLM base URL and API key."""
        mock_transport_cls.return_value = MagicMock()
        mock_agg_pair_cls.return_value = MagicMock()

        with (
            patch(
                "agents.hapax_daimonion.config.LITELLM_BASE",
                "http://127.0.0.1:4000",
            ),
            patch.dict("os.environ", {"LITELLM_API_KEY": "test-key"}),
        ):
            build_pipeline_task(llm_model="claude-sonnet")

        mock_llm_cls.assert_called_once_with(
            model="claude-sonnet",
            api_key="test-key",
            base_url="http://127.0.0.1:4000",
        )

    @patch("agents.hapax_daimonion.pipeline.LocalAudioTransport")
    @patch("agents.hapax_daimonion.pipeline.WhisperSTTService")
    @patch("agents.hapax_daimonion.pipeline.OpenAILLMService")
    @patch("agents.hapax_daimonion.pipeline.VoxtralTTSService")
    @patch("agents.hapax_daimonion.pipeline.LLMContext")
    @patch("agents.hapax_daimonion.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_daimonion.pipeline.Pipeline")
    @patch("agents.hapax_daimonion.pipeline.PipelineTask")
    def test_tools_registered_in_context(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair_cls,
        mock_ctx_cls,
        mock_tts_cls,
        mock_llm_cls,
        mock_stt_cls,
        mock_transport_cls,
    ):
        """LLMContext receives tool schemas when not in guest mode."""
        mock_transport_cls.return_value = MagicMock()
        mock_agg_pair_cls.return_value = MagicMock()

        build_pipeline_task(guest_mode=False)

        ctx_call = mock_ctx_cls.call_args
        tools_arg = ctx_call.kwargs.get("tools")
        # Tools should be a ToolsSchema (not None / NOT_GIVEN)
        from pipecat.adapters.schemas.tools_schema import ToolsSchema

        assert isinstance(tools_arg, ToolsSchema)

    @patch("agents.hapax_daimonion.pipeline.LocalAudioTransport")
    @patch("agents.hapax_daimonion.pipeline.WhisperSTTService")
    @patch("agents.hapax_daimonion.pipeline.OpenAILLMService")
    @patch("agents.hapax_daimonion.pipeline.VoxtralTTSService")
    @patch("agents.hapax_daimonion.pipeline.LLMContext")
    @patch("agents.hapax_daimonion.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_daimonion.pipeline.Pipeline")
    @patch("agents.hapax_daimonion.pipeline.PipelineTask")
    def test_guest_mode_has_no_tools(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair_cls,
        mock_ctx_cls,
        mock_tts_cls,
        mock_llm_cls,
        mock_stt_cls,
        mock_transport_cls,
    ):
        """Guest mode pipeline has no tools registered."""
        mock_transport_cls.return_value = MagicMock()
        mock_agg_pair_cls.return_value = MagicMock()

        build_pipeline_task(guest_mode=True)

        ctx_call = mock_ctx_cls.call_args
        from openai import NOT_GIVEN

        assert ctx_call.kwargs.get("tools") is NOT_GIVEN

    @patch("agents.hapax_daimonion.pipeline.LocalAudioTransport")
    @patch("agents.hapax_daimonion.pipeline.WhisperSTTService")
    @patch("agents.hapax_daimonion.pipeline.OpenAILLMService")
    @patch("agents.hapax_daimonion.pipeline.VoxtralTTSService")
    @patch("agents.hapax_daimonion.pipeline.LLMContext")
    @patch("agents.hapax_daimonion.pipeline.LLMContextAggregatorPair")
    @patch("agents.hapax_daimonion.pipeline.Pipeline")
    @patch("agents.hapax_daimonion.pipeline.PipelineTask")
    def test_returns_task_and_transport(
        self,
        mock_task_cls,
        mock_pipeline_cls,
        mock_agg_pair_cls,
        mock_ctx_cls,
        mock_tts_cls,
        mock_llm_cls,
        mock_stt_cls,
        mock_transport_cls,
    ):
        """build_pipeline_task returns a (PipelineTask, LocalAudioTransport) tuple."""
        mock_t = MagicMock()
        mock_transport_cls.return_value = mock_t
        mock_agg_pair_cls.return_value = MagicMock()

        result = build_pipeline_task()

        assert isinstance(result, tuple)
        assert len(result) == 2
        task, transport = result
        assert task == mock_task_cls()
        assert transport == mock_t


class TestSystemPromptContent:
    """System prompt contains expected persona elements."""

    def test_prompt_contains_hapax_identity(self):
        from agents.hapax_daimonion.persona import system_prompt

        prompt = system_prompt(guest_mode=False)
        assert "hapax" in prompt.lower() or "assistant" in prompt.lower()

    def test_guest_prompt_differs(self):
        from agents.hapax_daimonion.persona import system_prompt

        normal = system_prompt(guest_mode=False)
        guest = system_prompt(guest_mode=True)
        assert normal != guest

    def test_normal_prompt_mentions_system_access(self):
        from agents.hapax_daimonion.persona import system_prompt

        prompt = system_prompt(guest_mode=False)
        # The normal prompt gives access to the operator's system
        assert any(
            word in prompt.lower() for word in ["system", "briefing", "calendar", "documents"]
        )

    def test_guest_prompt_restricts_access(self):
        from agents.hapax_daimonion.persona import system_prompt

        prompt = system_prompt(guest_mode=True)
        # Guest prompt should indicate limited access
        assert any(word in prompt.lower() for word in ["guest", "cannot", "personal", "primary"])
