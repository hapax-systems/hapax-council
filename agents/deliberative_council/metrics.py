"""Prometheus counter for degraded / refused deliberative-council panels.

``council_panel_degraded_total{family, reason}`` increments once per council
degradation event surfaced to the prep pipeline (coherence refused,
disconfirmation degraded, narrative refused, panel below quorum). This is the
loud, scrapeable half of the degradation signal; the operator-facing half is an
ntfy notification (shared/notify.py). cc-task
cctv-council-perfect-health-faillloud-convergence.

Importing is safe when ``prometheus_client`` is unavailable: ``record_panel_degraded``
is then a no-op and ``panel_degraded_value`` returns ``None`` (mirrors
shared/affordance_dispatch_metrics).
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_DEGRADED_COUNTER: Any = None
try:
    from prometheus_client import Counter

    _DEGRADED_COUNTER = Counter(
        "council_panel_degraded_total",
        "Degraded/refused deliberative-council panels, by family and reason.",
        ["family", "reason"],
    )
except ImportError:
    log.debug("prometheus_client not available — council degraded counter disabled")
except ValueError:
    # Re-import / test reload races: recover the already-registered collector.
    try:
        from prometheus_client import REGISTRY

        for collector in list(REGISTRY._collector_to_names):  # type: ignore[attr-defined]
            names = REGISTRY._collector_to_names.get(collector, ())  # type: ignore[attr-defined]
            if "council_panel_degraded_total" in names:
                _DEGRADED_COUNTER = collector
                break
    except Exception:
        log.debug("could not recover existing council degraded counter", exc_info=True)


def record_panel_degraded(family: str, reason: str) -> None:
    """Increment ``council_panel_degraded_total{family, reason}``.

    No-op when prometheus_client is unavailable. ``Counter.inc()`` is thread-safe.
    """
    if _DEGRADED_COUNTER is None:
        return
    try:
        _DEGRADED_COUNTER.labels(family=family or "unknown", reason=reason or "unknown").inc()
    except Exception:
        log.debug("council degraded counter inc failed", exc_info=True)


def panel_degraded_value(family: str, reason: str) -> float | None:
    """Return the current counter value for a (family, reason) (test introspection).

    Returns ``None`` when prometheus_client is unavailable.
    """
    if _DEGRADED_COUNTER is None:
        return None
    try:
        return float(_DEGRADED_COUNTER.labels(family=family, reason=reason)._value.get())
    except Exception:
        log.debug("council degraded counter read failed", exc_info=True)
        return None


__all__ = ["panel_degraded_value", "record_panel_degraded"]
