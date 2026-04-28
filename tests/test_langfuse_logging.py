"""Tests for Langfuse exporter log-noise filtering."""

from __future__ import annotations

import logging
import sys

from shared.langfuse_logging import (
    LangfuseExporterNoiseFilter,
    classify_langfuse_exporter_record,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _otel_timeout_record() -> logging.LogRecord:
    try:
        raise TimeoutError("HTTPConnectionPool read timeout")
    except TimeoutError:
        return logging.LogRecord(
            "opentelemetry.sdk._shared_internal",
            logging.ERROR,
            __file__,
            1,
            "Exception while exporting Span.",
            (),
            sys.exc_info(),
        )


def test_classifies_transient_otel_export_timeout() -> None:
    record = _otel_timeout_record()

    assert classify_langfuse_exporter_record(record) == "otel_export_timeout"


def test_rate_limits_transient_otel_export_timeout_without_stack_trace() -> None:
    clock = _Clock()
    noise_filter = LangfuseExporterNoiseFilter(window_s=60.0, clock=clock)

    first = _otel_timeout_record()
    assert noise_filter.filter(first) is True
    assert first.levelno == logging.WARNING
    assert first.exc_info is None
    assert "Transient Langfuse OTLP span export timeout" in first.getMessage()

    second = _otel_timeout_record()
    assert noise_filter.filter(second) is False

    clock.advance(61.0)
    third = _otel_timeout_record()
    assert noise_filter.filter(third) is True


def test_does_not_filter_unrelated_exporter_exception() -> None:
    try:
        raise RuntimeError("connection refused")
    except RuntimeError:
        record = logging.LogRecord(
            "opentelemetry.sdk._shared_internal",
            logging.ERROR,
            __file__,
            1,
            "Exception while exporting Span.",
            (),
            sys.exc_info(),
        )

    noise_filter = LangfuseExporterNoiseFilter(window_s=60.0, clock=lambda: 0.0)

    assert classify_langfuse_exporter_record(record) is None
    assert noise_filter.filter(record) is True
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


def test_rate_limits_langfuse_unexpected_export_error() -> None:
    clock = _Clock()
    noise_filter = LangfuseExporterNoiseFilter(window_s=60.0, clock=clock)

    first = logging.LogRecord(
        "langfuse",
        logging.ERROR,
        __file__,
        1,
        "Unexpected error occurred. Please check your request and contact support: https://langfuse.com/support.",
        (),
        None,
    )
    assert noise_filter.filter(first) is True
    assert first.levelno == logging.WARNING
    assert "Langfuse SDK reported an export error" in first.getMessage()

    second = logging.LogRecord(
        "langfuse",
        logging.ERROR,
        __file__,
        1,
        "Unexpected error occurred. Please check your request and contact support: https://langfuse.com/support.",
        (),
        None,
    )
    assert noise_filter.filter(second) is False


def test_leaves_unrelated_langfuse_errors_visible() -> None:
    record = logging.LogRecord(
        "langfuse",
        logging.ERROR,
        __file__,
        1,
        "401 unauthorized",
        (),
        None,
    )

    noise_filter = LangfuseExporterNoiseFilter(window_s=60.0, clock=lambda: 0.0)

    assert classify_langfuse_exporter_record(record) is None
    assert noise_filter.filter(record) is True
    assert record.levelno == logging.ERROR
