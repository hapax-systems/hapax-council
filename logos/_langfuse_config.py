"""logos/_langfuse_config.py — Wire OpenTelemetry traces to self-hosted Langfuse.

Vendored from shared/langfuse_config.py during shared/ dissolution.

Import this module as a side-effect:
    from logos import _langfuse_config  # noqa: F401

Requires env vars:
    LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
"""

import os

HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")

if PUBLIC_KEY and SECRET_KEY:
    import base64

    _basic_auth = base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()

    # Configure OTel exporter to send traces to Langfuse
    os.environ.setdefault(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        f"{HOST}/api/public/otel",
    )
    os.environ.setdefault(
        "OTEL_EXPORTER_OTLP_HEADERS",
        f"Authorization=Basic {_basic_auth}",
    )
    os.environ.setdefault("OTEL_TRACES_EXPORTER", "otlp")

    # Programmatically create TracerProvider so get_tracer() returns real spans
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _resource = Resource.create({"service.name": "hapax-council"})
    _provider = TracerProvider(resource=_resource)
    _provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(
                endpoint=f"{HOST}/api/public/otel/v1/traces",
                headers={
                    "Authorization": f"Basic {_basic_auth}",
                },
            )
        )
    )
    trace.set_tracer_provider(_provider)

    # Auto-instrument httpx — covers pydantic-ai, Qdrant, Ollama, LiteLLM calls
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except Exception:
        pass  # instrumentation is optional
