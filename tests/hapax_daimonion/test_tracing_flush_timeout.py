"""Tests for OTel TracerProvider flush on shutdown.

Replaces the old VoiceTracer.flush() timeout tests — flush is now
handled by the OTel SDK's TracerProvider.force_flush().
"""

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory import InMemorySpanExporter


def test_force_flush_completes():
    """TracerProvider.force_flush() completes without error."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    t = trace.get_tracer("hapax_daimonion.test_flush")
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
    trace.set_tracer_provider(provider)

    retrieved = trace.get_tracer_provider()
    assert hasattr(retrieved, "force_flush")
    retrieved.force_flush(timeout_millis=5000)
