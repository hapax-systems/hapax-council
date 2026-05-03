"""Per-ward rolling-window visible-seconds tracker (recruitment-bias source).

Per cc-task ``p3-governance-recruitment-bias-replacement``: this module
**replaced** the prior FamilyCeilingTracker (#2259) which carried a
hardcoded threshold table (DURF 15%, M8 12%, Polyend 10%, Steam Deck 8%)
plus per-ward eviction priorities. That table was a static expert-system
rule and violated ``feedback_no_expert_system_rules`` per the
2026-05-02 24h independent-auditor batch (Auditor B finding #8).

Current shape: **bias-only**. Records visible-seconds per ward in a
rolling 60-min window. Exposes a multiplicative score adjustment via
``visible_time_bias_score()`` that the affordance pipeline applies to
ward-tagged candidates so a ward dominating recent visible-time loses
recruitment score proportionally — a competitor wins the next cycle
without any expert-rule ceiling fixed in advance.

Design constraints (non-negotiable per the governance correction):

- NO static threshold table / per-ward percentage constants.
- NO eviction priorities.
- NO ``consult(...)`` returning ceiling decisions.
- NO ``evictable_order(...)``.
- NO per-ward ``register_ward(...)`` policy registration.

What stays:

- :class:`WardVisibilityWindowTracker` — pure-logic rolling-window
  recorder. ``mark_visible_window`` + ``consumed_seconds``.
- :func:`visible_time_bias_score` — a stateless function over
  ``(consumed_s, window_s)`` returning a multiplicative score
  adjustment in ``[BIAS_FLOOR, BIAS_CEILING]``.

The AffordancePipeline (``shared/affordance_pipeline.py``) reads from
a process-shared :func:`get_default_tracker` singleton when scoring
ward candidates so the bias source is accessible from both the router
(writer) and the pipeline (reader) without a coupling import cycle.
"""

from __future__ import annotations

from collections import defaultdict, deque

#: Rolling window the tracker observes. Matches
#: :data:`agents.studio_compositor.activity_reveal_ward.DEFAULT_ROLLING_WINDOW_S`
#: so the per-ward visibility window the mixin already records and the
#: recruitment-bias window agree on the same epoch.
DEFAULT_VISIBILITY_WINDOW_S: float = 3600.0

#: At zero consumption the bias is the multiplicative identity (no
#: penalty). Recruitment scoring is unaffected for inactive wards.
BIAS_CEILING: float = 1.0

#: At full-window saturation (consumed == window_s) the bias scales
#: composed scores to half. The bias is intentionally bounded ABOVE
#: zero so a ward never loses its recruitability outright via
#: visible-time penalty alone — competing capabilities can still pull
#: it back down through the normal score-composition cascade, but a
#: ward saturated in the trailing window remains a viable choice for
#: cases where no competitor exceeds its biased score.
BIAS_FLOOR: float = 0.5


def visible_time_bias_score(
    consumed_s: float, *, window_s: float = DEFAULT_VISIBILITY_WINDOW_S
) -> float:
    """Return a multiplicative recruitment-score adjustment in
    ``[BIAS_FLOOR, BIAS_CEILING]`` for a ward that consumed
    ``consumed_s`` visible-seconds in the trailing ``window_s`` window.

    Linear interpolation between ``BIAS_CEILING`` (zero consumption)
    and ``BIAS_FLOOR`` (full-window saturation). Half-window
    consumption (30 min in 60 min) → bias = 0.75. The bias is the
    same shape regardless of which ward; the recruitment cascade
    decides who wins after applying it (vs the deleted table that
    pre-decided ceiling order outside the recruitment loop).

    Stateless helper — pure function over its arguments. The tracker
    below is the only piece carrying mutable state.
    """
    if window_s <= 0:
        return BIAS_CEILING
    consumption = min(1.0, max(0.0, consumed_s / window_s))
    return BIAS_CEILING - (BIAS_CEILING - BIAS_FLOOR) * consumption


