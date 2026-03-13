"""shared/log_setup.py -- Centralized structured JSON logging.

Call once at process startup, before any logger is used:
    from shared.log_setup import configure_logging
    configure_logging(agent="ingest")
"""

import logging
import os
import sys

SERVICE_NAME = os.environ.get("HAPAX_SERVICE", "hapax-council")


def configure_logging(
    *,
    agent: str = "unknown",
    level: str | None = None,
    human_readable: bool | None = None,
) -> None:
    """Configure root logger with JSON formatter and OTel trace injection.

    Args:
        agent: Agent name for the 'agent' field in every log line.
        level: Log level override. Defaults to LOG_LEVEL env var or INFO.
        human_readable: If True, use human-readable format instead of JSON.
            Defaults to HAPAX_LOG_HUMAN env var or False.
    """
    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    if human_readable is None:
        human_readable = os.environ.get("HAPAX_LOG_HUMAN", "").lower() in ("1", "true", "yes")

    # Instrument stdlib logging to inject OTel trace context
    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        LoggingInstrumentor().instrument(set_logging_format=False)
    except Exception:
        pass  # OTel not available -- degrade gracefully

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove any existing handlers (from prior basicConfig calls)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)

    if human_readable:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    else:
        from pythonjsonlogger.json import JsonFormatter

        class _OTelJsonFormatter(JsonFormatter):
            def add_fields(self, log_record, record, message_dict):
                super().add_fields(log_record, record, message_dict)
                # Rename OTel-injected fields and suppress zero trace IDs
                otel_trace = log_record.pop("otelTraceID", None)
                otel_span = log_record.pop("otelSpanID", None)
                log_record.pop("otelServiceName", None)
                if otel_trace and otel_trace != "0":
                    log_record["trace_id"] = otel_trace
                if otel_span and otel_span != "0":
                    log_record["span_id"] = otel_span

        formatter = _OTelJsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(module)s %(funcName)s %(lineno)d %(message)s",
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "name": "logger",
            },
            datefmt="%Y-%m-%dT%H:%M:%S.%fZ",
            static_fields={
                "service": SERVICE_NAME,
                "agent": agent,
            },
        )
        handler.setFormatter(formatter)

    root.addHandler(handler)

    # Quiet noisy libraries
    for lib in ("httpx", "httpcore", "urllib3", "watchdog", "filelock"):
        logging.getLogger(lib).setLevel(logging.WARNING)
