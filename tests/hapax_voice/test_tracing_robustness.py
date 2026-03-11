"""Robustness / failure-mode tests for VoiceTracer."""

from unittest.mock import MagicMock, patch

from agents.hapax_voice.tracing import NoOpSpan, VoiceTracer


def test_missing_public_key():
    """Empty LANGFUSE_PUBLIC_KEY → tracing disabled, returns None."""
    with (
        patch.dict(
            "os.environ",
            {
                "LANGFUSE_PUBLIC_KEY": "",
                "LANGFUSE_SECRET_KEY": "sk-test",
            },
            clear=False,
        ),
        patch("agents.hapax_voice.tracing.Langfuse", MagicMock()),
    ):
        tracer = VoiceTracer(enabled=True)
        assert tracer._get_client() is None
        assert tracer._enabled is False


def test_missing_secret_key():
    """Empty LANGFUSE_SECRET_KEY → tracing disabled, returns None."""
    with (
        patch.dict(
            "os.environ",
            {
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "",
            },
            clear=False,
        ),
        patch("agents.hapax_voice.tracing.Langfuse", MagicMock()),
    ):
        tracer = VoiceTracer(enabled=True)
        assert tracer._get_client() is None
        assert tracer._enabled is False


def test_langfuse_constructor_exception():
    """Langfuse() raising ConnectionError → disabled, logs warning."""
    with patch.dict(
        "os.environ",
        {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
        },
        clear=False,
    ):
        with patch("agents.hapax_voice.tracing.Langfuse", side_effect=ConnectionError("refused")):
            tracer = VoiceTracer(enabled=True)
            assert tracer._get_client() is None
            assert tracer._enabled is False


def test_trace_exception_during_trace_call():
    """client.trace() raising → yields NoOpSpan instead of crashing."""
    mock_client = MagicMock()
    mock_client.trace.side_effect = RuntimeError("trace failed")

    with (
        patch.dict(
            "os.environ",
            {
                "LANGFUSE_PUBLIC_KEY": "pk-test",
                "LANGFUSE_SECRET_KEY": "sk-test",
            },
            clear=False,
        ),
        patch("agents.hapax_voice.tracing.Langfuse", return_value=mock_client),
    ):
        tracer = VoiceTracer(enabled=True)
        with tracer.trace_analysis(presence_score="away") as span:
            assert isinstance(span, NoOpSpan)


def test_noop_span_chainable():
    """NoOpSpan methods are chainable and never crash."""
    noop = NoOpSpan()
    result = noop.span("a").span("b").span("c")
    assert isinstance(result, NoOpSpan)
    result.end()  # must not raise


def test_noop_span_update():
    """NoOpSpan.update() accepts arbitrary kwargs without crashing."""
    noop = NoOpSpan()
    noop.update(status="ok", metadata={"key": "val"})  # must not raise


def test_context_manager_exception_in_body():
    """Exception inside context manager body propagates normally."""
    tracer = VoiceTracer(enabled=False)
    with tracer.trace_analysis(presence_score="unknown"):
        # Span is NoOpSpan, but body exceptions are not swallowed
        pass  # no exception here; verify context manager works
    # More meaningful: verify exception propagates out
    try:
        with tracer.trace_analysis(presence_score="unknown"):
            raise ValueError("user error")
    except ValueError as e:
        assert str(e) == "user error"
    else:
        raise AssertionError("ValueError should have propagated")


def test_disabled_tracer_never_creates_client():
    """VoiceTracer(enabled=False) never calls Langfuse()."""
    with patch("agents.hapax_voice.tracing.Langfuse") as mock_cls:
        tracer = VoiceTracer(enabled=False)
        with tracer.trace_analysis(presence_score="away"):
            pass
        with tracer.trace_session(session_id="s1", trigger="hotkey"):
            pass
        with tracer.trace_delivery(
            session_id=None,
            presence_score="away",
            gate_reason="none",
            notification_priority="low",
        ):
            pass
        mock_cls.assert_not_called()


def test_client_cached_after_creation():
    """_get_client() called twice → Langfuse() constructed only once."""
    mock_client = MagicMock()
    with patch.dict(
        "os.environ",
        {
            "LANGFUSE_PUBLIC_KEY": "pk-test",
            "LANGFUSE_SECRET_KEY": "sk-test",
        },
        clear=False,
    ):
        with patch("agents.hapax_voice.tracing.Langfuse", return_value=mock_client) as mock_cls:
            tracer = VoiceTracer(enabled=True)
            c1 = tracer._get_client()
            c2 = tracer._get_client()
            assert c1 is c2 is mock_client
            mock_cls.assert_called_once()
