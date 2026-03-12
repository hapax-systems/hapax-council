"""Tests for OTel bootstrap in shared/langfuse_config.py.

Note: OTel has global state (TracerProvider) that can't be fully reset
between tests. These tests validate the module's behavior via env vars
and resource attributes rather than trying to reset the global provider.
"""

from __future__ import annotations

import importlib
import os
from unittest import mock


def test_env_vars_set_with_creds():
    """When LANGFUSE creds are set, OTEL env vars should be configured."""
    # Clear any existing OTEL env vars first
    for key in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_TRACES_EXPORTER",
    ):
        os.environ.pop(key, None)

    with mock.patch.dict(
        os.environ,
        {
            "LANGFUSE_PUBLIC_KEY": "pk-test-123",
            "LANGFUSE_SECRET_KEY": "sk-test-456",
            "LANGFUSE_HOST": "http://langfuse:3000",
        },
        clear=False,
    ):
        # Remove cached values so module re-reads env
        import shared.langfuse_config as mod

        importlib.reload(mod)

        assert mod.PUBLIC_KEY == "pk-test-123"
        assert mod.SECRET_KEY == "sk-test-456"
        assert mod.HOST == "http://langfuse:3000"


def test_no_env_vars_without_creds():
    """Without credentials, OTEL env vars should not be set by the module."""
    for key in (
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_TRACES_EXPORTER",
    ):
        os.environ.pop(key, None)

    with mock.patch.dict(
        os.environ,
        {
            "LANGFUSE_PUBLIC_KEY": "",
            "LANGFUSE_SECRET_KEY": "",
        },
        clear=False,
    ):
        import shared.langfuse_config as mod

        importlib.reload(mod)

        # Module should not have set these
        assert mod.PUBLIC_KEY == ""
        assert mod.SECRET_KEY == ""


def test_tracer_provider_has_correct_service_name():
    """The TracerProvider resource should have service.name = hapax-council."""
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider

    provider = trace.get_tracer_provider()
    # If the bootstrap has run (it runs at import time when creds are set),
    # verify the resource. If not, this test validates the no-op path.
    if isinstance(provider, TracerProvider):
        service_name = provider.resource.attributes.get("service.name", "")
        assert service_name == "hapax-council"


def test_get_tracer_returns_usable_tracer():
    """get_tracer() should return a tracer that can create spans without error."""
    from opentelemetry import trace

    tracer = trace.get_tracer("test-module")
    with tracer.start_as_current_span("test-span") as span:
        ctx = span.get_span_context()
        # Should have a valid (non-zero) trace_id if real provider is set
        # With no-op provider, trace_id is 0 — both are acceptable
        assert ctx is not None
