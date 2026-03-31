"""Tests for OTel TracerProvider flush on shutdown.

Replaces the old VoiceTracer.flush() timeout tests — flush is now
handled by the OTel SDK's TracerProvider.force_flush().
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


def test_force_flush_completes():
    """TracerProvider.force_flush() completes without error."""
    exporter = _ListSpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))

    t = provider.get_tracer("hapax_daimonion.test_flush")
    with t.start_as_current_span("flush_test"):
        pass

    result = provider.force_flush(timeout_millis=5000)
    assert result is True
    assert len(exporter.get_finished_spans()) == 1


def test_force_flush_on_empty_provider():
    """force_flush() on a provider with no spans is a no-op."""
    provider = TracerProvider()
    result = provider.force_flush(timeout_millis=1000)
    assert result is True


def test_shutdown_pattern():
    """Verify the shutdown pattern used in __main__.py works."""
    provider = TracerProvider()
    assert hasattr(provider, "force_flush")
    provider.force_flush(timeout_millis=5000)
