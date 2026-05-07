"""Prometheus metrics for live mood-claim engines.

The mood bridges now feed all three Bayesian mood engines with live
``bool | None`` observations. These metrics make the Phase D acceptance
surface scrape-visible:

- posterior gauges for arousal, valence, and coherence
- a monotonically increasing contributed-signal counter per engine

Importing this module is safe when ``prometheus_client`` is unavailable.
In that case recording functions are no-ops and introspection helpers
return ``None``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

log = logging.getLogger(__name__)

MOOD_ENGINE_LABELS: tuple[str, ...] = ("mood_arousal", "mood_valence", "mood_coherence")
POSTERIOR_METRIC_NAMES: dict[str, str] = {
    "mood_arousal": "mood_arousal_posterior_value",
    "mood_valence": "mood_valence_posterior_value",
    "mood_coherence": "mood_coherence_posterior_value",
}
SIGNALS_COUNTER_NAME = "mood_engine_signals_contributed_total"

_POSTERIOR_GAUGES: dict[str, Any] = {}
_SIGNALS_COUNTER: Any = None


def _collector_by_name(name: str) -> Any | None:
    try:
        from prometheus_client import REGISTRY

        for collector in list(REGISTRY._collector_to_names):  # type: ignore[attr-defined]
            names = REGISTRY._collector_to_names.get(collector, ())  # type: ignore[attr-defined]
            if name in names:
                return collector
    except Exception:
        log.debug("could not recover existing Prometheus collector %s", name, exc_info=True)
    return None


try:
    from prometheus_client import Counter, Gauge

    for engine, metric_name in POSTERIOR_METRIC_NAMES.items():
        try:
            _POSTERIOR_GAUGES[engine] = Gauge(
                metric_name,
                f"Current Bayesian posterior for {engine.replace('_', ' ')}.",
            )
        except ValueError:
            existing = _collector_by_name(metric_name)
            if existing is not None:
                _POSTERIOR_GAUGES[engine] = existing

    try:
        _SIGNALS_COUNTER = Counter(
            SIGNALS_COUNTER_NAME,
            "Non-None mood-engine signal observations contributed to Bayesian updates.",
            ["engine"],
        )
    except ValueError:
        _SIGNALS_COUNTER = _collector_by_name(SIGNALS_COUNTER_NAME)
except ImportError:
    log.debug("prometheus_client not available; mood-engine metrics disabled")


def contributed_signal_count(observations: Mapping[str, object | None]) -> int:
    """Count observations that actually contributed to the Bayesian tick."""

    return sum(1 for value in observations.values() if value is not None)


def record_mood_engine_tick(
    engine: str,
    posterior: float,
    observations: Mapping[str, object | None],
) -> None:
    """Set posterior gauge and increment contributed-signal counter.

    ``engine`` is intentionally a closed label set. Unknown labels are
    ignored so a caller typo cannot expand Prometheus cardinality.
    """

    if engine not in MOOD_ENGINE_LABELS:
        return

    gauge = _POSTERIOR_GAUGES.get(engine)
    if gauge is not None:
        try:
            gauge.set(float(posterior))
        except Exception:
            log.debug("mood posterior gauge update failed", exc_info=True)

    count = contributed_signal_count(observations)
    if count <= 0 or _SIGNALS_COUNTER is None:
        return
    try:
        _SIGNALS_COUNTER.labels(engine=engine).inc(float(count))
    except Exception:
        log.debug("mood signal counter update failed", exc_info=True)


def posterior_gauge_value(engine: str) -> float | None:
    """Return the current posterior gauge value for tests."""

    gauge = _POSTERIOR_GAUGES.get(engine)
    if gauge is None:
        return None
    try:
        return float(gauge._value.get())
    except Exception:
        log.debug("mood posterior gauge read failed", exc_info=True)
        return None


def signals_counter_value(engine: str) -> float | None:
    """Return the current contributed-signal counter value for tests."""

    if _SIGNALS_COUNTER is None:
        return None
    try:
        return float(_SIGNALS_COUNTER.labels(engine=engine)._value.get())
    except Exception:
        log.debug("mood signal counter read failed", exc_info=True)
        return None


__all__ = [
    "MOOD_ENGINE_LABELS",
    "POSTERIOR_METRIC_NAMES",
    "SIGNALS_COUNTER_NAME",
    "contributed_signal_count",
    "posterior_gauge_value",
    "record_mood_engine_tick",
    "signals_counter_value",
]
