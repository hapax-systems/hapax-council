"""Prometheus metrics for live mood-claim engines.

The mood bridges now feed all three Bayesian mood engines with live
``bool | None`` observations. These metrics make the Phase D acceptance
surface scrape-visible:

- posterior gauges for arousal, valence, and coherence
- monotonically increasing observed- and contributed-signal counters per engine

Importing this module is safe when ``prometheus_client`` is unavailable.
In that case recording functions are no-ops and introspection helpers
return ``None``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

log = logging.getLogger(__name__)

MOOD_ENGINE_LABELS: tuple[str, ...] = ("mood_arousal", "mood_valence", "mood_coherence")
POSTERIOR_METRIC_NAMES: dict[str, str] = {
    "mood_arousal": "mood_arousal_posterior_value",
    "mood_valence": "mood_valence_posterior_value",
    "mood_coherence": "mood_coherence_posterior_value",
}
SIGNALS_COUNTER_NAME = "mood_engine_signals_contributed_total"
OBSERVED_COUNTER_NAME = "mood_engine_signals_observed_total"

_POSTERIOR_GAUGES: dict[str, Any] = {}
_SIGNALS_COUNTER: Any = None
_OBSERVED_COUNTER: Any = None


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
            "Mood-engine signal observations that affected Bayesian log-odds updates.",
            ["engine"],
        )
    except ValueError:
        _SIGNALS_COUNTER = _collector_by_name(SIGNALS_COUNTER_NAME)

    try:
        _OBSERVED_COUNTER = Counter(
            OBSERVED_COUNTER_NAME,
            "Non-None mood-engine signal observations seen by the bridge.",
            ["engine"],
        )
    except ValueError:
        _OBSERVED_COUNTER = _collector_by_name(OBSERVED_COUNTER_NAME)
except ImportError:
    log.debug("prometheus_client not available; mood-engine metrics disabled")


def observed_signal_count(observations: Mapping[str, object | None]) -> int:
    """Count non-None observations seen by the bridge."""

    return sum(1 for value in observations.values() if value is not None)


def contributed_signal_count(
    observations: Mapping[str, object | None],
    *,
    positive_only_signals: Iterable[str] = (),
) -> int:
    """Count observations that actually contributed to the Bayesian tick.

    ``ClaimEngine[bool]`` skips ``False`` observations for positive-only
    signals. Counting them as contributions made dashboards look healthy
    while the posterior correctly stayed at its prior.
    """

    positive_only = frozenset(positive_only_signals)
    count = 0
    for signal_name, value in observations.items():
        if value is None:
            continue
        if isinstance(value, bool) and not value and signal_name in positive_only:
            continue
        count += 1
    return count


def record_mood_engine_tick(
    engine: str,
    posterior: float,
    observations: Mapping[str, object | None],
    *,
    positive_only_signals: Iterable[str] = (),
) -> None:
    """Set posterior gauge and increment signal counters.

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

    observed_count = observed_signal_count(observations)
    if observed_count > 0 and _OBSERVED_COUNTER is not None:
        try:
            _OBSERVED_COUNTER.labels(engine=engine).inc(float(observed_count))
        except Exception:
            log.debug("mood observed signal counter update failed", exc_info=True)

    contributed_count = contributed_signal_count(
        observations,
        positive_only_signals=positive_only_signals,
    )
    if contributed_count > 0 and _SIGNALS_COUNTER is not None:
        try:
            _SIGNALS_COUNTER.labels(engine=engine).inc(float(contributed_count))
        except Exception:
            log.debug("mood contributed signal counter update failed", exc_info=True)


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


def observed_signals_counter_value(engine: str) -> float | None:
    """Return the current observed-signal counter value for tests."""

    if _OBSERVED_COUNTER is None:
        return None
    try:
        return float(_OBSERVED_COUNTER.labels(engine=engine)._value.get())
    except Exception:
        log.debug("mood observed signal counter read failed", exc_info=True)
        return None


__all__ = [
    "MOOD_ENGINE_LABELS",
    "OBSERVED_COUNTER_NAME",
    "POSTERIOR_METRIC_NAMES",
    "SIGNALS_COUNTER_NAME",
    "contributed_signal_count",
    "observed_signal_count",
    "observed_signals_counter_value",
    "posterior_gauge_value",
    "record_mood_engine_tick",
    "signals_counter_value",
]
