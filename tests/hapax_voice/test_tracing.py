"""Tests for VoiceTracer Langfuse integration."""

from unittest.mock import MagicMock, patch

from agents.hapax_voice.tracing import VoiceTracer


def test_disabled_tracer_is_noop():
    tracer = VoiceTracer(enabled=False)
    with tracer.trace_analysis(presence_score="likely_present", images_sent=2) as span:
        assert span is not None


def test_enabled_tracer_creates_langfuse_client():
    with (
        patch.dict(
            "os.environ",
            {
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
                "LANGFUSE_HOST": "http://localhost:3000",
            },
        ),
        patch("agents.hapax_voice.tracing.Langfuse") as mock_cls,
    ):
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        tracer = VoiceTracer(enabled=True)
        tracer._get_client()
        mock_cls.assert_called_once()


def test_trace_analysis_context_manager():
    tracer = VoiceTracer(enabled=False)
    with tracer.trace_analysis(presence_score="uncertain", images_sent=1) as ctx:
        ctx.span("call_vision")


def test_trace_session_context_manager():
    tracer = VoiceTracer(enabled=False)
    with tracer.trace_session(session_id="abc123", trigger="hotkey"):
        pass


def test_trace_delivery_context_manager():
    tracer = VoiceTracer(enabled=False)
    with tracer.trace_delivery(
        session_id=None,
        presence_score="likely_present",
        gate_reason="",
        notification_priority="normal",
    ):
        pass
