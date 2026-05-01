"""Prometheus histogram for AffordancePipeline winner score distribution.

Pairs with the recruitment / dispatch / outcome counter trio. Those
counters give Grafana per-domain volume, per-dropout-reason
breakdowns, and post-recruitment success/failure — but not the
*confidence* distribution of winning selections.

``hapax_affordance_winner_similarity`` is observed inside
``AffordanceMetrics.record_selection`` whenever a non-None winner
emerged, with the cosine similarity (already in [0, 1]) as the
observation. Operators can read percentiles in Grafana to tune the
``THRESHOLD`` constant in ``shared.affordance_pipeline`` and to spot
drift when an embedding source degrades.

Importing this module is safe even when ``prometheus_client`` is
unavailable: ``observe_winner_similarity`` is then a no-op and
``winner_similarity_observation_count`` returns ``None``.
"""

from __future__ import annotations

import logging
from typing import Any, Final

log = logging.getLogger(__name__)

# Linear 11-bucket cover of cosine space. Cosine similarity is bounded
# in [0, 1] so we don't need a +Inf overflow past 1.0; prometheus_client
# adds its own +Inf sentinel automatically.
WINNER_SIMILARITY_BUCKETS: Final[tuple[float, ...]] = (
    0.0,
    0.1,
    0.2,
    0.3,
    0.4,
    0.5,
    0.6,
    0.7,
    0.8,
    0.9,
    1.0,
)


_PROMETHEUS_AVAILABLE = False
_WINNER_SIMILARITY_HIST: Any = None
try:
    from prometheus_client import Histogram

    _WINNER_SIMILARITY_HIST = Histogram(
        "hapax_affordance_winner_similarity",
        "Cosine-similarity score of the winning selection candidate per select() call.",
        buckets=WINNER_SIMILARITY_BUCKETS,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    log.debug("prometheus_client not available — winner-similarity histogram disabled")
except ValueError:
    # Re-import / test reload races: recover the existing collector.
    try:
        from prometheus_client import REGISTRY

        for collector in list(REGISTRY._collector_to_names):  # type: ignore[attr-defined]
            names = REGISTRY._collector_to_names.get(collector, ())  # type: ignore[attr-defined]
            if "hapax_affordance_winner_similarity" in names:
                _WINNER_SIMILARITY_HIST = collector
                _PROMETHEUS_AVAILABLE = True
                break
    except Exception:
        log.debug("could not recover existing winner-similarity histogram", exc_info=True)


def observe_winner_similarity(similarity: float) -> None:
    """Observe one cosine-similarity value into the histogram.

    No-op when prometheus_client is unavailable. Caller is responsible
    for passing only winner observations (i.e. ``similarity > 0`` from
    a non-None winner) — there is no inferred ``no-winner`` semantic.

    Out-of-range observations (negative, NaN, > 1.0) are clamped to
    [0, 1] before observation so a buggy upstream cannot corrupt the
    histogram with values that fall outside the bucket cover.
    """

    if _WINNER_SIMILARITY_HIST is None:
        return
    try:
        value = float(similarity)
    except (TypeError, ValueError):
        return
    # NaN check must happen BEFORE max/min: Python's min/max with NaN
    # is order-dependent and silently returns the non-NaN argument
    # rather than propagating NaN.
    if value != value:
        return
    clamped = max(0.0, min(1.0, value))
    try:
        _WINNER_SIMILARITY_HIST.observe(clamped)
    except Exception:
        log.debug("winner-similarity observe failed", exc_info=True)


def winner_similarity_observation_count() -> float | None:
    """Return the histogram's total observation count (test introspection).

    Returns ``None`` when prometheus_client is unavailable.
    """

    if _WINNER_SIMILARITY_HIST is None:
        return None
    try:
        return float(_WINNER_SIMILARITY_HIST._sum.get())  # type: ignore[attr-defined]
    except Exception:
        log.debug("winner-similarity sum read failed", exc_info=True)
        return None


def winner_similarity_total_count() -> int | None:
    """Return the histogram's total event count (sum across buckets).

    Returns ``None`` when prometheus_client is unavailable. Reads via
    ``collect()`` so the histogram's published ``_count`` sample is
    authoritative — the per-bucket ``_buckets`` array is non-cumulative
    (each Counter holds the count for that bucket only) and a +Inf
    overflow bucket is appended automatically; summing or reading the
    last bucket gives the wrong answer.
    """

    if _WINNER_SIMILARITY_HIST is None:
        return None
    try:
        for metric in _WINNER_SIMILARITY_HIST.collect():
            for sample in metric.samples:
                if sample.name.endswith("_count") and not sample.name.endswith("_bucket_count"):
                    # Histogram emits one ``<metric>_count`` sample carrying the
                    # total observation count.
                    if sample.name == "hapax_affordance_winner_similarity_count":
                        return int(sample.value)
        return 0
    except Exception:
        log.debug("winner-similarity count read failed", exc_info=True)
        return None


__all__ = [
    "WINNER_SIMILARITY_BUCKETS",
    "observe_winner_similarity",
    "winner_similarity_observation_count",
    "winner_similarity_total_count",
]
