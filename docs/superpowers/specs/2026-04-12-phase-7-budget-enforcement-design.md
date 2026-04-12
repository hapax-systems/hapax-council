# Phase 7: Budget Enforcement — Design Spec

**Date:** 2026-04-12
**Status:** Approved (self-authored, alpha session)
**Epic:** `docs/superpowers/plans/2026-04-12-compositor-unification-epic.md`
**Phase:** 7 of 7 (final planned phase)
**Risk:** Low (purely additive; no rendering paths break under default config)
**Depends on:** Phase 3b complete (`CairoSourceRunner` exists)

---

## Purpose

Prevent expensive content from degrading the overall stream. Track
per-source frame-time, expose rolling averages for observability, and
skip sources that exceed their budget — falling back to the cached
texture from the previous frame so the operator never sees a stall.

After Phase 7:

- Every Cairo source's render is wrapped in a timer.
- A `BudgetTracker` holds a rolling window of recent frame times per
  source plus aggregate stats (last/avg/p95).
- Aggregated stats publish to `/dev/shm/hapax-compositor/source-costs.json`
  for Grafana / waybar / external observability.
- Sources with `budget_ms` configured are skipped when their last
  frame exceeded budget; the cached surface from the previous tick
  is reused. After N consecutive skips, the runner emits a degraded
  signal (logged + count exposed) so the operator knows the stream
  is running below spec.
- The default budget is `None` (unlimited) — no source is skipped
  unless its config explicitly opts in. Phase 7 adds the *machinery*
  without changing existing behavior.

This is the final planned phase of the compositor unification epic.
After 7 ships, the only remaining work is Phase 5b (GStreamer + wgpu
unification), which is a multi-week migration on its own.

---

## Coexistence with `CairoSourceRunner`

Phase 3b's `CairoSourceRunner` already tracks `last_render_ms` and
`frame_count` per source instance. Phase 7 builds on this:

- A new optional `budget_tracker` parameter on the runner.
- When supplied, the runner calls `tracker.record(source_id, ms)`
  after every successful render.
- A new optional `budget_ms` parameter caps per-frame work; when
  exceeded on the previous tick, the next tick is skipped.
- Default behavior is unchanged: no tracker, no budget, no skips.

The runner's existing `_last_render_ms` field becomes the source of
truth for "what just happened on this thread"; the BudgetTracker is
the source of truth for "rolling state across many frames."

---

## Scope

Two sub-phases per the master plan, **shipped as one PR** because
they're tightly coupled:

1. **Phase 7a — Per-source frame-time accounting.**
   New `BudgetTracker` class. Rolling window per source. Last/avg/p95
   queries. `publish_costs(path)` writes the JSON snapshot.
   `CairoSourceRunner` gains an opt-in tracker parameter.

2. **Phase 7b — Skip-if-over-budget with fallback.**
   `BudgetTracker.over_budget(source_id, budget_ms)` query.
   `CairoSourceRunner` gains an opt-in `budget_ms` parameter; when
   set, the runner skips this tick if last frame exceeded budget,
   logs the skip, and increments a `degraded_count`. After N
   consecutive skips the runner stays in "degraded" mode until a
   render succeeds within budget.

The combined PR is small (~350 lines net) and ships as one cohesive
piece. Each sub-phase is independently testable within the PR.

---

## File structure

| File | Purpose |
|---|---|
| `agents/studio_compositor/budget.py` | `BudgetTracker`, `SourceCost`, `publish_costs` |
| `agents/studio_compositor/cairo_source.py` | Add `budget_tracker` + `budget_ms` to `CairoSourceRunner` |
| `tests/test_budget.py` | 18+ unit tests covering tracker, integration, publish |

---

## BudgetTracker

