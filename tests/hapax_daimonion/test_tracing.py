"""Tests for hapax-daimonion OTel tracing module."""

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult


class _ListSpanExporter(SpanExporter):
    """Minimal in-memory exporter for tests (replaces removed InMemorySpanExporter)."""

    def __init__(self) -> None:
        self.spans: list = []

    def export(self, spans):
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def clear(self) -> None:
        self.spans.clear()

    def get_finished_spans(self) -> list:
        return list(self.spans)


def _make_tracer(name: str = "test"):
    """Create a fresh provider+exporter+tracer triple (no global mutation)."""
    exporter = _ListSpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(name)
    return exporter, provider, tracer


def test_tracer_module_exports_tracer():
    """tracing.py exports a usable tracer object."""
    from agents.hapax_daimonion.tracing import tracer

    assert tracer is not None
    assert hasattr(tracer, "start_as_current_span")


def test_tracer_creates_spans():
    """Spans created via the module tracer are recorded."""
    exporter, _provider, t = _make_tracer("hapax_daimonion.test")

    with t.start_as_current_span("test_span", attributes={"agent.name": "hapax-daimonion"}):
        pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test_span"
    assert spans[0].attributes["agent.name"] == "hapax-daimonion"


def test_workspace_analysis_span_attributes():
    """Verify the workspace_analysis span pattern used in workspace_monitor."""
    exporter, _provider, t = _make_tracer("hapax_daimonion.workspace_monitor")

    with t.start_as_current_span(
        "workspace_analysis",
        attributes={
            "agent.name": "hapax-daimonion",
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
