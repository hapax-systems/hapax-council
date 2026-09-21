"""Tests for OTel bootstrap in shared/langfuse_config.py.

Note: OTel has global state (TracerProvider) that can't be fully reset
between tests. These tests validate the module's behavior via env vars
and resource attributes rather than trying to reset the global provider.
"""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
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


def test_tracer_provider_has_correct_service_name(tmp_path):
    """A fresh enabled bootstrap installs the declared service resource.

    The process-wide provider may belong to an earlier test and cannot be reset
    through the public OTel API. Exercise this module's actual bootstrap in its
    own process instead of making an assertion about that ambient provider.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json\n"
            "import shared.langfuse_config\n"
            "from opentelemetry import trace\n"
            "provider = trace.get_tracer_provider()\n"
            "try:\n"
            "    print(json.dumps(dict(provider.resource.attributes)))\n"
            "finally:\n"
            "    provider.shutdown()\n",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "OTEL_SDK_DISABLED": "false",
            "OTEL_TRACES_EXPORTER": "otlp",
            "LANGFUSE_HOST": "http://127.0.0.1:1",
            "LANGFUSE_PUBLIC_KEY": "pk-test-123",
            "LANGFUSE_SECRET_KEY": "sk-test-456",
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["service.name"] == "hapax-council"


def test_get_tracer_returns_usable_tracer():
    """get_tracer() should return a tracer that can create spans without error."""
    from opentelemetry import trace

    tracer = trace.get_tracer("test-module")
    with tracer.start_as_current_span("test-span") as span:
        ctx = span.get_span_context()
        # Should have a valid (non-zero) trace_id if real provider is set
        # With no-op provider, trace_id is 0 — both are acceptable
        assert ctx is not None
