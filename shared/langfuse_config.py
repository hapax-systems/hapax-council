"""langfuse_config.py — Wire OpenTelemetry traces to self-hosted Langfuse.

Import this module as a side-effect in any agent script:
    import langfuse_config  # noqa: F401

Requires env vars:
    LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
"""
import os

HOST = os.environ.get("LANGFUSE_HOST", "http://localhost:3000")
PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY", "")

if PUBLIC_KEY and SECRET_KEY:
    # Configure OTel exporter to send traces to Langfuse
    os.environ.setdefault(
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        f"{HOST}/api/public/otel",
    )
    os.environ.setdefault(
        "OTEL_EXPORTER_OTLP_HEADERS",
        f"x-langfuse-public-key={PUBLIC_KEY},x-langfuse-secret-key={SECRET_KEY}",
    )
    os.environ.setdefault("OTEL_TRACES_EXPORTER", "otlp")
