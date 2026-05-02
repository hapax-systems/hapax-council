"""Prometheus counter for broadcast audio health probes.

Exposes ``hapax_broadcast_audio_health_probes_total{route, outcome}``
on the global Prometheus registry. Cardinality is bounded by the
configured route set + 3 outcome values (``detected`` / ``not_detected``
/ ``error``).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _build_counter() -> Any:
    """Build the counter or a no-op stub when prometheus_client is missing."""
    try:
        from prometheus_client import Counter  # type: ignore[import-not-found]
    except ImportError:
        log.debug("prometheus_client missing; broadcast-audio-health counter is a no-op")

        class _Stub:
            def labels(self, *args: object, **kwargs: object) -> _Stub:
                return self

            def inc(self, amount: float = 1.0) -> None:
                return None

        return _Stub()

    return Counter(
        "hapax_broadcast_audio_health_probes_total",
        "Broadcast-audio-health probe outcomes by route.",
        labelnames=("route", "outcome"),
    )


PROBES_TOTAL: Any = _build_counter()


def record_probe(route: str, outcome: str) -> None:
    """Increment ``hapax_broadcast_audio_health_probes_total{route, outcome}``."""
    try:
        PROBES_TOTAL.labels(route=route, outcome=outcome).inc()
    except Exception:
        log.exception("broadcast-audio-health metric increment failed")
