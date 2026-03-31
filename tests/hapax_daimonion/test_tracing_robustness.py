"""Robustness tests for OTel tracing in hapax-daimonion.

Replaces old VoiceTracer robustness tests. OTel spans are fail-open
by design — if no TracerProvider is configured, get_tracer() returns
a no-op tracer that silently drops spans.
"""

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


def test_noop_tracer_does_not_crash():
    """Without a configured provider, spans are silently dropped."""
    provider = TracerProvider()
    t = provider.get_tracer("hapax_daimonion.noop_test")
    with t.start_as_current_span("should_not_crash"):
        pass  # no error


def test_span_with_exception_in_body():
    """Exceptions inside a span propagate normally (not swallowed)."""
    exporter, _provider, t = _make_tracer("hapax_daimonion.exception_test")

    try:
        with t.start_as_current_span("failing_span"):
            raise ValueError("user error")
    except ValueError as e:
        assert str(e) == "user error"
    else:
        raise AssertionError("ValueError should have propagated")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "failing_span"
    # OTel records the exception event on the span
    events = spans[0].events
    assert any(ev.name == "exception" for ev in events)


def test_nested_spans():
    """Nested spans are correctly parented."""
    exporter, _provider, t = _make_tracer("hapax_daimonion.nesting_test")

    with t.start_as_current_span("parent"):
        with t.start_as_current_span("child"):
            pass

    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    child, parent = spans  # SimpleSpanProcessor: child finishes first
    assert child.name == "child"
    assert parent.name == "parent"
    assert child.parent.span_id == parent.context.span_id


def test_attributes_are_recorded():
    """Span attributes round-trip correctly."""
    exporter, _provider, t = _make_tracer("hapax_daimonion.attrs_test")

    with t.start_as_current_span(
        "attr_span",
        attributes={
            "agent.name": "hapax-daimonion",
            "presence_score": "likely_absent",
            "images_sent": 0,
        },
    ):
        pass

    spans = exporter.get_finished_spans()
    assert spans[0].attributes["agent.name"] == "hapax-daimonion"
    assert spans[0].attributes["images_sent"] == 0
