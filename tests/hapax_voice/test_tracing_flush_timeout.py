"""Tests for VoiceTracer.flush() timeout behavior."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock

from agents.hapax_voice.tracing import VoiceTracer


def _make_tracer_with_mock_client() -> tuple[VoiceTracer, MagicMock]:
    tracer = VoiceTracer(enabled=False)
    mock_client = MagicMock()
    tracer._client = mock_client
    return tracer, mock_client


def test_flush_completes_normally():
    tracer, mock_client = _make_tracer_with_mock_client()
    tracer.flush(timeout_s=2.0)
    mock_client.flush.assert_called_once()


def test_flush_times_out():
    tracer, mock_client = _make_tracer_with_mock_client()
    block = threading.Event()
    mock_client.flush.side_effect = lambda: block.wait()

    tracer.flush(timeout_s=0.5)
    # Should return without hanging
    block.set()  # unblock the background thread so it can exit cleanly


def test_flush_with_no_client():
    tracer = VoiceTracer(enabled=False)
    assert tracer._client is None
    tracer.flush()  # should be a no-op, no error


def test_flush_handles_exception():
    tracer, mock_client = _make_tracer_with_mock_client()
    mock_client.flush.side_effect = RuntimeError("connection refused")
    tracer.flush(timeout_s=2.0)  # should not raise
