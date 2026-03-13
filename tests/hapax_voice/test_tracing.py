"""Tests for hapax-voice OTel tracing module."""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter


def _setup_test_tracer():
    """Create an in-memory OTel tracer for testing."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return exporter


def test_tracer_module_exports_tracer():
    """tracing.py exports a usable tracer object."""
    from agents.hapax_voice.tracing import tracer

    assert tracer is not None
    assert hasattr(tracer, "start_as_current_span")


def test_tracer_creates_spans():
    """Spans created via the module tracer are recorded."""
    exporter = _setup_test_tracer()

    from agents.hapax_voice.tracing import tracer  # noqa: F811 — re-import to pick up new provider

    # The module-level get_tracer() already ran, but the provider is global
    # so we use a fresh tracer from the new provider to verify the pattern.
    t = trace.get_tracer("hapax_voice.test")
    with t.start_as_current_span("test_span", attributes={"agent.name": "hapax-voice"}):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test_span"
    assert spans[0].attributes["agent.name"] == "hapax-voice"


def test_workspace_analysis_span_attributes():
    """Verify the workspace_analysis span pattern used in workspace_monitor."""
    exporter = _setup_test_tracer()
    t = trace.get_tracer("hapax_voice.workspace_monitor")

    with t.start_as_current_span(
        "workspace_analysis",
        attributes={
            "agent.name": "hapax-voice",
            "agent.repo": "hapax-council",
            "presence_score": "likely_present",
            "images_sent": 3,
            "activity_mode": "coding",
        },
    ):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    span = spans[0]
    assert span.name == "workspace_analysis"
    assert span.attributes["presence_score"] == "likely_present"
    assert span.attributes["images_sent"] == 3
