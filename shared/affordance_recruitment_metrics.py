"""Prometheus counter for AffordancePipeline recruitment events.

Audit-closeout 12.3: ``hapax_affordance_recruitment_total`` gives Grafana
an aggregate recruitment volume signal that complements per-tick log
lines and per-event JSONL traces.

The counter is labelled by ``domain`` from the canonical 6-domain
taxonomy referenced in
``hapax-council/CLAUDE.md §Unified Semantic Recruitment``:
``perception | expression | recall | action | communication | regulation``.
Cardinality is hard-capped to those six labels plus an ``unknown``
fallback for capabilities whose name prefix does not match the
registry domains — that prevents capability-name explosion from leaking
into the label set.

Importing this module is safe even when ``prometheus_client`` is
unavailable (e.g. in minimal test environments). In that case
``record_recruitment`` is a no-op and ``recruitment_counter_value`` is
``None``; pipeline behavior is unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Canonical 6-domain taxonomy. Treated as a closed enum for label
# cardinality; ``unknown`` is a 7th bucket for fallbacks but is reserved
# for genuinely unmapped capabilities (e.g. a registry-extension
# capability that hasn't been mapped yet).
TAXONOMY_DOMAINS: tuple[str, ...] = (
    "perception",
    "expression",
    "recall",
    "action",
    "communication",
    "regulation",
)
UNKNOWN_DOMAIN: str = "unknown"
ALL_DOMAINS: tuple[str, ...] = TAXONOMY_DOMAINS + (UNKNOWN_DOMAIN,)

# Capability-name prefix → 6-domain taxonomy.
#
# The affordance registry is organised into 10 prefix domains
# (``shared.affordance_registry.AFFORDANCE_DOMAINS``); the 6-domain
# taxonomy collapses these into the canonical set. Mapping rationale:
#   env / body / world      → perception (sensing the surround)
#   studio / narration      → expression (rendered output)
#   space / digital         → action (do-something on a target)
#   knowledge               → recall (remembering and retrieving)
#   social                  → communication (operator-facing)
#   system                  → regulation (self-control of the system)
_PREFIX_TO_TAXONOMY: dict[str, str] = {
    "env": "perception",
    "body": "perception",
    "world": "perception",
    "studio": "expression",
    "narration": "expression",
    "space": "action",
    "digital": "action",
    "knowledge": "recall",
    "social": "communication",
    "system": "regulation",
}


_PROMETHEUS_AVAILABLE = False
_RECRUITMENT_COUNTER: Any = None
try:
    from prometheus_client import Counter

    _RECRUITMENT_COUNTER = Counter(
        "hapax_affordance_recruitment_total",
        "Affordance pipeline recruitment events, labelled by 6-domain taxonomy.",
        ["domain"],
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    log.debug("prometheus_client not available — recruitment counter disabled")
except ValueError:
    # Re-import at module reload (test isolation, importlib.reload) raises
    # ValueError("Duplicated timeseries"); look up the existing collector
    # rather than fail.
    try:
        from prometheus_client import REGISTRY

        for collector in list(REGISTRY._collector_to_names):  # type: ignore[attr-defined]
            names = REGISTRY._collector_to_names.get(collector, ())  # type: ignore[attr-defined]
            if "hapax_affordance_recruitment_total" in names:
                _RECRUITMENT_COUNTER = collector
                _PROMETHEUS_AVAILABLE = True
                break
    except Exception:
        log.debug("could not recover existing recruitment counter", exc_info=True)


def domain_label_for(capability_name: str | None) -> str:
    """Map a capability name to its 6-domain label.

    Capability names in the registry use ``<prefix>.<verb_phrase>`` form
    (e.g. ``env.weather_conditions``, ``studio.compose_camera_grid``).
    The prefix is the registry domain; this function collapses that
    onto the canonical 6-domain taxonomy.
    """

    if not capability_name or "." not in capability_name:
        return UNKNOWN_DOMAIN
    prefix = capability_name.split(".", 1)[0]
    return _PREFIX_TO_TAXONOMY.get(prefix, UNKNOWN_DOMAIN)


def record_recruitment(capability_name: str | None) -> None:
    """Increment ``hapax_affordance_recruitment_total{domain=<...>}``.

    No-op when prometheus_client is unavailable. Safe to call from any
    thread; ``Counter.inc()`` is thread-safe by design.
    """

    if _RECRUITMENT_COUNTER is None:
        return
    domain = domain_label_for(capability_name)
    try:
        _RECRUITMENT_COUNTER.labels(domain=domain).inc()
    except Exception:
        log.debug("recruitment counter inc failed", exc_info=True)


def recruitment_counter_value(domain: str) -> float | None:
    """Return current counter value for a domain label (test introspection).

    Returns ``None`` when prometheus_client is unavailable.
    """

    if _RECRUITMENT_COUNTER is None:
        return None
    try:
        return float(_RECRUITMENT_COUNTER.labels(domain=domain)._value.get())
    except Exception:
        log.debug("recruitment counter read failed", exc_info=True)
        return None


__all__ = [
    "ALL_DOMAINS",
    "TAXONOMY_DOMAINS",
    "UNKNOWN_DOMAIN",
    "domain_label_for",
    "record_recruitment",
    "recruitment_counter_value",
]
