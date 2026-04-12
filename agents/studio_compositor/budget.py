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

import json
import logging
import os
import threading
from collections import deque
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_WINDOW_SIZE = 120
"""Default rolling window depth (~4 seconds at 30 fps)."""


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
        """
        with self._lock:
            state = self._states.get(source_id)
            if state is None:
                state = _SourceState(samples=deque(maxlen=self._window_size))
                self._states[source_id] = state
            state.samples.append(elapsed_ms)

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

    Atomic means: write to ``path.tmp`` first, then ``os.replace``
    onto the final path. External readers either see the previous
    file or the new one — never a partial write.
    """
    snapshot = tracker.snapshot()
    serializable = {
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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(serializable, indent=2))
    os.replace(tmp_path, path)


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
