"""Logging filters for known Langfuse exporter noise."""

from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Callable

_OTEL_EXPORTER_LOGGER = "opentelemetry.sdk._shared_internal"
_LANGFUSE_LOGGER = "langfuse"
_OTEL_SPAN_EXPORT_MESSAGE = "Exception while exporting Span."
_LANGFUSE_UNEXPECTED_PREFIX = "Unexpected error occurred. Please check your request"
_TIMEOUT_MARKERS = (
    "ReadTimeout",
    "ReadTimeoutError",
    "TimeoutError",
    "read timeout",
    "timed out",
)
_installed_filters: dict[str, LangfuseExporterNoiseFilter] = {}


def classify_langfuse_exporter_record(record: logging.LogRecord) -> str | None:
    """Return the known transient-noise class for a log record, if any."""
    message = record.getMessage()
    if record.name == _OTEL_EXPORTER_LOGGER and message == _OTEL_SPAN_EXPORT_MESSAGE:
        exc_text = _exception_text(record)
        if any(marker in exc_text for marker in _TIMEOUT_MARKERS):
            return "otel_export_timeout"
        return None

    if record.name == _LANGFUSE_LOGGER and message.startswith(_LANGFUSE_UNEXPECTED_PREFIX):
        return "langfuse_unexpected_export_error"

    return None


def _exception_text(record: logging.LogRecord) -> str:
    if record.exc_info is None:
        return ""
    return "".join(traceback.format_exception(*record.exc_info))


class LangfuseExporterNoiseFilter(logging.Filter):
    """Compact and rate-limit transient Langfuse exporter failures.

    The filter leaves unrelated records untouched. Known local timeout paths
    still emit a compact warning once per window so a real outage has a visible
    journal breadcrumb while repeated stack traces do not drown the service log.
    """

    def __init__(
        self,
        *,
        window_s: float = 300.0,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__()
        self._window_s = window_s
        self._clock = clock or time.monotonic
        self._last_seen: dict[str, float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        noise_class = classify_langfuse_exporter_record(record)
        if noise_class is None:
            return True

        now = self._clock()
        last = self._last_seen.get(noise_class)
        if last is not None and now - last < self._window_s:
            return False

        self._last_seen[noise_class] = now
        _compact_record(record, noise_class, self._window_s)
        return True


def _compact_record(record: logging.LogRecord, noise_class: str, window_s: float) -> None:
    record.levelno = logging.WARNING
    record.levelname = "WARNING"
    record.args = ()
    record.exc_info = None
    record.exc_text = None
    if noise_class == "otel_export_timeout":
        record.msg = (
            "Transient Langfuse OTLP span export timeout; suppressing repeated "
            f"exporter stack traces for {window_s:.0f}s. Trace health still reports "
            "endpoint/auth outages."
        )
        return

    record.msg = (
        "Langfuse SDK reported an export error; suppressing repeated copies for "
        f"{window_s:.0f}s. Check trace endpoint/auth health if this persists."
    )


def install_langfuse_exporter_noise_filter(*, window_s: float = 300.0) -> None:
    """Install the transient-exporter filter on the SDK loggers once."""
    for logger_name in (_OTEL_EXPORTER_LOGGER, _LANGFUSE_LOGGER):
        logger = logging.getLogger(logger_name)
        if logger_name in _installed_filters:
            continue
        noise_filter = LangfuseExporterNoiseFilter(window_s=window_s)
        logger.addFilter(noise_filter)
        _installed_filters[logger_name] = noise_filter
