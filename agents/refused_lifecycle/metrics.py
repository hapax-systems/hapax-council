"""Shared Prometheus metrics for the refused-lifecycle substrate.

All three watchers (structural / constitutional / conditional) share the
``probes_total`` and ``probe_failures_total`` counters; the ``trigger``
label discriminates them. The runner's ``transitions_total`` lives here
too so any caller importing the module gets the full metric set without
having to also import runner. Centralising registration avoids
``CollectorRegistry`` duplicate-timeseries errors when more than one
watcher module is loaded in the same process (e.g., during pytest
collection).
"""

from __future__ import annotations

from prometheus_client import Counter

probes_total = Counter(
    "hapax_refused_lifecycle_probes_total",
    "Refused-lifecycle probes executed (any outcome).",
    ["trigger", "slug"],
)

probe_failures_total = Counter(
    "hapax_refused_lifecycle_probe_failures_total",
    "Refused-lifecycle probe failures by reason.",
    ["trigger", "slug", "reason"],
)

# Per-transition counter labelled with from_state, to_state, slug. Slug
# label is high-cardinality but bounded by the active cc-task set (~40).
transitions_total = Counter(
    "hapax_refused_lifecycle_transitions_total",
    "Refused-lifecycle state-machine transitions emitted by the runner.",
    ["from_state", "to_state", "slug"],
)


__all__ = ["probe_failures_total", "probes_total", "transitions_total"]
