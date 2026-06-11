"""Optional tracing helpers for health-monitor entry points."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any


class NoOpTracer:
    """Minimal tracer compatible with ``start_as_current_span`` callers."""

    def start_as_current_span(self, *_args: Any, **_kwargs: Any) -> nullcontext[None]:
        return nullcontext()


def get_tracer(name: str) -> Any:
    """Return an OpenTelemetry tracer, or a no-op tracer when OTel is absent."""

    try:
        from opentelemetry import trace
    except ImportError:
        return NoOpTracer()
    return trace.get_tracer(name)
