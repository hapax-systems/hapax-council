"""Tests for OTel trace_id/span_id injection in EventLog.emit()."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def event_log(tmp_path: Path):
    """Create an EventLog writing to a temp directory."""
    from agents.hapax_voice.event_log import EventLog

    el = EventLog(base_dir=tmp_path, enabled=True)
    el.set_session_id("test-session")
    yield el
    el.close()


def _read_last_event(tmp_path: Path) -> dict:
    """Read the last event from any JSONL file in tmp_path."""
    files = sorted(tmp_path.glob("events-*.jsonl"))
    assert files, "No event files found"
    lines = files[-1].read_text().strip().splitlines()
    assert lines, "Event file is empty"
    return json.loads(lines[-1])


def test_trace_id_present_with_active_span(event_log, tmp_path):
    """When an OTel span is active, trace_id and span_id should appear in the event."""
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider()
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("test-span"):
        event_log.emit("test_event", foo="bar")

    event = _read_last_event(tmp_path)
    assert "trace_id" in event
    assert "span_id" in event
    assert len(event["trace_id"]) == 32  # 128-bit hex
    assert len(event["span_id"]) == 16  # 64-bit hex
    assert event["foo"] == "bar"
    assert event["type"] == "test_event"

    provider.shutdown()


def test_trace_id_absent_without_active_span(event_log, tmp_path):
    """Without an active span, trace_id/span_id should not appear."""
    event_log.emit("no_span_event", key="val")

    event = _read_last_event(tmp_path)
    # The default INVALID span has trace_id=0, which should not be injected
    assert event.get("trace_id") is None or event.get("trace_id") == "0" * 32
    assert event["type"] == "no_span_event"


def test_emit_works_without_otel_installed(event_log, tmp_path, monkeypatch):
    """If opentelemetry is not importable, emit() should still write the event."""
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "opentelemetry" or name.startswith("opentelemetry."):
            raise ImportError("mocked")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    event_log.emit("fallback_event", data="ok")

    event = _read_last_event(tmp_path)
    assert event["type"] == "fallback_event"
    assert event["data"] == "ok"
    assert "trace_id" not in event
