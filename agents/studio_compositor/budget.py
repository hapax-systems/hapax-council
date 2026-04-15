"""Per-source frame-time accounting and budget enforcement.

Phase 7 of the compositor unification epic. The :class:`BudgetTracker`
holds a rolling window of recent frame times per source and exposes
aggregate stats (last, avg, p95) for observability and over-budget
decisions. The :func:`publish_costs` helper writes the snapshot to
a JSON file atomically so external observers (Grafana, waybar,
prometheus) get a consistent view.

The tracker is the rolling, cross-frame source of truth. The runner-
local ``CairoSourceRunner._last_render_ms`` field stays as instant
state for the rendering thread.

Default behavior of :class:`CairoSourceRunner` is unchanged: no
tracker, no budget, no skips. Phase 7 adds the machinery; opt-in is
per-source via ``budget_ms`` config.

See: docs/superpowers/specs/2026-04-12-phase-7-budget-enforcement-design.md
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

# Re-exported from atomic_io so legacy callers (and the test mocks at
# `agents.studio_compositor.budget.atomic_write_json`) keep working.
# See drop #41 finding 2: this symbol previously lived here and
# ``budget_signal`` imported it from ``budget``, creating a cycle with
# ``metrics.py``'s force-import of ``budget_signal``. Moving the
# helper to a standalone module breaks the cycle.
from agents.studio_compositor.atomic_io import atomic_write_json  # noqa: F401

log = logging.getLogger(__name__)

COSTS_SCHEMA_VERSION = 1
"""Schema version embedded in publish_costs output.

