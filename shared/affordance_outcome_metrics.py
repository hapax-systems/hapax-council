"""Prometheus counter for AffordanceMetrics outcome events.

Pairs with ``shared.affordance_recruitment_metrics`` (which counts
selections per 6-domain bucket): once a capability has been recruited,
``AffordanceMetrics.record_outcome`` records whether activation
succeeded or failed. This module exposes that signal as
``hapax_affordance_outcome_total{outcome=success|failure}``.

Cardinality is hard-bounded to two labels — "success" / "failure" —
so no caller can blow up the label set with a free-form value.

Importing this module is safe even when ``prometheus_client`` is
unavailable: ``record_outcome`` is then a no-op and
``outcome_counter_value`` returns ``None``.
"""

from __future__ import annotations

import logging
from typing import Any, Final, Literal

log = logging.getLogger(__name__)

# Closed enum: cardinality bound for the ``outcome`` label.
OutcomeLabel = Literal["success", "failure"]
OUTCOME_LABELS: Final[tuple[OutcomeLabel, ...]] = ("success", "failure")


_PROMETHEUS_AVAILABLE = False
_OUTCOME_COUNTER: Any = None
try:
    from prometheus_client import Counter

    _OUTCOME_COUNTER = Counter(
        "hapax_affordance_outcome_total",
        "Affordance pipeline outcome events, labelled by success/failure.",
        ["outcome"],
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    log.debug("prometheus_client not available — outcome counter disabled")
except ValueError:
    # Re-import / test reload races trip "Duplicated timeseries"; recover the
    # existing collector rather than fail.
    try:
        from prometheus_client import REGISTRY

        for collector in list(REGISTRY._collector_to_names):  # type: ignore[attr-defined]
            names = REGISTRY._collector_to_names.get(collector, ())  # type: ignore[attr-defined]
            if "hapax_affordance_outcome_total" in names:
                _OUTCOME_COUNTER = collector
                _PROMETHEUS_AVAILABLE = True
                break
    except Exception:
        log.debug("could not recover existing outcome counter", exc_info=True)


def record_outcome(success: bool) -> None:
    """Increment ``hapax_affordance_outcome_total{outcome=success|failure}``.

    No-op when prometheus_client is unavailable. Safe to call from any
    thread; ``Counter.inc()`` is thread-safe by design.
    """

    if _OUTCOME_COUNTER is None:
        return
    label: OutcomeLabel = "success" if success else "failure"
    try:
        _OUTCOME_COUNTER.labels(outcome=label).inc()
    except Exception:
        log.debug("outcome counter inc failed", exc_info=True)


def outcome_counter_value(label: OutcomeLabel) -> float | None:
    """Return current counter value for an outcome label (test introspection).

    Returns ``None`` when prometheus_client is unavailable.
    """

    if _OUTCOME_COUNTER is None:
        return None
    try:
        return float(_OUTCOME_COUNTER.labels(outcome=label)._value.get())
    except Exception:
        log.debug("outcome counter read failed", exc_info=True)
        return None


__all__ = [
    "OUTCOME_LABELS",
    "OutcomeLabel",
    "outcome_counter_value",
    "record_outcome",
]
