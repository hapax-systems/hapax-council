"""Prometheus counter for AffordancePipeline dispatch outcomes.

Completes the affordance-pipeline observability trio:
- recruitment: selection-with-winner volume by 6-domain bucket
  (``shared.affordance_recruitment_metrics``)
- dispatch: every ``select()`` call's classified outcome — winner or
  named dropout reason (this module)
- outcome: post-recruitment success/failure
  (``shared.affordance_outcome_metrics``)

The counter ``hapax_affordance_dispatch_total{outcome=...}`` is
incremented once per ``select()`` call inside
``AffordancePipeline._emit_dispatch_trace``. Cardinality is hard-bounded
to the closed enum below (10 known outcomes + ``unknown``), so a future
``dropout_at`` value lands in the fallback rather than blowing up the
label set.

Importing this module is safe even when ``prometheus_client`` is
unavailable: ``record_dispatch`` is then a no-op and
``dispatch_counter_value`` returns ``None``.
"""

from __future__ import annotations

import logging
from typing import Any, Final

log = logging.getLogger(__name__)

# Closed enum: every classified outcome `_emit_dispatch_trace` may carry.
# ``success`` covers ``trace["dropout_at"] is None`` (selection produced
# a winner). Every other value mirrors a literal `trace["dropout_at"] =
# "..."` site in `affordance_pipeline.py`.
KNOWN_OUTCOMES: Final[tuple[str, ...]] = (
    "success",
    "interrupt_no_handler",
    "inhibited",
    "no_embedding_fallback",
    "retrieve_family_empty",
    "retrieve_global_empty",
    "consent_filter_empty",
    "monetization_filter_empty",
    "content_risk_filter_empty",
    "threshold_miss",
)
UNKNOWN_OUTCOME: Final[str] = "unknown"
ALL_OUTCOMES: Final[tuple[str, ...]] = KNOWN_OUTCOMES + (UNKNOWN_OUTCOME,)
_KNOWN_SET: Final[frozenset[str]] = frozenset(KNOWN_OUTCOMES)


_PROMETHEUS_AVAILABLE = False
_DISPATCH_COUNTER: Any = None
try:
    from prometheus_client import Counter

    _DISPATCH_COUNTER = Counter(
        "hapax_affordance_dispatch_total",
        "Affordance pipeline dispatch outcomes per select() call.",
        ["outcome"],
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    log.debug("prometheus_client not available — dispatch counter disabled")
except ValueError:
    # Re-import / test reload races: recover the existing collector.
    try:
        from prometheus_client import REGISTRY

        for collector in list(REGISTRY._collector_to_names):  # type: ignore[attr-defined]
            names = REGISTRY._collector_to_names.get(collector, ())  # type: ignore[attr-defined]
            if "hapax_affordance_dispatch_total" in names:
                _DISPATCH_COUNTER = collector
                _PROMETHEUS_AVAILABLE = True
                break
    except Exception:
        log.debug("could not recover existing dispatch counter", exc_info=True)


def outcome_label_for(dropout_at: str | None) -> str:
    """Map a ``trace["dropout_at"]`` value to its bounded label.

    ``None`` (the success path) → ``"success"``. Known dropout reasons
    pass through. Anything else (a future addition we haven't seen
    yet) collapses to ``"unknown"`` so the label set stays bounded.
    """

    if dropout_at is None:
        return "success"
    if dropout_at in _KNOWN_SET:
        return dropout_at
    return UNKNOWN_OUTCOME


def record_dispatch(dropout_at: str | None) -> None:
    """Increment ``hapax_affordance_dispatch_total{outcome=...}``.

    No-op when prometheus_client is unavailable. Safe to call from any
    thread; ``Counter.inc()`` is thread-safe by design.
    """

    if _DISPATCH_COUNTER is None:
        return
    label = outcome_label_for(dropout_at)
    try:
        _DISPATCH_COUNTER.labels(outcome=label).inc()
    except Exception:
        log.debug("dispatch counter inc failed", exc_info=True)


def dispatch_counter_value(outcome: str) -> float | None:
    """Return current counter value for an outcome label (test introspection).

    Returns ``None`` when prometheus_client is unavailable.
    """

    if _DISPATCH_COUNTER is None:
        return None
    try:
        return float(_DISPATCH_COUNTER.labels(outcome=outcome)._value.get())
    except Exception:
        log.debug("dispatch counter read failed", exc_info=True)
        return None


__all__ = [
    "ALL_OUTCOMES",
    "KNOWN_OUTCOMES",
    "UNKNOWN_OUTCOME",
    "dispatch_counter_value",
    "outcome_label_for",
    "record_dispatch",
]