Bumped whenever the payload shape changes in a breaking way. Readers
can refuse to parse unknown versions rather than silently misreading.
"""

DEFAULT_WINDOW_SIZE = 120
"""Default rolling window depth (~4 seconds at 30 fps)."""


# Follow-up ticket #6 from the post-epic audit retirement handoff:
# gauge publish_costs with a FreshnessGauge so a silent stop of the
# publish-costs path becomes visible on the compositor's Prometheus
# exporter. The gauge is constructed at import time — if no caller
# ever invokes publish_costs the age metric stays ``+inf`` and the
# dead path is loud instead of silent. Beta's PR #752 Phase 4 flagged
# the compositor publish-costs wiring as a candidate dead path; this
# gauge will make that status directly observable.
#
# Registry plumbing: the compositor's /metrics HTTP server at :9482
# uses a custom ``CollectorRegistry`` (see metrics.REGISTRY), not the
# default prometheus_client global. FreshnessGauge must register to
# the custom one or it is scraped-invisible. ``metrics._init_metrics``
# runs at metrics.py import time, so by the time this module is
# imported from metrics.py (see the force-import block at the bottom
# of metrics.py), REGISTRY is populated.
try:
    from shared.freshness_gauge import FreshnessGauge

    try:
        from agents.studio_compositor.metrics import (
            REGISTRY as _COMPOSITOR_METRICS_REGISTRY,
        )
    except ImportError:
        _COMPOSITOR_METRICS_REGISTRY = None  # type: ignore[assignment]

    _PUBLISH_COSTS_FRESHNESS: FreshnessGauge | None = FreshnessGauge(
        name="compositor_publish_costs",
        expected_cadence_s=1.0,
        registry=_COMPOSITOR_METRICS_REGISTRY,
    )
except Exception:  # pragma: no cover — prometheus_client optional
    log.warning(
        "FreshnessGauge unavailable for publish_costs; continuing without metric",
        exc_info=True,
    )
    _PUBLISH_COSTS_FRESHNESS = None


@dataclass(frozen=True)
class SourceCost:
    """Aggregated per-source cost metrics.

    Returned by :meth:`BudgetTracker.snapshot`. Frozen so it can be
    serialized via JSON or hashed as a cache key.
    """

    source_id: str
    sample_count: int
    last_ms: float
    avg_ms: float
    p95_ms: float
    skip_count: int


@dataclass
class _SourceState:
    """Internal: per-source rolling state.

    Lives inside the BudgetTracker. The deque holds the last
    ``window_size`` samples; the counters are unbounded.
    """

    samples: deque[float]
    skip_count: int = 0


class BudgetTracker:
    """Thread-safe per-source rolling cost tracker.

    A single tracker is shared across every :class:`CairoSourceRunner`
    in the process. Concurrent ``record()`` calls from runner background
    threads are safe; the lock is held only for the deque append +
    counter increment, so the critical section is sub-microsecond.

    The window size defaults to 120 samples — about 4 seconds of
    history at 30 fps, enough for a stable rolling average without
    overweighting transient spikes.
    """

    def __init__(self, window_size: int = DEFAULT_WINDOW_SIZE) -> None:
        if window_size < 1:
            raise ValueError(f"window_size must be >= 1, got {window_size}")
        self._window_size = window_size
        self._states: dict[str, _SourceState] = {}
        self._lock = threading.Lock()

    @property
    def window_size(self) -> int:
        return self._window_size

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, source_id: str, elapsed_ms: float) -> None:
        """Record one frame's elapsed time in ms for ``source_id``.

        New sources are auto-created on first record. The deque
        evicts the oldest sample when ``window_size`` is exceeded.

        Drop #41 C1: also observes into the per-source Prometheus
        histogram so dashboards can answer "which source is closest
        to starving the layout budget" without scraping `costs.json`.
        Histogram observation is best-effort — if metrics aren't
        initialized (test envs, prometheus_client not importable) the
        recording proceeds normally and only the in-process rolling
        window is updated.
        """
        with self._lock:
            state = self._states.get(source_id)
            if state is None:
                state = _SourceState(samples=deque(maxlen=self._window_size))
                self._states[source_id] = state
            state.samples.append(elapsed_ms)
        try:
            from agents.studio_compositor import metrics as _metrics

            if _metrics.COMP_SOURCE_RENDER_DURATION_MS is not None:
                _metrics.COMP_SOURCE_RENDER_DURATION_MS.labels(source_id=source_id).observe(
                    elapsed_ms
                )
        except Exception:
            pass

    def record_skip(self, source_id: str) -> None:
        """Record that a tick was skipped (over budget).

        Increments the skip counter without touching the samples
        deque so skipped frames don't pollute the average.
        """
        with self._lock:
            state = self._states.get(source_id)
            if state is None:
                state = _SourceState(samples=deque(maxlen=self._window_size))
                self._states[source_id] = state
            state.skip_count += 1

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def last_frame_ms(self, source_id: str) -> float:
        """Return the most recent recorded frame time, or 0.0."""
        with self._lock:
            state = self._states.get(source_id)
            if state is None or not state.samples:
                return 0.0
            return state.samples[-1]

    def avg_frame_ms(self, source_id: str) -> float:
        """Return the rolling-window average frame time, or 0.0."""
        with self._lock:
            state = self._states.get(source_id)
            if state is None or not state.samples:
                return 0.0
            return sum(state.samples) / len(state.samples)

    def p95_frame_ms(self, source_id: str) -> float:
        """Return the 95th percentile of the rolling window, or 0.0.

        Uses linear interpolation between the two nearest samples;
        for small windows this is dominated by the maximum sample,
        which is the conservative answer for budget decisions.
        """
        with self._lock:
            state = self._states.get(source_id)
            if state is None or not state.samples:
                return 0.0
            sorted_samples = sorted(state.samples)
            return _percentile(sorted_samples, 0.95)

    def over_budget(self, source_id: str, budget_ms: float) -> bool:
        """True iff the most recent frame for ``source_id`` exceeded budget.

        Sources with no recorded samples (e.g. the very first tick
        after init) are never over budget — the first frame always
        renders so the operator gets at least one image.
        """
        return self.last_frame_ms(source_id) > budget_ms

    # ------------------------------------------------------------------
    # Followup F2: per-frame layout budgets
    # ------------------------------------------------------------------

    def total_last_frame_ms(self, source_ids: list[str] | None = None) -> float:
        """Sum of the most recent frame times across the given sources.

        When ``source_ids`` is None, sums every recorded source. The
        operator's compositor code passes the active source list from
        the current CompiledFrame to get the per-frame total against
        the layout's overall frame budget.

        Sources with no recorded samples contribute 0.0.
        """
        with self._lock:
            if source_ids is None:
                ids = list(self._states.keys())
            else:
                ids = source_ids
            total = 0.0
            for source_id in ids:
                state = self._states.get(source_id)
                if state is None or not state.samples:
                    continue
                total += state.samples[-1]
            return total

    def total_avg_frame_ms(self, source_ids: list[str] | None = None) -> float:
        """Sum of the rolling-window averages across the given sources.

        Used for budget decisions that look at sustained cost rather
        than the most recent frame. Smoother than ``total_last_frame_ms``
        — appropriate when the executor wants to react to trends, not
        spikes.
        """
        with self._lock:
            if source_ids is None:
                ids = list(self._states.keys())
            else:
                ids = source_ids
            total = 0.0
            for source_id in ids:
                state = self._states.get(source_id)
                if state is None or not state.samples:
                    continue
                total += sum(state.samples) / len(state.samples)
            return total

    def over_layout_budget(
        self,
        layout_budget_ms: float,
        source_ids: list[str] | None = None,
    ) -> bool:
        """True iff the most recent frame total exceeded the layout budget.

        Used by the host compositor's frame planner to decide whether
        to drop the lowest-priority sources from the next frame.
        Returns False when no samples have been recorded yet (the
        first frame always renders, matching the per-source semantics).
        """
        total = self.total_last_frame_ms(source_ids)
        if total == 0.0:
            return False
        return total > layout_budget_ms

    def headroom_ms(
        self,
        layout_budget_ms: float,
        source_ids: list[str] | None = None,
    ) -> float:
        """Return remaining budget in ms after the last frame's total.

        Negative when over budget. Used for proportional throttling
        decisions ("we have X ms left, what can we squeeze in?").
        """
        return layout_budget_ms - self.total_last_frame_ms(source_ids)

    # ------------------------------------------------------------------
    # Snapshot + serialization
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, SourceCost]:
        """Return per-source cost stats as a snapshot dict.

        Safe to call from any thread. The returned values are an
        immutable copy; mutating the tracker afterwards does not
        affect the snapshot.
        """
        with self._lock:
            out: dict[str, SourceCost] = {}
            for source_id, state in self._states.items():
                if not state.samples:
                    out[source_id] = SourceCost(
                        source_id=source_id,
                        sample_count=0,
                        last_ms=0.0,
                        avg_ms=0.0,
                        p95_ms=0.0,
                        skip_count=state.skip_count,
                    )
                    continue
                sorted_samples = sorted(state.samples)
                out[source_id] = SourceCost(
                    source_id=source_id,
                    sample_count=len(state.samples),
                    last_ms=state.samples[-1],
                    avg_ms=sum(state.samples) / len(state.samples),
                    p95_ms=_percentile(sorted_samples, 0.95),
                    skip_count=state.skip_count,
                )
            return out

    def reset(self, source_id: str | None = None) -> None:
        """Clear samples + skip counter for one source, or every source."""
        with self._lock:
            if source_id is None:
                self._states.clear()
                return
            self._states.pop(source_id, None)


def publish_costs(tracker: BudgetTracker, path: Path) -> None:
    """Atomically write the tracker's snapshot to a JSON file.

    Used by an external timer (waybar tick, prometheus exporter, the
    compositor's status loop) to publish the latest state for
    observability dashboards.

    The payload is wrapped with a top-level metadata envelope so
    readers can distinguish stale snapshots from fresh ones without
    needing to ``stat()`` the file:

    .. code-block:: json

        {
          "schema_version": 1,
          "timestamp_ms": 12345.678,
          "wall_clock": 1728000000.123,
          "sources": {
            "album-overlay": {"last_ms": 1.2, ...},
            ...
          }
        }

    ``timestamp_ms`` is monotonic (process uptime in milliseconds).
    ``wall_clock`` is ``time.time()`` seconds since the epoch, suitable
    for comparing against system time in operator tooling.
    """
    snapshot = tracker.snapshot()
    sources = {
        source_id: {
            "source_id": cost.source_id,
            "sample_count": cost.sample_count,
            "last_ms": round(cost.last_ms, 3),
            "avg_ms": round(cost.avg_ms, 3),
            "p95_ms": round(cost.p95_ms, 3),
            "skip_count": cost.skip_count,
        }
        for source_id, cost in snapshot.items()
    }
    payload = {
        "schema_version": COSTS_SCHEMA_VERSION,
        "timestamp_ms": round(time.monotonic() * 1000.0, 3),
        "wall_clock": round(time.time(), 3),
        "sources": sources,
    }
    try:
        atomic_write_json(payload, path)
    except Exception:
        if _PUBLISH_COSTS_FRESHNESS is not None:
            _PUBLISH_COSTS_FRESHNESS.mark_failed()
        raise
    if _PUBLISH_COSTS_FRESHNESS is not None:
        _PUBLISH_COSTS_FRESHNESS.mark_published()


def _percentile(sorted_samples: list[float], q: float) -> float:
    """Linear-interpolated percentile on a sorted list.

    Returns the maximum sample for q=1.0 and the minimum for q=0.0.
    Empty input returns 0.0; single-sample input returns that sample.
    """
    if not sorted_samples:
        return 0.0
    if len(sorted_samples) == 1:
        return sorted_samples[0]
    if q <= 0.0:
        return sorted_samples[0]
    if q >= 1.0:
        return sorted_samples[-1]
    pos = q * (len(sorted_samples) - 1)
    lo = int(pos)
    hi = lo + 1
    if hi >= len(sorted_samples):
        return sorted_samples[lo]
    frac = pos - lo
    return sorted_samples[lo] * (1.0 - frac) + sorted_samples[hi] * frac