```python
"""Per-source frame-time accounting and budget enforcement.

Phase 7 of the compositor unification epic. The tracker holds a
rolling window of recent frame times per source and exposes
aggregate stats (last, avg, p95) for observability and over-budget
decisions.

Usage:

    tracker = BudgetTracker(window_size=120)  # ~4s at 30fps
    tracker.record("sierpinski-lines", elapsed_ms=12.5)
    tracker.last_frame_ms("sierpinski-lines")  # 12.5
    tracker.avg_frame_ms("sierpinski-lines")   # 12.5

    if tracker.over_budget("sierpinski-lines", budget_ms=5.0):
        # Last frame exceeded budget — skip this tick.
        ...

    publish_costs(tracker, Path("/dev/shm/hapax-compositor/source-costs.json"))

The class is thread-safe; multiple CairoSourceRunner background
threads can call ``record()`` concurrently.
"""
```

```python
@dataclass(frozen=True)
class SourceCost:
    """Aggregated per-source cost metrics. Snapshot returned by
    BudgetTracker.snapshot()."""

    source_id: str
    sample_count: int
    last_ms: float
    avg_ms: float
    p95_ms: float
    over_budget_count: int


class BudgetTracker:
    def __init__(self, window_size: int = 120) -> None: ...
    def record(self, source_id: str, elapsed_ms: float) -> None: ...
    def record_skip(self, source_id: str) -> None: ...
    def last_frame_ms(self, source_id: str) -> float: ...
    def avg_frame_ms(self, source_id: str) -> float: ...
    def p95_frame_ms(self, source_id: str) -> float: ...
    def over_budget(self, source_id: str, budget_ms: float) -> bool: ...
    def snapshot(self) -> dict[str, SourceCost]: ...
    def reset(self, source_id: str | None = None) -> None: ...


def publish_costs(tracker: BudgetTracker, path: Path) -> None:
    """Atomically write the tracker's snapshot to a JSON file.

    Used by an external timer (waybar, prometheus exporter, the
    compositor's status loop) to publish the latest state for
    observability dashboards.
    """
```

### Rolling window

Per-source state is a `deque(maxlen=window_size)` of recent
elapsed_ms values. `last_frame_ms` is `deque[-1]`. `avg_frame_ms` is
`sum / len`. `p95_frame_ms` is the 95th percentile of the deque
contents.

The `window_size` default of 120 gives ~4 seconds of history at 30
fps — enough for a stable average without overweighting transient
spikes.

### Over-budget query

```python
def over_budget(self, source_id: str, budget_ms: float) -> bool:
    """True iff the last recorded frame for ``source_id`` exceeded
    ``budget_ms``. Sources with no samples yet are never over budget
    (a source's first frame always renders).
    """
```

### Snapshot for publishing

```python
def snapshot(self) -> dict[str, SourceCost]:
    """Return per-source cost stats. Safe to call from any thread."""
```

`publish_costs(tracker, path)` calls `snapshot()`, serializes via
`json.dumps`, and writes atomically (write to `.tmp`, rename) so
external readers never see a partial file.

---

## CairoSourceRunner integration

```python
class CairoSourceRunner:
    def __init__(
        self,
        source_id: str,
        source: CairoSource,
        canvas_w: int = 1920,
        canvas_h: int = 1080,
        target_fps: float = 10.0,
        publish_to_source_protocol: bool = False,
        budget_tracker: BudgetTracker | None = None,   # NEW
        budget_ms: float | None = None,                # NEW
    ) -> None: ...
```

### Record path (7a)

After every successful render in `_render_one_frame()`:

```python
if self._budget_tracker is not None:
    self._budget_tracker.record(self._source_id, self._last_render_ms)
```

### Skip path (7b)

At the top of `_render_one_frame()`, before allocating the surface:

```python
if (
    self._budget_ms is not None
    and self._budget_tracker is not None
    and self._budget_tracker.over_budget(self._source_id, self._budget_ms)
):
    self._budget_tracker.record_skip(self._source_id)
    self._consecutive_skips += 1
    return
self._consecutive_skips = 0
```

A new `_consecutive_skips` field tracks the run length. The runner
exposes it via a `degraded` property — `True` when the count exceeds
a threshold (default 5). The operator can read it for the source-cost
JSON or for stimmung gating.