class WardVisibilityWindowTracker:
    """Rolling-window per-ward visible-seconds recorder.

    Pure logic: no I/O, no threading, deterministic. Records intervals
    via :meth:`mark_visible_window` and answers "how many visible
    seconds in the rolling window ending at ``now``?"

    The tracker stores intervals as ``(start_ts, end_ts)`` tuples per
    ward and evicts entries whose ``end_ts`` is older than the rolling
    window on every read. No policies, no ceilings, no priorities —
    those would be expert-system rules and were removed per cc-task
    ``p3-governance-recruitment-bias-replacement``.

    Thread safety: not thread-safe by itself. The router writes from
    one tick loop; the pipeline reads from one select() call at a
    time. Callers wanting concurrent updates serialize externally.
    """

    def __init__(self, *, window_s: float = DEFAULT_VISIBILITY_WINDOW_S) -> None:
        if window_s <= 0:
            raise ValueError(f"window_s must be > 0, got {window_s}")
        self._window_s = window_s
        self._intervals: dict[str, deque[tuple[float, float]]] = defaultdict(deque)

    @property
    def window_s(self) -> float:
        return self._window_s

    def mark_visible_window(self, ward_id: str, start_ts: float, end_ts: float) -> None:
        """Record a closed visibility interval for ``ward_id``.

        No-op if ``end_ts < start_ts`` (defensive — clock-skew /
        out-of-order callers don't poison the tracker).
        """
        if end_ts < start_ts:
            return
        self._intervals[ward_id].append((start_ts, end_ts))
        self._evict_expired(ward_id, now=end_ts)

    def consumed_seconds(self, ward_id: str, *, now: float) -> float:
        """Visible-seconds for ``ward_id`` inside the rolling window
        ending at ``now``. Properly trims intervals that overlap the
        window edge."""
        self._evict_expired(ward_id, now=now)
        cutoff = now - self._window_s
        total = 0.0
        for start_ts, end_ts in self._intervals[ward_id]:
            trimmed_start = max(start_ts, cutoff)
            trimmed_end = min(end_ts, now)
            if trimmed_end > trimmed_start:
                total += trimmed_end - trimmed_start
        return total

    def bias_score(self, ward_id: str, *, now: float) -> float:
        """Convenience: visible_time_bias_score for this ward at now."""
        return visible_time_bias_score(
            self.consumed_seconds(ward_id, now=now), window_s=self._window_s
        )

    def _evict_expired(self, ward_id: str, *, now: float) -> None:
        cutoff = now - self._window_s
        intervals = self._intervals[ward_id]
        while intervals and intervals[0][1] < cutoff:
            intervals.popleft()


# ── Process-shared singleton (read-side bridge from AffordancePipeline) ──
#
# The tracker is written by ActivityRouter on every tick and read by
# AffordancePipeline.select() on every recruitment cycle. Both run in
# the same compositor process. A module-level singleton (lazy-init)
# is sufficient and avoids passing the tracker through 6 layers of
# call sites. The router and the pipeline both call get_default_tracker.

_DEFAULT_TRACKER: WardVisibilityWindowTracker | None = None


def get_default_tracker() -> WardVisibilityWindowTracker:
    """Process-singleton accessor for the visibility-window tracker.

    Lazy-init on first call. The router writes via
    ``mark_visible_window``; the affordance pipeline reads via
    ``bias_score``. Tests can swap the singleton via :func:`set_default_tracker`.
    """
    global _DEFAULT_TRACKER
    if _DEFAULT_TRACKER is None:
        _DEFAULT_TRACKER = WardVisibilityWindowTracker()
    return _DEFAULT_TRACKER


def set_default_tracker(tracker: WardVisibilityWindowTracker | None) -> None:
    """Replace the process-singleton (test seam). Pass ``None`` to
    reset; the next :func:`get_default_tracker` call lazy-inits a
    fresh tracker."""
    global _DEFAULT_TRACKER
    _DEFAULT_TRACKER = tracker


__all__ = [
    "BIAS_CEILING",
    "BIAS_FLOOR",
    "DEFAULT_VISIBILITY_WINDOW_S",
    "WardVisibilityWindowTracker",
    "get_default_tracker",
    "set_default_tracker",
    "visible_time_bias_score",
]
