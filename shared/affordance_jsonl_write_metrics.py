"""Prometheus counter for JSONL write failures in AffordancePipeline.

The pipeline writes three append-only JSONL streams to disk for the
dispatch-dropout investigation, recruitment baseline, and perceptual-
distance impingement bus. All three swallow ``OSError`` silently
(fail-open: recruitment must never break on a logging failure). That's
the right runtime posture but it leaves operators blind to disk-full
or permission-denied incidents.

This module exposes ``hapax_affordance_jsonl_write_failures_total``
with a ``sink`` label for the three known append targets:

* ``dispatch_trace``     — ``DISPATCH_TRACE_FILE``
* ``recruitment_log``    — ``RECRUITMENT_LOG_FILE``
* ``perceptual_impingements`` — ``_PERCEPTUAL_IMPINGEMENTS_FILE``

Cardinality is hard-bounded; an unrecognised sink name lands in
``unknown`` rather than expanding the label set.
"""

from __future__ import annotations

import logging
from typing import Any, Final, Literal

log = logging.getLogger(__name__)

JsonlSink = Literal[
    "dispatch_trace",
    "recruitment_log",
    "perceptual_impingements",
]
KNOWN_SINKS: Final[tuple[JsonlSink, ...]] = (
    "dispatch_trace",
    "recruitment_log",
    "perceptual_impingements",
)
UNKNOWN_SINK: Final[str] = "unknown"
ALL_SINKS: Final[tuple[str, ...]] = KNOWN_SINKS + (UNKNOWN_SINK,)
_KNOWN_SET: Final[frozenset[str]] = frozenset(KNOWN_SINKS)


_WRITE_FAILURE_COUNTER: Any = None
try:
    from prometheus_client import Counter

    _WRITE_FAILURE_COUNTER = Counter(
        "hapax_affordance_jsonl_write_failures_total",
        "OSError-class failures appending to AffordancePipeline JSONL sinks.",
        ["sink"],
    )
except ImportError:
    log.debug("prometheus_client not available — JSONL write-failure counter disabled")
except ValueError:
    try:
        from prometheus_client import REGISTRY

        for collector in list(REGISTRY._collector_to_names):  # type: ignore[attr-defined]
            names = REGISTRY._collector_to_names.get(collector, ())  # type: ignore[attr-defined]
            if "hapax_affordance_jsonl_write_failures_total" in names:
                _WRITE_FAILURE_COUNTER = collector
                break
    except Exception:
        log.debug("could not recover existing JSONL write-failure counter", exc_info=True)


def _sink_label(name: str) -> str:
    if name in _KNOWN_SET:
        return name
    return UNKNOWN_SINK


def record_write_failure(sink: str) -> None:
    """Increment the write-failure counter for one of the JSONL sinks.

    No-op when prometheus_client is unavailable. Unknown sink names
    collapse to ``unknown`` so the cardinality bound is preserved.
    """

    if _WRITE_FAILURE_COUNTER is None:
        return
    try:
        _WRITE_FAILURE_COUNTER.labels(sink=_sink_label(sink)).inc()
    except Exception:
        log.debug("JSONL write-failure counter inc failed", exc_info=True)


def write_failure_counter_value(sink: str) -> float | None:
    """Return current counter value for a sink label (test introspection)."""

    if _WRITE_FAILURE_COUNTER is None:
        return None
    try:
        return float(_WRITE_FAILURE_COUNTER.labels(sink=_sink_label(sink))._value.get())
    except Exception:
        log.debug("JSONL write-failure counter read failed", exc_info=True)
        return None


__all__ = [
    "ALL_SINKS",
    "KNOWN_SINKS",
    "UNKNOWN_SINK",
    "JsonlSink",
    "record_write_failure",
    "write_failure_counter_value",
]