When a tick is skipped, the cached output surface from the previous
successful tick stays in place — `get_output_surface()` keeps
returning the most recent valid frame. Synchronous consumers (the
GStreamer cairooverlay path) blit the same surface they would have
the previous frame.

---

## Tests

`tests/test_budget.py`:

### BudgetTracker basics
- `test_record_appends_to_window`
- `test_record_zero_samples_returns_zero`
- `test_last_frame_ms_returns_most_recent`
- `test_avg_frame_ms_smooths_across_window`
- `test_p95_frame_ms_picks_high_percentile`
- `test_window_evicts_oldest_after_max_size`
- `test_record_unknown_source_creates_entry`
- `test_reset_one_source_clears_only_that_source`
- `test_reset_all_clears_every_source`
- `test_concurrent_record_is_thread_safe`

### Over-budget
- `test_over_budget_false_when_no_samples`
- `test_over_budget_false_when_last_frame_within_budget`
- `test_over_budget_true_when_last_frame_exceeds_budget`
- `test_over_budget_uses_only_last_frame_not_average`

### Snapshot + publish
- `test_snapshot_returns_per_source_cost`
- `test_snapshot_includes_skip_count`
- `test_publish_costs_writes_json_atomically`

### CairoSourceRunner integration
- `test_runner_records_to_tracker_when_provided`
- `test_runner_no_record_when_tracker_is_none`
- `test_runner_skips_when_over_budget`
- `test_runner_skip_preserves_cached_surface`
- `test_runner_consecutive_skips_track_degraded_count`
- `test_runner_degraded_clears_after_successful_render`

---

## Acceptance

- `agents/studio_compositor/budget.py::BudgetTracker` exists with
  rolling window + percentile + over-budget queries
- `publish_costs(tracker, path)` writes a JSON snapshot atomically
- `CairoSourceRunner` accepts opt-in `budget_tracker` and `budget_ms`
  parameters with default `None` (no behavior change without
  explicit opt-in)
- The tracker is thread-safe (concurrent record from multiple runner
  threads)
- ~22 new tests pass
- `uv run ruff check` clean
- `uv run pyright` clean
- Visual output unchanged when no budget is configured (which is
  the default for every existing source)

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Budget enforcement skips a source the operator wants visible | Medium | Medium | Default `budget_ms=None` means no skips. Operators opt in per source. |
| Tracker memory grows unbounded with many sources | Low | Low | Per-source state is bounded by window_size; total is bounded by the small number of sources |
| Concurrent record from many threads serializes on the lock | Low | Low | Lock is held for the deque append + counter increment only — sub-microsecond critical section |
| publish_costs writes a partial file under load | Low | Medium | Atomic write via tmp + rename; readers always see a complete file |
| Skip path skips the *first* render after init (no samples → over budget?) | Low | Medium | over_budget returns False when there are no samples — first frame always renders |

---

## Not in scope

Phase 7 does not:

- Auto-tune budgets based on stimmung or operator energy (Phase 4
  optimizations cover most of the same ground via dead-source
  culling and version caching)
- Schedule sources across frames to share budget (the runner is
  per-source; cross-source scheduling is a Phase 4-rust follow-up)
- Wire `degraded_count` into stimmung (separate stim integration
  task; the data is exposed but no consumer is added)
- Migrate Phase 3b's `last_render_ms` field into the tracker (the
  runner keeps both — `_last_render_ms` is per-thread instant state,
  the tracker is the rolling state)
- Add per-frame budgets at the layout level (per-source only)

---

## Success metrics

Phase 7 is complete when:

- A source with `budget_ms=5.0` configured will skip frames whose
  predecessor exceeded 5ms
- Skipped frames preserve the previous frame's output (no visual
  glitches)
- The tracker exposes per-source last/avg/p95 stats via `snapshot()`
- `publish_costs()` writes a well-formed JSON file readable by
  Grafana / waybar / external observers
- All 22 tests pass
- No existing source's behavior changes (every existing
  CairoSourceRunner call site uses default `budget_ms=None`)
